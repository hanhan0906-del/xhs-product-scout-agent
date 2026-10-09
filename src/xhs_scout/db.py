from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .signals import gray_metric_items
from typing import Iterable


SQLITE_TIMEOUT_SECONDS = 10.0
SQLITE_BUSY_TIMEOUT_MS = 10_000


class RiskStopActiveError(RuntimeError):
    """Raised when an ordinary resume would bypass an active hard risk stop."""


class RiskConfirmationError(ValueError):
    """Raised when an explicit risk-resume confirmation is missing or stale."""


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS search_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    priority INTEGER NOT NULL DEFAULT 50,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_run_at TEXT,
    run_owner TEXT,
    run_lease_expires_at TEXT,
    last_started_at TEXT,
    last_finished_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_leases (
    name TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    title TEXT,
    shop_name TEXT,
    share_url TEXT,
    direct_url TEXT,
    price REAL,
    is_virtual INTEGER,
    virtual_confidence REAL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_sales_follows (
    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    followed_at TEXT NOT NULL,
    followed_by TEXT NOT NULL DEFAULT 'workbench'
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER REFERENCES products(id),
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    screenshot_path TEXT,
    raw_text TEXT,
    cumulative_sales_display TEXT,
    cumulative_sales_exact INTEGER,
    cumulative_sales_min INTEGER,
    daily_sales_delta INTEGER,
    sales_24h_min INTEGER,
    sales_7d_min INTEGER,
    sales_30d_min INTEGER,
    cart_24h_min INTEGER,
    new_30d_min INTEGER,
    positive_reviews_30d_min INTEGER,
    favorites_30d_min INTEGER,
    interested_7d_min INTEGER,
    interested_30d_min INTEGER,
    viewers_now INTEGER,
    sales_surging INTEGER NOT NULL DEFAULT 0,
    raw_signals_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS candidate_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    assessed_at TEXT NOT NULL,
    evidence_grade TEXT NOT NULL,
    score REAL NOT NULL,
    low_follower_verified INTEGER NOT NULL DEFAULT 0,
    reasons_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate'
);

CREATE TABLE IF NOT EXISTS note_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    recorded_at TEXT NOT NULL,
    author_name TEXT,
    follower_count INTEGER NOT NULL,
    likes INTEGER NOT NULL DEFAULT 0,
    collects INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    published_days_ago INTEGER,
    source_note TEXT
);

CREATE TABLE IF NOT EXISTS note_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER REFERENCES products(id),
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL,
    screenshot_path TEXT,
    probe_dir TEXT,
    page_kind TEXT,
    raw_text TEXT,
    author_name TEXT,
    follower_count INTEGER,
    likes INTEGER,
    collects INTEGER,
    comments INTEGER,
    published_days_ago INTEGER,
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS task_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES search_tasks(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    observation_id INTEGER NOT NULL REFERENCES observations(id),
    captured_at TEXT NOT NULL,
    valid INTEGER NOT NULL DEFAULT 1,
    invalid_reason TEXT,
    UNIQUE(task_id, observation_id)
);

CREATE TABLE IF NOT EXISTS search_result_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES search_tasks(id),
    product_id INTEGER REFERENCES products(id),
    observation_id INTEGER REFERENCES observations(id),
    source_keyword TEXT NOT NULL,
    result_rank INTEGER,
    page_kind TEXT,
    search_probe_dir TEXT,
    search_screenshot_path TEXT,
    text_excerpt TEXT,
    recorded_at TEXT NOT NULL,
    valid INTEGER NOT NULL DEFAULT 1,
    invalid_reason TEXT,
    UNIQUE(task_id, observation_id, result_rank)
);

CREATE TABLE IF NOT EXISTS product_keyword_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    observation_id INTEGER NOT NULL REFERENCES observations(id),
    task_id INTEGER NOT NULL REFERENCES search_tasks(id),
    run_id TEXT NOT NULL,
    source_root TEXT NOT NULL,
    source_keyword TEXT NOT NULL,
    raw_title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    search_result_rank INTEGER NOT NULL,
    search_context_recovered INTEGER NOT NULL CHECK(search_context_recovered = 1),
    share_url TEXT,
    link_gap TEXT,
    evidence_path TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    noise_reasons_json TEXT NOT NULL DEFAULT '[]',
    decomposition_status TEXT NOT NULL
        CHECK(decomposition_status IN ('complete', 'evidence_gap', 'risk_blocked')),
    review_status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK(review_status IN ('pending_review', 'approved', 'rejected', 'deprecated')),
    source_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(product_id, observation_id, source_root)
);

CREATE TABLE IF NOT EXISTS product_keyword_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES product_keyword_records(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL
        CHECK(dimension IN ('domain', 'scene', 'audience', 'format', 'stage', 'function')),
    raw_term TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK(review_status IN ('pending_review', 'approved', 'rejected', 'deprecated')),
    created_at TEXT NOT NULL,
    UNIQUE(record_id, dimension, normalized_term)
);

