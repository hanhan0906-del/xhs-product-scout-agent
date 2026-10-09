from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .db import enqueue, get_monitor_state, set_monitor_state, utcnow
from .digest import (
    MonitoringDigest,
    build_daily_digest,
    build_weekly_digest,
)
from .keyword_portfolio import build_rotation_plan, normalize_keyword
from .quality import audit_evidence_records


def quality_snapshot(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    issue_limit: int = 20,
) -> dict[str, Any]:
    products = _rows(
        conn,
        """
        SELECT p.*,
               a.evidence_grade, a.score, a.low_follower_verified, a.status
        FROM products p
        LEFT JOIN candidate_assessments a
          ON a.id=(SELECT id FROM candidate_assessments
                   WHERE product_id=p.id ORDER BY id DESC LIMIT 1)
        ORDER BY p.id DESC
        LIMIT 200
        """,
    )
    observations = _rows(
        conn,
        """
        SELECT o.*, a.evidence_grade, a.score, a.low_follower_verified,
               a.status
        FROM observations o
        LEFT JOIN candidate_assessments a
          ON a.id=(SELECT id FROM candidate_assessments
                   WHERE product_id=o.product_id ORDER BY id DESC LIMIT 1)
        ORDER BY o.id DESC
        LIMIT 500
        """,
    )
    notes = _rows(
        conn,
        "SELECT * FROM note_observations ORDER BY id DESC LIMIT 500",
    )
    search_evidence = _rows(
        conn,
        "SELECT * FROM search_result_evidence ORDER BY id DESC LIMIT 500",
    )
    keywords = [
        row["keyword"]
        for row in conn.execute("SELECT DISTINCT keyword FROM search_tasks")
    ]
    for row in products:
        row["screenshot_exists"] = True
    for row in observations:
        row["screenshot_exists"] = _path_exists(
            row.get("screenshot_path"),
            settings.data_dir,
        )
    for row in notes:
        row["screenshot_exists"] = _path_exists(
            row.get("screenshot_path"),
            settings.data_dir,
        )
    for row in search_evidence:
        row["search_screenshot_exists"] = _path_exists(
            row.get("search_screenshot_path"),
            settings.data_dir,
        )

    report = audit_evidence_records(
        products=products,
        observations=observations,
        notes=notes,
        search_evidence=search_evidence,
        allowed_keywords=keywords,
        now=utcnow(),
    ).as_dict()
    report["issues"] = report["issues"][: max(0, issue_limit)]
    report["scope"] = {
        "products": len(products),
        "observations": len(observations),
        "notes": len(notes),
        "search_evidence": len(search_evidence),
    }
    report["audited_at"] = utcnow()
    return report


def digest_snapshot(
    conn: sqlite3.Connection,
    *,
    period: str = "daily",
) -> dict[str, Any]:
    observations = _rows(
        conn,
        """
        SELECT o.*, p.title,
               se.source_keyword AS search_source_keyword
        FROM observations o
        LEFT JOIN products p ON p.id=o.product_id
        LEFT JOIN search_result_evidence se
          ON se.id=(SELECT id FROM search_result_evidence
                    WHERE observation_id=o.id AND valid=1
                    ORDER BY id DESC LIMIT 1)
        ORDER BY o.id DESC
        LIMIT 500
        """,
    )
    candidates = _rows(
        conn,
        """
        SELECT p.id AS product_id, p.title, a.assessed_at,
               a.evidence_grade, a.score, a.low_follower_verified,
               se.source_keyword AS search_source_keyword,
               se.result_rank AS search_result_rank,
               (SELECT author_name FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_author_name,
               (SELECT likes FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_likes,
               (SELECT collects FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_collects,
               (SELECT comments FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_comments,
               (SELECT published_days_ago FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_published_days_ago,
               (SELECT author_name FROM note_observations no
                WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                ORDER BY no.id DESC LIMIT 1) AS profile_author_name,
               (SELECT follower_count FROM note_observations no
                WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                ORDER BY no.id DESC LIMIT 1) AS profile_follower_count,
               (SELECT probe_dir FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_evidence_path,
               (SELECT probe_dir FROM note_observations no
                WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                ORDER BY no.id DESC LIMIT 1) AS profile_evidence_path
        FROM candidate_assessments a
        JOIN products p ON p.id=a.product_id
        LEFT JOIN search_result_evidence se
          ON se.id=(SELECT id FROM search_result_evidence
                    WHERE product_id=p.id AND valid=1 ORDER BY id DESC LIMIT 1)
        WHERE a.status='candidate'
          AND a.id=(SELECT id FROM candidate_assessments
                    WHERE product_id=a.product_id ORDER BY id DESC LIMIT 1)
        ORDER BY a.id DESC
        """,
    )
    tasks = _rows(
        conn,
        """
        SELECT id, keyword, status, attempts, max_attempts, updated_at,
               last_finished_at, last_error
        FROM search_tasks ORDER BY id DESC LIMIT 500
        """,
    )
    builder = build_weekly_digest if period == "weekly" else build_daily_digest
    digest = builder(
        observations=observations,
        candidates=candidates,
        tasks=tasks,
        monitor=get_monitor_state(conn),
        generated_at=utcnow(),
        timezone_label="Asia/Shanghai",
    )
    return _digest_to_dict(digest)