CREATE INDEX IF NOT EXISTS idx_product_keyword_records_source_root
ON product_keyword_records(source_root);

CREATE INDEX IF NOT EXISTS idx_product_keyword_terms_support
ON product_keyword_terms(dimension, normalized_term);

CREATE TABLE IF NOT EXISTS keyword_combination_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_fingerprint TEXT NOT NULL UNIQUE,
    generation_stage TEXT NOT NULL
        CHECK(generation_stage IN ('not_ready', 'sample', 'stable')),
    product_count INTEGER NOT NULL,
    root_count INTEGER NOT NULL,
    domain_scene_count INTEGER NOT NULL,
    shop_count INTEGER NOT NULL,
    context_count INTEGER NOT NULL,
    gates_json TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keyword_combination_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL
        REFERENCES keyword_combination_snapshots(id) ON DELETE CASCADE,
    phrase TEXT NOT NULL,
    candidate_stage TEXT NOT NULL
        CHECK(candidate_stage IN ('sample', 'stable')),
    product_count INTEGER NOT NULL,
    root_count INTEGER NOT NULL,
    shop_count INTEGER NOT NULL,
    context_count INTEGER NOT NULL,
    support_json TEXT NOT NULL,
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK(review_status IN ('pending_review', 'approved', 'rejected', 'deprecated')),
    source_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(snapshot_id, phrase)
);

CREATE INDEX IF NOT EXISTS idx_keyword_combination_candidates_review
ON keyword_combination_candidates(review_status, candidate_stage);

CREATE TABLE IF NOT EXISTS keyword_queue_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_hash TEXT NOT NULL UNIQUE,
    dataset_fingerprint TEXT NOT NULL,
    approval_fingerprint TEXT NOT NULL,
    selected_keywords_json TEXT NOT NULL,
    inserted_count INTEGER NOT NULL,
    executed_at TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_at TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    phase TEXT NOT NULL,
    event TEXT NOT NULL,
    task_id INTEGER REFERENCES search_tasks(id),
    product_id INTEGER REFERENCES products(id),
    observation_id INTEGER REFERENCES observations(id),
    message TEXT,
    data_json TEXT NOT NULL DEFAULT '{}'
);
"""

ACTIVE_TASK_UNIQUE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_search_tasks_active_keyword
ON search_tasks(keyword)
WHERE status IN ('pending', 'running', 'paused', 'needs_manual_detail', 'risk_stopped');
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _add_seconds(timestamp: str, seconds: int) -> str:
    return (
        datetime.fromisoformat(timestamp)
        + timedelta(seconds=max(0, int(seconds)))
    ).isoformat(timespec="seconds")


def _migrate_search_tasks_active_uniqueness(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='search_tasks'"
    ).fetchone()
    if row is None or row["sql"] is None:
        return
    normalized = "".join(row["sql"].lower().split())
    if "unique(keyword,status)" not in normalized:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            CREATE TABLE search_tasks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                priority INTEGER NOT NULL DEFAULT 50,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                next_run_at TEXT,
                run_owner TEXT,
                run_lease_expires_at TEXT,
                last_started_at TEXT,
                last_finished_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO search_tasks_new(
                id, keyword, source, priority, status, attempts,
                last_error, created_at, updated_at
            )
            SELECT id, keyword, source, priority, status, attempts,
                   last_error, created_at, updated_at
            FROM search_tasks
            """
        )
        conn.execute("DROP TABLE search_tasks")
        conn.execute("ALTER TABLE search_tasks_new RENAME TO search_tasks")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


@contextmanager
def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.executescript(SCHEMA)
    _migrate_search_tasks_active_uniqueness(conn)
    conn.execute(ACTIVE_TASK_UNIQUE_INDEX_SQL)
    task_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(search_tasks)")
    }
    task_column_defs = {
        "max_attempts": "INTEGER NOT NULL DEFAULT 3",
        "next_run_at": "TEXT",
        "run_owner": "TEXT",
        "run_lease_expires_at": "TEXT",
        "last_started_at": "TEXT",
        "last_finished_at": "TEXT",
    }
    for name, definition in task_column_defs.items():
        if name not in task_columns:
            conn.execute(f"ALTER TABLE search_tasks ADD COLUMN {name} {definition}")
    product_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(products)")
    }
    if "direct_url" not in product_columns:
        conn.execute("ALTER TABLE products ADD COLUMN direct_url TEXT")
    observation_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(observations)")
    }
    observation_column_defs = {
        "cumulative_sales_display": "TEXT",
        "cumulative_sales_exact": "INTEGER",
        "daily_sales_delta": "INTEGER",
        "sales_7d_min": "INTEGER",
        "sales_30d_min": "INTEGER",
        "interested_7d_min": "INTEGER",
        "interested_30d_min": "INTEGER",
        "favorites_30d_min": "INTEGER",
    }
    for name, definition in observation_column_defs.items():
        if name not in observation_columns:
            conn.execute(f"ALTER TABLE observations ADD COLUMN {name} {definition}")
    for table in ("task_results", "search_result_evidence"):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "valid" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN valid INTEGER NOT NULL DEFAULT 1")
        if "invalid_reason" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN invalid_reason TEXT")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def enqueue(conn: sqlite3.Connection, keywords: Iterable[str], source: str = "manual") -> int:
    now = utcnow()
    inserted = 0
    for keyword in keywords:
        keyword = keyword.strip()
        if not keyword:
            continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO search_tasks(keyword, source, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (keyword, source, now, now),
        )
        inserted += cur.rowcount
    return inserted


def set_product_sales_follow(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    enabled: bool,
    actor: str = "workbench",
) -> dict:
    product = conn.execute(
        "SELECT id, title, share_url, direct_url FROM products WHERE id=?",
        (product_id,),
    ).fetchone()
    if product is None:
        raise KeyError(product_id)
    from .product_link import is_supported_product_direct_url

    if enabled and not is_supported_product_direct_url(product["direct_url"]):
        raise ValueError("product_direct_url_missing")

    if enabled:
        conn.execute(
            """
            INSERT INTO product_sales_follows(product_id, followed_at, followed_by)
            VALUES (?, ?, ?)
            ON CONFLICT(product_id) DO NOTHING
            """,
            (product_id, utcnow(), actor),
        )
    else:
        conn.execute(
            "DELETE FROM product_sales_follows WHERE product_id=?",
            (product_id,),
        )

    row = conn.execute(
        """
        SELECT p.id AS product_id, p.title, p.share_url, p.direct_url,
               f.followed_at, f.followed_by
        FROM products p
        LEFT JOIN product_sales_follows f ON f.product_id=p.id
        WHERE p.id=?
        """,
        (product_id,),
    ).fetchone()
    return {
        **dict(row),
        "sales_followed": row["followed_at"] is not None,
    }


def followed_product_sales_snapshot(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.id AS product_id, p.title, p.shop_name, p.share_url,
                   p.direct_url, p.direct_url AS verified_direct_url,
                   f.followed_at, f.followed_by
            FROM product_sales_follows f
            JOIN products p ON p.id=f.product_id
            ORDER BY f.followed_at, p.id
            """
        )
    ]


def latest_daily_sales_result(
    conn: sqlite3.Connection,
    *,
    product_id: int,
) -> dict | None:
    exists = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='daily_sales_plans'
        """
    ).fetchone()
    if exists is None:
        return None
    row = conn.execute(
        """
        SELECT cycle_date, status, observed_at, cumulative_sales_display,
               cumulative_sales_exact, daily_sales_delta
        FROM daily_sales_plans
        WHERE product_id=?
          AND status IN ('completed_exact', 'completed_fuzzy')
        ORDER BY cycle_date DESC, id DESC
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def dashboard_stats(conn: sqlite3.Connection) -> dict:
    result = {}
    for name, sql in {
        "pending_tasks": "SELECT COUNT(*) FROM search_tasks WHERE status='pending'",
        "products": "SELECT COUNT(*) FROM products",
        "observations": "SELECT COUNT(*) FROM observations",
        "note_observations": "SELECT COUNT(*) FROM note_observations",
        "followed_products": "SELECT COUNT(*) FROM product_sales_follows",
        "candidates": """
            SELECT COUNT(*) FROM candidate_assessments a
            WHERE a.status='candidate'
              AND a.id=(SELECT id FROM candidate_assessments
                        WHERE product_id=a.product_id ORDER BY id DESC LIMIT 1)
        """,
    }.items():
        result[name] = conn.execute(sql).fetchone()[0]
    result["recent"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT o.id AS observation_id, p.id AS product_id,
                   p.title, p.shop_name, p.price, p.share_url, p.direct_url,
                   o.observed_at,
                   o.cumulative_sales_display, o.cumulative_sales_exact,
                   o.cumulative_sales_min, o.daily_sales_delta, o.sales_24h_min,
                   o.sales_7d_min, o.sales_30d_min,
                   o.cart_24h_min, o.new_30d_min,
                   o.positive_reviews_30d_min, o.favorites_30d_min,
                   o.interested_7d_min, o.interested_30d_min,
                   o.viewers_now, o.sales_surging, o.screenshot_path,
                   o.raw_signals_json,
                   EXISTS(
                       SELECT 1 FROM product_sales_follows pf
                       WHERE pf.product_id=p.id
                   ) AS sales_followed,
                   a.evidence_grade, a.score, a.low_follower_verified,
                   a.reasons_json, a.status AS assessment_status,
                   se.source_keyword AS search_source_keyword,
                   se.result_rank AS search_result_rank,
                   se.search_probe_dir AS search_probe_dir,
                   se.search_screenshot_path AS search_screenshot_path,
                   (SELECT COUNT(*) FROM note_observations no
                    WHERE no.product_id=p.id) AS note_observation_count,
                   (SELECT author_name FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS note_author_name,
                   (SELECT likes FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS note_likes,
                   (SELECT published_days_ago FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS note_published_days_ago,
                   (SELECT follower_count FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                    ORDER BY no.id DESC LIMIT 1) AS note_author_follower_count,
                   (SELECT follower_count FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='seller_profile_from_product'
                    ORDER BY no.id DESC LIMIT 1) AS seller_follower_count,
                   (SELECT CASE
                        WHEN no.follower_count IS NOT NULL THEN 'visible'
                        WHEN json_valid(no.raw_json)
                             AND json_extract(no.raw_json, '$.follower_display_status')='not_displayed'
                            THEN 'not_displayed'
                        ELSE 'missing'
                    END
                    FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='seller_profile_from_product'
                    ORDER BY no.id DESC LIMIT 1) AS seller_follower_display_status,
                   (SELECT CASE
                        WHEN no.follower_count IS NOT NULL THEN no.id
                        WHEN json_valid(no.raw_json)
                             AND json_extract(no.raw_json, '$.follower_display_status')='not_displayed'
                            THEN no.id
                        ELSE NULL
                    END
                    FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='seller_profile_from_product'
                    ORDER BY no.id DESC LIMIT 1) AS seller_profile_evidence_id,
                   EXISTS(
                       SELECT 1 FROM task_results tr
                       WHERE tr.product_id=p.id
                         AND tr.observation_id=o.id
                         AND tr.valid=1
                   ) AS task_result_valid
            FROM products p
            JOIN observations o
              ON o.id=(SELECT id FROM observations latest
                       WHERE latest.product_id=p.id
                       ORDER BY latest.id DESC LIMIT 1)
            LEFT JOIN candidate_assessments a
              ON a.id=(SELECT id FROM candidate_assessments
                       WHERE product_id=o.product_id ORDER BY id DESC LIMIT 1)
            LEFT JOIN search_result_evidence se
              ON se.id=(SELECT id FROM search_result_evidence
                        WHERE observation_id=o.id AND valid=1 ORDER BY id DESC LIMIT 1)
            ORDER BY o.id DESC
            """
        )
    ]
    for row in result["recent"]:
        daily_sales = latest_daily_sales_result(
            conn,
            product_id=int(row["product_id"]),
        )
        if daily_sales is not None:
            if daily_sales.get("cumulative_sales_display"):
                row["cumulative_sales_display"] = daily_sales[
                    "cumulative_sales_display"
                ]
            if daily_sales.get("cumulative_sales_exact") is not None:
                row["cumulative_sales_exact"] = daily_sales[
                    "cumulative_sales_exact"
                ]
                row["cumulative_sales_min"] = daily_sales[
                    "cumulative_sales_exact"
                ]
            if daily_sales.get("daily_sales_delta") is not None:
                row["daily_sales_delta"] = daily_sales["daily_sales_delta"]
        raw_signals = row.pop("raw_signals_json", None)
        items = gray_metric_items(raw_signals)
        row["gray_metric_count"] = len(items)
        row["gray_metric_items"] = list(items)
        row["task_result_valid"] = bool(row.get("task_result_valid"))
        row["hot_metrics_qualified"] = len(items) >= 3
        follower_count = row.get("seller_follower_count")
        follower_display_status = (
            row.get("seller_follower_display_status") or "missing"
        )
        row["seller_follower_display_status"] = follower_display_status
        row["low_follower_qualified"] = (
            follower_display_status == "visible"
            and follower_count is not None
            and 1 <= int(follower_count) <= 2_000
        )
        row["candidate_qualified"] = bool(
            row["task_result_valid"]
            and row["hot_metrics_qualified"]
            and row["low_follower_qualified"]
        )
        seller_evidence_present = row.get("seller_profile_evidence_id") is not None
        row["collection_status"] = (
            "complete"
            if row["task_result_valid"] and seller_evidence_present
            else "partial"
        )
        qualification_reasons: list[str] = []
        if not row["task_result_valid"]:
            qualification_reasons.append("最新观察缺少有效任务结果")
        if not row["hot_metrics_qualified"]:
            qualification_reasons.append(
                f"热门指标不足：已识别{len(items)}条，需至少3条"
            )
        if follower_display_status == "not_displayed":
            qualification_reasons.append("店铺页面未显示粉丝数，按非低粉处理")
        elif follower_count is None:
            qualification_reasons.append("缺少商品店铺粉丝证据")
        elif not row["low_follower_qualified"]:
            qualification_reasons.append(
                f"店铺粉丝{int(follower_count)}不在1至2000范围"
            )
        if not qualification_reasons:
            qualification_reasons.append("有效任务、热门指标和低粉店铺均已通过")
        row["qualification_reasons"] = qualification_reasons
        if not row.get("cumulative_sales_display"):
            try:
                raw = json.loads(raw_signals or "{}")
            except json.JSONDecodeError:
                raw = {}
            display = (raw.get("signals") or {}).get("cumulative_sales_display")
            row["cumulative_sales_display"] = display or (
                str(row["cumulative_sales_min"])
                if row.get("cumulative_sales_min") is not None
                else None
            )
    result["gray_qualified_candidates"] = sum(
        row["gray_metric_count"] >= 3 for row in result["recent"]
    )
    result["qualified_candidates"] = sum(
        row["candidate_qualified"] for row in result["recent"]
    )
    return result