def portfolio_snapshot(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    per_round_budget: int = 1,
) -> dict[str, Any]:
    config = _portfolio_config(settings)
    policy = dict(config.get("policy") or {})
    policy["hourly_budget"] = max(1, int(per_round_budget))
    policy["per_round_budget"] = max(1, int(per_round_budget))
    config = {**config, "policy": policy}

    history: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        """
        SELECT keyword, last_started_at, last_finished_at, updated_at
        FROM search_tasks
        ORDER BY id DESC
        """
    ):
        key = normalize_keyword(row["keyword"])
        if key not in history:
            history[key] = {
                "last_started_at": (
                    row["last_started_at"]
                    or row["last_finished_at"]
                    or row["updated_at"]
                )
            }
    state = get_monitor_state(conn)
    return build_rotation_plan(
        config,
        now=utcnow(),
        keyword_history=history,
        hourly_used=0,
        rotation_cursor=int(state.get("portfolio_cursor") or 0),
        pause_input={
            "risk_stop_reason": state.get("risk_stop_reason"),
            "consecutive_failures": 0,
        },
    )


def ensure_portfolio_queue(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    max_keywords: int = 1,
) -> dict[str, Any]:
    runnable = conn.execute(
        """
        SELECT COUNT(*) FROM search_tasks
        WHERE status='pending'
          AND attempts < COALESCE(max_attempts, 3)
          AND (next_run_at IS NULL OR julianday(next_run_at) <= julianday(?))
        """,
        (utcnow(),),
    ).fetchone()[0]
    plan = portfolio_snapshot(
        conn,
        settings,
        per_round_budget=max(1, int(max_keywords)),
    )
    if runnable:
        result = {**plan, "queued": 0, "queue_reason": "runnable_tasks_exist"}
        set_monitor_state(conn, "last_portfolio_plan", result)
        return result

    selected = plan.get("selected") or []
    queued = 0
    for item in selected[: max(1, int(max_keywords))]:
        queued += enqueue(
            conn,
            [item["keyword"]],
            source=f"keyword_portfolio:{item['layer']}:{item['category_id']}",
        )
    set_monitor_state(
        conn,
        "portfolio_cursor",
        (plan.get("rotation") or {}).get("next_cursor", 0),
    )
    result = {
        **plan,
        "queued": queued,
        "queue_reason": "portfolio_seeded" if queued else "no_eligible_keyword",
    }
    set_monitor_state(conn, "last_portfolio_plan", result)
    return result


def _portfolio_config(settings: Settings) -> dict[str, Any]:
    path = settings.root / "config" / "keyword_portfolio.json"
    if not path.is_file():
        return {"version": 1, "policy": {}, "categories": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql)]


def _path_exists(value: Any, root: Path) -> bool:
    if not value:
        return False
    path = Path(str(value))
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    allowed_root = root.resolve()
    return allowed_root in resolved.parents and resolved.is_file()


def _digest_to_dict(digest: MonitoringDigest) -> dict[str, Any]:
    data = asdict(digest)
    return _json_ready(data)


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value