def record_run_event(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    phase: str,
    event: str,
    level: str = "info",
    task_id: int | None = None,
    product_id: int | None = None,
    observation_id: int | None = None,
    message: str | None = None,
    data: dict | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO run_events(
            run_id, event_at, level, phase, event, task_id, product_id,
            observation_id, message, data_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            utcnow(),
            level,
            phase,
            event,
            task_id,
            product_id,
            observation_id,
            message,
            json.dumps(data or {}, ensure_ascii=False),
        ),
    )
    return int(cur.lastrowid)


class _InfrastructureDispositionBlocked(RuntimeError):
    def __init__(self, reason_code: str, **details):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.details = details


def record_infrastructure_hard_stop(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    owner: str | None,
    reason: str,
    phase: str,
    reason_code: str,
    event_name: str,
    failure_label: str,
    task_id: int | None = None,
    restore_status: str = "pending",
    refund_all_owned_tasks: bool = False,
    evidence: dict | None = None,
    cleanup_note_observation_ids: Iterable[int] | None = None,
    require_active_monitor_lease: bool = False,
) -> dict:
    """原子暂停监控并返还一次基础设施故障消耗的任务尝试。

    被返还的任务必须仍由 ``owner`` 持有。监控严格模式还要求有效的
    ``monitor_once`` 租约和任务租约。任务更新、全局硬停止和审计事件共享
    同一个savepoint，不能只完成其中一部分。
    """

    allowed_restore_statuses = {"pending", "paused", "needs_manual_detail"}
    if restore_status not in allowed_restore_statuses:
        raise ValueError(
            f"unsupported {failure_label} restore status: {restore_status}"
        )
    if task_id is not None and not owner:
        raise ValueError(
            f"owner is required when refunding a {failure_label} task"
        )

    savepoint = "infrastructure_hard_stop"
    now = utcnow()
    cleanup_ids = sorted(
        {int(value) for value in (cleanup_note_observation_ids or [])}
    )
    refunded_tasks: list[dict] = []
    removed_note_observations: list[dict] = []
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        if require_active_monitor_lease:
            if not owner:
                raise _InfrastructureDispositionBlocked("monitor_owner_required")
            monitor_cur = conn.execute(
                """
                UPDATE run_leases
                SET heartbeat_at=heartbeat_at
                WHERE name='monitor_once' AND owner=?
                  AND expires_at IS NOT NULL
                  AND julianday(expires_at) > julianday(?)
                """,
                (owner, now),
            )
            if monitor_cur.rowcount != 1:
                monitor_row = conn.execute(
                    """
                    SELECT owner, expires_at,
                           CASE
                               WHEN expires_at IS NOT NULL
                                AND julianday(expires_at) > julianday(?)
                               THEN 1 ELSE 0
                           END AS lease_active
                    FROM run_leases
                    WHERE name='monitor_once'
                    """,
                    (now,),
                ).fetchone()
                monitor_snapshot = dict(monitor_row) if monitor_row else None
                if monitor_row is None:
                    failure_reason = "monitor_lease_missing"
                elif monitor_row["owner"] != owner:
                    failure_reason = "monitor_owner_mismatch"
                elif not bool(monitor_row["lease_active"]):
                    failure_reason = "monitor_lease_expired"
                else:
                    failure_reason = "monitor_lease_changed"
                raise _InfrastructureDispositionBlocked(
                    failure_reason,
                    monitor_lease=monitor_snapshot,
                )

        rows: list[sqlite3.Row] = []
        if owner:
            params: list[object] = [owner]
            task_filter = ""
            if task_id is not None and not refund_all_owned_tasks:
                task_filter = " AND id=?"
                params.append(task_id)
            rows = conn.execute(
                f"""
                SELECT id, keyword, attempts, status, run_owner,
                       run_lease_expires_at,
                       CASE
                           WHEN run_lease_expires_at IS NOT NULL
                            AND julianday(run_lease_expires_at) > julianday(?)
                           THEN 1 ELSE 0
                       END AS lease_active
                FROM search_tasks
                WHERE status='running' AND run_owner=?{task_filter}
                ORDER BY id
                """,
                (now, *params),
            ).fetchall()

        if task_id is not None and not any(
            int(row["id"]) == int(task_id) for row in rows
        ):
            if require_active_monitor_lease:
                task_row = conn.execute(
                    """
                    SELECT id, status, run_owner, run_lease_expires_at,
                           CASE
                               WHEN run_lease_expires_at IS NOT NULL
                                AND julianday(run_lease_expires_at) > julianday(?)
                               THEN 1 ELSE 0
                           END AS lease_active
                    FROM search_tasks
                    WHERE id=?
                    """,
                    (now, task_id),
                ).fetchone()
                task_snapshot = dict(task_row) if task_row else None
                if task_row is None:
                    failure_reason = "task_missing"
                elif task_row["status"] != "running":
                    failure_reason = "task_not_running"
                elif task_row["run_owner"] != owner:
                    failure_reason = "task_owner_mismatch"
                elif not bool(task_row["lease_active"]):
                    failure_reason = "task_lease_expired"
                else:
                    failure_reason = "task_lease_changed"
                raise _InfrastructureDispositionBlocked(
                    failure_reason,
                    task=task_snapshot,
                )
            raise RuntimeError(
                f"{failure_label} task {task_id} is no longer owned by {owner}"
            )

        for row in rows:
            if require_active_monitor_lease and not bool(row["lease_active"]):
                raise _InfrastructureDispositionBlocked(
                    "task_lease_expired",
                    task={
                        "id": int(row["id"]),
                        "status": row["status"],
                        "run_owner": row["run_owner"],
                        "run_lease_expires_at": row["run_lease_expires_at"],
                    },
                )
            attempts_before = int(row["attempts"] or 0)
            if attempts_before <= 0:
                if require_active_monitor_lease:
                    raise _InfrastructureDispositionBlocked(
                        "task_attempt_unavailable",
                        task={
                            "id": int(row["id"]),
                            "attempts": attempts_before,
                        },
                    )
                raise RuntimeError(
                    f"{failure_label} task {row['id']} has no attempt to return"
                )

        for observation_id in cleanup_ids:
            note_row = conn.execute(
                """
                SELECT id, product_id, source, page_kind, raw_text
                FROM note_observations
                WHERE id=?
                """,
                (observation_id,),
            ).fetchone()
            if note_row is None:
                continue
            if (
                note_row["source"]
                not in {"related_note_card", "author_profile_from_note"}
                or note_row["page_kind"] != "ocr_timeout"
                or str(note_row["raw_text"] or "").strip()
            ):
                raise RuntimeError(
                    "refusing to remove a non-timeout note observation: "
                    f"{observation_id}"
                )
            conn.execute(
                "DELETE FROM note_observations WHERE id=?",
                (observation_id,),
            )
            removed_note_observations.append(
                {
                    "id": int(note_row["id"]),
                    "product_id": note_row["product_id"],
                    "source": note_row["source"],
                }
            )

        for row in rows:
            attempts_before = int(row["attempts"] or 0)
            attempts_after = attempts_before - 1
            update_sql = """
                UPDATE search_tasks
                SET status=?, attempts=?, next_run_at=NULL,
                    run_owner=NULL, run_lease_expires_at=NULL,
                    last_finished_at=?, last_error=?, updated_at=?
                WHERE id=? AND status='running' AND run_owner=? AND attempts=?
            """
            update_params: list[object] = [
                restore_status,
                attempts_after,
                now,
                reason,
                now,
                row["id"],
                owner,
                attempts_before,
            ]
            if require_active_monitor_lease:
                update_sql += """
                  AND run_lease_expires_at IS NOT NULL
                  AND julianday(run_lease_expires_at) > julianday(?)
                  AND EXISTS (
                      SELECT 1 FROM run_leases
                      WHERE name='monitor_once' AND owner=?
                        AND expires_at IS NOT NULL
                        AND julianday(expires_at) > julianday(?)
                  )
                """
                update_params.extend((now, owner, now))
            cur = conn.execute(update_sql, tuple(update_params))
            if cur.rowcount != 1:
                if require_active_monitor_lease:
                    raise _InfrastructureDispositionBlocked(
                        "lease_changed_during_attempt_return",
                        task={"id": int(row["id"])},
                    )
                raise RuntimeError(
                    f"{failure_label} task {row['id']} changed during attempt return"
                )
            refunded_tasks.append(
                {
                    "task_id": int(row["id"]),
                    "keyword": row["keyword"],
                    "attempts_before": attempts_before,
                    "attempts_after": attempts_after,
                    "status": restore_status,
                }
            )

        set_monitor_desired_state(conn, "paused")
        set_monitor_state(conn, "risk_stop_reason", reason)
        set_monitor_state(conn, "last_block_reason", reason)
        payload = {
            "reason_code": reason_code,
            "infrastructure_failure": True,
            "requires_explicit_resume": True,
            "phase": phase,
            "refunded_tasks": refunded_tasks,
            "attempt_returned": bool(refunded_tasks),
            "disposition_attempted": True,
            "removed_ocr_timeout_note_observations": removed_note_observations,
            "evidence": evidence or {},
        }
        record_run_event(
            conn,
            run_id=run_id,
            phase=phase,
            event=event_name,
            level="error",
            task_id=task_id,
            message=reason,
            data=payload,
        )
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except _InfrastructureDispositionBlocked as exc:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        blocked_savepoint = "ocr_timeout_disposition_blocked"
        conn.execute(f"SAVEPOINT {blocked_savepoint}")
        try:
            set_monitor_desired_state(conn, "paused")
            set_monitor_state(conn, "risk_stop_reason", reason)
            set_monitor_state(conn, "last_block_reason", reason)
            lease_safety_blocked = {
                "reason": exc.reason_code,
                "owner": owner,
                "task_id": task_id,
                "checked_at": now,
                **exc.details,
            }
            payload = {
                "reason_code": reason_code,
                "infrastructure_failure": True,
                "requires_explicit_resume": True,
                "phase": phase,
                "refunded_tasks": [],
                "attempt_returned": False,
                "disposition_attempted": True,
                "removed_ocr_timeout_note_observations": [],
                "lease_safety_blocked": lease_safety_blocked,
                "evidence": evidence or {},
            }
            record_run_event(
                conn,
                run_id=run_id,
                phase=phase,
                event=event_name,
                level="error",
                task_id=task_id,
                message=reason,
                data=payload,
            )
            conn.execute(f"RELEASE SAVEPOINT {blocked_savepoint}")
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {blocked_savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {blocked_savepoint}")
            raise
        return {
            "hard_stop": True,
            "reason_code": reason_code,
            "infrastructure_failure": True,
            "requires_explicit_resume": True,
            "reason": reason,
            "phase": phase,
            "refunded_tasks": [],
            "attempt_returned": False,
            "disposition_attempted": True,
            "removed_ocr_timeout_note_observations": [],
            "lease_safety_blocked": lease_safety_blocked,
            "evidence": evidence or {},
        }
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise

    return {
        "hard_stop": True,
        "reason_code": reason_code,
        "infrastructure_failure": True,
        "requires_explicit_resume": True,
        "reason": reason,
        "phase": phase,
        "refunded_tasks": refunded_tasks,
        "attempt_returned": bool(refunded_tasks),
        "disposition_attempted": True,
        "removed_ocr_timeout_note_observations": removed_note_observations,
        "evidence": evidence or {},
    }


def record_ocr_timeout_hard_stop(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    owner: str | None,
    reason: str,
    phase: str,
    task_id: int | None = None,
    restore_status: str = "pending",
    refund_all_owned_tasks: bool = False,
    evidence: dict | None = None,
    cleanup_note_observation_ids: Iterable[int] | None = None,
    require_active_monitor_lease: bool = False,
) -> dict:
    """保持既有OCR接口，同时使用通用基础设施故障事务。"""

    return record_infrastructure_hard_stop(
        conn,
        run_id=run_id,
        owner=owner,
        reason=reason,
        phase=phase,
        reason_code="ocr_timeout",
        event_name="ocr_timeout_hard_stop",
        failure_label="OCR-timeout",
        task_id=task_id,
        restore_status=restore_status,
        refund_all_owned_tasks=refund_all_owned_tasks,
        evidence=evidence,
        cleanup_note_observation_ids=cleanup_note_observation_ids,
        require_active_monitor_lease=require_active_monitor_lease,
    )


def recent_run_events(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, run_id, event_at, level, phase, event, task_id,
                   product_id, observation_id, message, data_json
            FROM run_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
    ]


def acquire_run_lease(
    conn: sqlite3.Connection,
    *,
    name: str,
    owner: str,
    ttl_seconds: int,
    now: str | None = None,
    metadata: dict | None = None,
) -> dict:
    now = now or utcnow()
    expires_at = _add_seconds(now, ttl_seconds)
    cur = conn.execute(
        """
        INSERT INTO run_leases(name, owner, acquired_at, heartbeat_at, expires_at, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            owner=excluded.owner,
            acquired_at=CASE
                WHEN run_leases.owner=excluded.owner THEN run_leases.acquired_at
                ELSE excluded.acquired_at
            END,
            heartbeat_at=excluded.heartbeat_at,
            expires_at=excluded.expires_at,
            metadata_json=excluded.metadata_json
        WHERE run_leases.owner=excluded.owner
           OR julianday(run_leases.expires_at) <= julianday(excluded.heartbeat_at)
        """,
        (
            name,
            owner,
            now,
            now,
            expires_at,
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    row = conn.execute("SELECT * FROM run_leases WHERE name=?", (name,)).fetchone()
    lease = dict(row) if row else None
    return {
        "acquired": bool(cur.rowcount and lease and lease["owner"] == owner),
        "lease": lease,
    }


def heartbeat_run_lease(
    conn: sqlite3.Connection,
    *,
    name: str,
    owner: str,
    ttl_seconds: int,
    now: str | None = None,
) -> bool:
    now = now or utcnow()
    expires_at = _add_seconds(now, ttl_seconds)
    cur = conn.execute(
        """
        UPDATE run_leases
        SET heartbeat_at=?, expires_at=?
        WHERE name=? AND owner=?
        """,
        (now, expires_at, name, owner),
    )
    return bool(cur.rowcount)


def release_run_lease(conn: sqlite3.Connection, *, name: str, owner: str) -> bool:
    cur = conn.execute(
        "DELETE FROM run_leases WHERE name=? AND owner=?",
        (name, owner),
    )
    return bool(cur.rowcount)


def get_run_lease(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM run_leases WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None


def purge_expired_run_leases(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    now = now or utcnow()
    cur = conn.execute(
        "DELETE FROM run_leases WHERE julianday(expires_at) <= julianday(?)",
        (now,),
    )
    return int(cur.rowcount)


def record_note_observation(
    conn: sqlite3.Connection,
    *,
    product_id: int | None,
    source: str,
    screenshot_path: str | None,
    probe_dir: str | None,
    page_kind: str | None,
    raw_text: str | None,
    author_name: str | None = None,
    follower_count: int | None = None,
    likes: int | None = None,
    collects: int | None = None,
    comments: int | None = None,
    published_days_ago: int | None = None,
    raw: dict | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO note_observations(
            product_id, captured_at, source, screenshot_path, probe_dir, page_kind,
            raw_text, author_name, follower_count, likes, collects, comments,
            published_days_ago, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            utcnow(),
            source,
            screenshot_path,
            probe_dir,
            page_kind,
            raw_text,
            author_name,
            follower_count,
            likes,
            collects,
            comments,
            published_days_ago,
            json.dumps(raw or {}, ensure_ascii=False),
        ),
    )
    return int(cur.lastrowid)


def set_monitor_state(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        """
        INSERT INTO monitor_state(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=False), utcnow()),
    )


def get_monitor_state(conn: sqlite3.Connection) -> dict:
    state = {
        "desired_state": "paused",
        "risk_stop_reason": None,
        "last_block_reason": None,
        "last_skip_reason": None,
        "last_run_id": None,
        "last_heartbeat": None,
        "last_report_path": None,
        "scheduler_running": False,
        "next_run_at": None,
        "last_scheduler_output": None,
    }
    for row in conn.execute("SELECT key, value FROM monitor_state"):
        try:
            state[row["key"]] = json.loads(row["value"])
        except json.JSONDecodeError:
            state[row["key"]] = row["value"]
    return state


def set_monitor_desired_state(conn: sqlite3.Connection, desired_state: str) -> None:
    if desired_state not in {"running", "paused"}:
        raise ValueError(f"Unsupported monitor state: {desired_state}")
    if desired_state == "running":
        risk_reason = get_monitor_state(conn).get("risk_stop_reason")
        if risk_reason:
            raise RiskStopActiveError(
                f"风险停止仍生效，普通恢复已拒绝：{risk_reason}"
            )
    set_monitor_state(conn, "desired_state", desired_state)


def resume_monitor_after_risk(
    conn: sqlite3.Connection,
    *,
    confirm_risk_reason: str,
    actor: str,
) -> dict:
    state = get_monitor_state(conn)
    current_reason = state.get("risk_stop_reason")
    if not current_reason:
        raise RiskConfirmationError("当前没有需要解除的风险停止")
    if not confirm_risk_reason or confirm_risk_reason != current_reason:
        raise RiskConfirmationError("提交的风险原因与当前风险停止原因不一致")

    set_monitor_state(conn, "risk_stop_reason", None)
    set_monitor_state(conn, "desired_state", "running")
    record_run_event(
        conn,
        run_id=f"risk-resume:{utcnow()}",
        phase="monitor_control",
        event="risk_stop_cleared",
        level="warning",
        message="操作者显式确认当前风险原因后解除硬风控并恢复监控",
        data={
            "actor": actor,
            "confirmed_risk_reason": current_reason,
        },
    )
    return get_monitor_state(conn)


def record_search_result_evidence(
    conn: sqlite3.Connection,
    *,
    source_keyword: str,
    task_id: int | None = None,
    product_id: int | None = None,
    observation_id: int | None = None,
    result_rank: int | None = None,
    page_kind: str | None = None,
    search_probe_dir: str | None = None,
    search_screenshot_path: str | None = None,
    text_excerpt: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO search_result_evidence(
            task_id, product_id, observation_id, source_keyword, result_rank,
            page_kind, search_probe_dir, search_screenshot_path, text_excerpt,
            recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id, observation_id, result_rank) DO UPDATE SET
            product_id=COALESCE(excluded.product_id, search_result_evidence.product_id),
            source_keyword=excluded.source_keyword,
            page_kind=COALESCE(excluded.page_kind, search_result_evidence.page_kind),
            search_probe_dir=COALESCE(excluded.search_probe_dir, search_result_evidence.search_probe_dir),
            search_screenshot_path=COALESCE(excluded.search_screenshot_path, search_result_evidence.search_screenshot_path),
            text_excerpt=COALESCE(excluded.text_excerpt, search_result_evidence.text_excerpt),
            recorded_at=excluded.recorded_at
        """,
        (
            task_id,
            product_id,
            observation_id,
            source_keyword,
            result_rank,
            page_kind,
            search_probe_dir,
            search_screenshot_path,
            text_excerpt,
            utcnow(),
        ),
    )
    if cur.lastrowid:
        return int(cur.lastrowid)
    row = conn.execute(
        """
        SELECT id FROM search_result_evidence
        WHERE task_id IS ? AND observation_id IS ? AND result_rank IS ?
        ORDER BY id DESC LIMIT 1
        """,
        (task_id, observation_id, result_rank),
    ).fetchone()
    return int(row["id"]) if row else 0
