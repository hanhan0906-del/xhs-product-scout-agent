from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Iterator, Mapping

from .ingest import calculate_daily_sales_delta
from .product_link import is_supported_product_direct_url


SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
UTC = timezone.utc
TERMINAL_STATUSES = {
    "completed_exact",
    "completed_fuzzy",
    "skipped",
    "failed",
    "risk_stopped",
}
ALL_STATUSES = {"pending", "running", *TERMINAL_STATUSES}
HARD_STOP_REASONS = {
    "captcha",
    "risk_control",
    "anr",
    "unknown_page",
    "identity_unknown",
    "database_lock_error",
}
RESULT_OUTCOMES = {"sample", "skipped", "failed", "hard_stop", "risk_stopped"}


class DailySalesBatchHardStop(RuntimeError):
    """Signals that the entire cycle must stop rather than skip one product."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")


@dataclass(frozen=True)
class FollowedProductSnapshotItem:
    product_id: int
    verified_direct_url: str


def _row(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    return dict(zip((item[0] for item in cursor.description), value))


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, value)) for value in cursor.fetchall()]


def _parse_aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_must_include_timezone")
    return parsed


def _utc_iso(value: str | datetime | None = None) -> str:
    parsed = datetime.now(UTC) if value is None else _parse_aware(value)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def _cycle_date(value: str | date) -> date:
    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, date) or isinstance(parsed, datetime):
        raise ValueError("cycle_date_must_be_date")
    return parsed


def _window(cycle: date) -> tuple[datetime, datetime]:
    start = datetime.combine(cycle, time.min, tzinfo=SHANGHAI_TZ)
    return start, start + timedelta(minutes=15)


def _in_cycle_window(observed_at: str | datetime, cycle: date) -> bool:
    local = _parse_aware(observed_at).astimezone(SHANGHAI_TZ)
    start, end = _window(cycle)
    return start <= local <= end


def _is_database_lock(error: BaseException) -> bool:
    text = str(error).lower()
    return isinstance(error, sqlite3.OperationalError) and (
        "locked" in text or "busy" in text
    )


@contextmanager
def _write_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    savepoint: str | None = None
    try:
        if conn.in_transaction:
            savepoint = f"daily_sales_{uuid.uuid4().hex}"
            conn.execute(f"SAVEPOINT {savepoint}")
        else:
            conn.execute("BEGIN IMMEDIATE")
        yield
    except Exception as error:
        if savepoint is not None:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except sqlite3.Error:
                pass
        else:
            conn.rollback()
        if _is_database_lock(error):
            raise DailySalesBatchHardStop("database_lock_error", str(error)) from error
        raise
    else:
        if savepoint is not None:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        else:
            conn.commit()


def initialize_daily_sales_tracking(conn: sqlite3.Connection) -> None:
    """Create private batch, item and audit tables without changing business tables."""
    with _write_transaction(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_sales_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_date TEXT NOT NULL UNIQUE,
                snapshot_count INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'completed', 'hard_stopped')),
                hard_stop_reason TEXT,
                hard_stop_detail TEXT,
                hard_stopped_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_sales_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                cycle_date TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                verified_direct_url TEXT NOT NULL,
                window_start_at TEXT NOT NULL,
                window_end_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN (
                        'pending', 'running', 'completed_exact', 'completed_fuzzy',
                        'skipped', 'failed', 'risk_stopped'
                    )),
                owner TEXT,
                lease_expires_at TEXT,
                claim_count INTEGER NOT NULL DEFAULT 0,
                recovery_count INTEGER NOT NULL DEFAULT 0,
                observed_at TEXT,
                cumulative_sales_display TEXT,
                cumulative_sales_exact INTEGER,
                daily_sales_delta INTEGER,
                reason_code TEXT,
                reason_detail TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(batch_id, product_id),
                UNIQUE(batch_id, sequence_no),
                FOREIGN KEY(batch_id) REFERENCES daily_sales_batches(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_daily_sales_plans_cycle_status
                ON daily_sales_plans(cycle_date, status, sequence_no)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_sales_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                plan_id INTEGER,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                owner TEXT,
                reason_code TEXT,
                event_at TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(batch_id) REFERENCES daily_sales_batches(id),
                FOREIGN KEY(plan_id) REFERENCES daily_sales_plans(id)
            )
            """
        )


def plan_midnight_cycle(
    conn: sqlite3.Connection,
    *,
    cycle_date: str | date,
    followed_products: Iterable[
        FollowedProductSnapshotItem | Mapping[str, Any]
    ],
    created_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Freeze the caller-provided manually followed products for one day."""
    cycle = _cycle_date(cycle_date)
    snapshot = [_normalize_followed_item(item) for item in followed_products]
    product_ids = [item.product_id for item in snapshot]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("duplicate_product_id_in_snapshot")

    cycle_text = cycle.isoformat()
    timestamp = _utc_iso(created_at)
    start, end = _window(cycle)
    with _write_transaction(conn):
        existing_batch = _row(
            conn.execute(
                "SELECT * FROM daily_sales_batches WHERE cycle_date=?", (cycle_text,)
            )
        )
        if existing_batch is not None:
            frozen = [
                FollowedProductSnapshotItem(row[0], row[1])
                for row in conn.execute(
                    """
                    SELECT product_id, verified_direct_url FROM daily_sales_plans
                    WHERE batch_id=? ORDER BY sequence_no
                    """,
                    (existing_batch["id"],),
                ).fetchall()
            ]
            if frozen != snapshot:
                return {
                    "created": False,
                    "code": "snapshot_frozen_mismatch",
                    "cycle_date": cycle_text,
                    "batch_id": existing_batch["id"],
                    "snapshot_count": len(frozen),
                }
            return {
                "created": False,
                "code": "already_planned",
                "cycle_date": cycle_text,
                "batch_id": existing_batch["id"],
                "snapshot_count": len(frozen),
            }

        if product_ids:
            placeholders = ",".join("?" for _ in product_ids)
            found = {
                row[0]
                for row in conn.execute(
                    f"SELECT id FROM products WHERE id IN ({placeholders})", product_ids
                ).fetchall()
            }
            missing = [product_id for product_id in product_ids if product_id not in found]
            if missing:
                return {
                    "created": False,
                    "code": "snapshot_product_not_found",
                    "cycle_date": cycle_text,
                    "missing_product_ids": missing,
                }

        conn.execute(
            """
            INSERT INTO daily_sales_batches(
                cycle_date, snapshot_count, status, created_at, updated_at
            ) VALUES (?, ?, 'active', ?, ?)
            """,
            (cycle_text, len(snapshot), timestamp, timestamp),
        )
        batch_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for sequence_no, item in enumerate(snapshot, start=1):
            conn.execute(
                """
                INSERT INTO daily_sales_plans(
                    batch_id, product_id, cycle_date, sequence_no,
                    verified_direct_url, window_start_at, window_end_at,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    batch_id,
                    item.product_id,
                    cycle_text,
                    sequence_no,
                    item.verified_direct_url,
                    start.isoformat(timespec="seconds"),
                    end.isoformat(timespec="seconds"),
                    timestamp,
                    timestamp,
                ),
            )
        _add_event(
            conn,
            batch_id=batch_id,
            plan_id=None,
            event_type="snapshot_frozen",
            from_status=None,
            to_status="active",
            owner=None,
            reason_code=None,
            event_at=timestamp,
            details={
                "followed_products": [
                    {
                        "product_id": item.product_id,
                        "verified_direct_url": item.verified_direct_url,
                    }
                    for item in snapshot
                ]
            },
        )
        if not snapshot:
            conn.execute(
                """
                UPDATE daily_sales_batches
                SET status='completed', completed_at=?, updated_at=? WHERE id=?
                """,
                (timestamp, timestamp, batch_id),
            )
    return {
        "created": True,
        "code": "snapshot_created",
        "cycle_date": cycle_text,
        "batch_id": batch_id,
        "snapshot_count": len(snapshot),
    }


def get_next_pending_daily_sales_task(
    conn: sqlite3.Connection, *, cycle_date: str | date
) -> dict[str, Any]:
    """Read the first unfinished item without repeating terminal items."""
    cycle_text = _cycle_date(cycle_date).isoformat()
    batch = _get_batch_by_cycle(conn, cycle_text)
    if batch is None:
        return {"available": False, "code": "batch_not_found"}
    if batch["status"] == "hard_stopped":
        return {
            "available": False,
            "code": "batch_hard_stopped",
            "reason_code": batch["hard_stop_reason"],
        }
    task = _row(
        conn.execute(
            """
            SELECT id AS plan_id, product_id, sequence_no,
                   verified_direct_url, status
            FROM daily_sales_plans
            WHERE batch_id=? AND status='pending'
            ORDER BY sequence_no LIMIT 1
            """,
            (batch["id"],),
        )
    )
    if task is None:
        return {
            "available": False,
            "code": "batch_completed" if batch["status"] == "completed" else "no_pending",
        }
    return {"available": True, "code": "pending_task", **task}


def claim_daily_sales_task(
    conn: sqlite3.Connection,
    *,
    plan_id: int,
    owner: str,
    now: str | datetime | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    """Claim a pending item or reclaim an expired item when its batch is active."""
    if not owner or not owner.strip():
        raise ValueError("owner_required")
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or lease_seconds <= 0:
        raise ValueError("lease_seconds_must_be_positive_integer")
    timestamp = _utc_iso(now)
    lease_expires = (
        _parse_aware(timestamp).astimezone(UTC) + timedelta(seconds=lease_seconds)
    ).isoformat(timespec="seconds")

    with _write_transaction(conn):
        plan = _get_plan(conn, plan_id)
        if plan is None:
            return {"claimed": False, "code": "not_found", "plan_id": plan_id}
        batch = _get_batch(conn, plan["batch_id"])
        if batch["status"] == "hard_stopped":
            return {
                "claimed": False,
                "code": "batch_hard_stopped",
                "plan_id": plan_id,
                "reason_code": batch["hard_stop_reason"],
            }
        if batch["status"] == "completed" or plan["status"] in TERMINAL_STATUSES:
            return {
                "claimed": False,
                "code": "terminal",
                "plan_id": plan_id,
                "status": plan["status"],
            }
        if plan["status"] == "running" and plan["lease_expires_at"] > timestamp:
            return {
                "claimed": False,
                "code": "lease_held",
                "plan_id": plan_id,
                "owner": plan["owner"],
                "lease_expires_at": plan["lease_expires_at"],
            }

        reclaimed = plan["status"] == "running"
        conn.execute(
            """
            UPDATE daily_sales_plans
            SET status='running', owner=?, lease_expires_at=?,
                claim_count=claim_count+1, recovery_count=recovery_count+?,
                updated_at=?
            WHERE id=?
            """,
            (owner.strip(), lease_expires, int(reclaimed), timestamp, plan_id),
        )
        _add_event(
            conn,
            batch_id=plan["batch_id"],
            plan_id=plan_id,
            event_type="expired_reclaimed" if reclaimed else "claimed",
            from_status=plan["status"],
            to_status="running",
            owner=owner.strip(),
            reason_code="lease_expired" if reclaimed else None,
            event_at=timestamp,
            details={"previous_owner": plan["owner"]} if reclaimed else None,
        )
    return {
        "claimed": True,
        "code": "expired_reclaimed" if reclaimed else "claimed",
        "plan_id": plan_id,
        "owner": owner.strip(),
        "lease_expires_at": lease_expires,
        "verified_direct_url": plan["verified_direct_url"],
    }


def record_daily_sales_result(
    conn: sqlite3.Connection,
    *,
    plan_id: int,
    owner: str,
    observed_product_id: int | None,
    observed_at: str | datetime,
    cumulative_sales_exact: int | None = None,
    cumulative_sales_display: str | None = None,
    outcome: str = "sample",
    reason_code: str | None = None,
    reason_detail: str | None = None,
    action_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Finalize one item; ordinary failures isolate the item, safety failures stop the batch."""
    if outcome not in RESULT_OUTCOMES:
        raise ValueError("invalid_outcome")
    if not owner or not owner.strip():
        raise ValueError("owner_required")
    observed_timestamp = _parse_aware(observed_at).isoformat(timespec="seconds")
    action_timestamp = _utc_iso(action_at)

    with _write_transaction(conn):
        plan = _get_plan(conn, plan_id)
        if plan is None:
            return {"recorded": False, "code": "not_found", "plan_id": plan_id}
        batch = _get_batch(conn, plan["batch_id"])
        if plan["status"] in TERMINAL_STATUSES:
            return {
                "recorded": False,
                "code": "already_final",
                "plan_id": plan_id,
                "status": plan["status"],
            }
        if batch["status"] == "hard_stopped":
            return {
                "recorded": False,
                "code": "batch_hard_stopped",
                "plan_id": plan_id,
                "reason_code": batch["hard_stop_reason"],
            }
        if plan["status"] != "running":
            return {
                "recorded": False,
                "code": "not_running",
                "plan_id": plan_id,
                "status": plan["status"],
            }
        if plan["owner"] != owner.strip():
            return {
                "recorded": False,
                "code": "owner_mismatch",
                "plan_id": plan_id,
                "owner": plan["owner"],
            }
        if plan["lease_expires_at"] <= action_timestamp:
            return {
                "recorded": False,
                "code": "lease_expired",
                "plan_id": plan_id,
                "lease_expires_at": plan["lease_expires_at"],
            }

        hard_stop_reason = _hard_stop_reason(
            outcome=outcome,
            reason_code=reason_code,
            observed_product_id=observed_product_id,
            expected_product_id=plan["product_id"],
        )
        if hard_stop_reason is not None:
            _finalize_plan(
                conn,
                plan=plan,
                status="risk_stopped",
                owner=owner.strip(),
                observed_at=observed_timestamp,
                display=cumulative_sales_display,
                exact=cumulative_sales_exact,
                delta=None,
                reason_code=hard_stop_reason,
                reason_detail=reason_detail,
                action_at=action_timestamp,
            )
            _hard_stop_batch(
                conn,
                batch_id=plan["batch_id"],
                plan_id=plan_id,
                owner=owner.strip(),
                reason_code=hard_stop_reason,
                reason_detail=reason_detail,
                action_at=action_timestamp,
            )
            return {
                "recorded": True,
                "code": "batch_hard_stopped",
                "plan_id": plan_id,
                "status": "risk_stopped",
                "daily_sales_delta": None,
                "reason_code": hard_stop_reason,
                "continue_batch": False,
            }

        final_status: str
        final_reason = reason_code
        delta: int | None = None
        if outcome == "skipped":
            final_status = "skipped"
            final_reason = final_reason or "ordinary_item_skipped"
        elif outcome == "failed":
            final_status = "failed"
            final_reason = final_reason or "ordinary_item_failed"
        else:
            cycle = date.fromisoformat(plan["cycle_date"])
            if not _in_cycle_window(observed_timestamp, cycle):
                final_status = "failed"
                final_reason = "outside_midnight_window"
            elif type(cumulative_sales_exact) is int and cumulative_sales_exact >= 0:
                baseline = _find_previous_exact_baseline(
                    conn, product_id=plan["product_id"], cycle=cycle
                )
                if baseline is None:
                    final_status = "failed"
                    final_reason = "missing_previous_exact_baseline"
                elif cumulative_sales_exact < baseline["exact"]:
                    final_status = "failed"
                    final_reason = "sales_decreased"
                else:
                    delta = calculate_daily_sales_delta(
                        previous_exact=baseline["exact"],
                        previous_at=baseline["observed_at"],
                        current_exact=cumulative_sales_exact,
                        current_at=observed_timestamp,
                    )
                    if delta is None:
                        final_status = "failed"
                        final_reason = "invalid_daily_baseline"
                    else:
                        final_status = "completed_exact"
            elif (
                cumulative_sales_exact is None
                and isinstance(cumulative_sales_display, str)
                and cumulative_sales_display.strip()
            ):
                final_status = "completed_fuzzy"
            else:
                final_status = "failed"
                final_reason = "invalid_sales_sample"

        _finalize_plan(
            conn,
            plan=plan,
            status=final_status,
            owner=owner.strip(),
            observed_at=observed_timestamp,
            display=cumulative_sales_display,
            exact=cumulative_sales_exact,
            delta=delta,
            reason_code=final_reason,
            reason_detail=reason_detail,
            action_at=action_timestamp,
        )
        _refresh_batch_completion(conn, plan["batch_id"], action_timestamp)
    return {
        "recorded": True,
        "code": final_status,
        "plan_id": plan_id,
        "status": final_status,
        "daily_sales_delta": delta,
        "reason_code": final_reason,
        "continue_batch": True,
    }


def hard_stop_daily_sales_cycle(
    conn: sqlite3.Connection,
    *,
    cycle_date: str | date,
    reason_code: str,
    owner: str,
    reason_detail: str | None = None,
    action_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Persist an externally detected batch-level safety stop."""
    if reason_code not in HARD_STOP_REASONS:
        raise ValueError("reason_is_not_batch_hard_stop")
    timestamp = _utc_iso(action_at)
    with _write_transaction(conn):
        batch = _get_batch_by_cycle(conn, _cycle_date(cycle_date).isoformat())
        if batch is None:
            return {"stopped": False, "code": "batch_not_found"}
        if batch["status"] == "hard_stopped":
            return {
                "stopped": False,
                "code": "already_hard_stopped",
                "reason_code": batch["hard_stop_reason"],
            }
        if batch["status"] == "completed":
            return {"stopped": False, "code": "batch_completed"}
        _hard_stop_batch(
            conn,
            batch_id=batch["id"],
            plan_id=None,
            owner=owner,
            reason_code=reason_code,
            reason_detail=reason_detail,
            action_at=timestamp,
        )
    return {
        "stopped": True,
        "code": "batch_hard_stopped",
        "reason_code": reason_code,
    }


def recover_expired_daily_sales_tasks(
    conn: sqlite3.Connection,
    *,
    now: str | datetime | None = None,
    recovery_owner: str = "offline_recovery",
) -> dict[str, Any]:
    """After restart, return expired running items to pending only in active batches."""
    timestamp = _utc_iso(now)
    recovered_ids: list[int] = []
    with _write_transaction(conn):
        expired = _rows(
            conn.execute(
                """
                SELECT p.id, p.batch_id, p.owner
                FROM daily_sales_plans AS p
                JOIN daily_sales_batches AS b ON b.id=p.batch_id
                WHERE p.status='running' AND p.lease_expires_at<=?
                  AND b.status='active'
                ORDER BY p.sequence_no
                """,
                (timestamp,),
            )
        )
        for item in expired:
            conn.execute(
                """
                UPDATE daily_sales_plans
                SET status='pending', owner=NULL, lease_expires_at=NULL,
                    recovery_count=recovery_count+1, updated_at=?
                WHERE id=? AND status='running' AND lease_expires_at<=?
                """,
                (timestamp, item["id"], timestamp),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                continue
            recovered_ids.append(item["id"])
            _add_event(
                conn,
                batch_id=item["batch_id"],
                plan_id=item["id"],
                event_type="lease_recovered",
                from_status="running",
                to_status="pending",
                owner=recovery_owner,
                reason_code="lease_expired",
                event_at=timestamp,
                details={"previous_owner": item["owner"]},
            )
    return {"recovered_count": len(recovered_ids), "recovered_plan_ids": recovered_ids}


def get_daily_sales_cycle_summary(
    conn: sqlite3.Connection, *, cycle_date: str | date
) -> dict[str, Any]:
    """Return the frozen-list batch status, complete counts and every item result."""
    cycle = _cycle_date(cycle_date).isoformat()
    batch = _get_batch_by_cycle(conn, cycle)
    if batch is None:
        return {
            "cycle_date": cycle,
            "batch_status": "not_planned",
            "total": 0,
            **{status: 0 for status in ALL_STATUSES},
            "all_items_final": False,
            "items": [],
        }
    items = _rows(
        conn.execute(
            """
            SELECT
                p.id AS plan_id, p.product_id, p.sequence_no,
                products.title, p.verified_direct_url,
                p.cycle_date, p.window_start_at, p.window_end_at, p.status,
                p.owner, p.lease_expires_at, p.observed_at,
                p.cumulative_sales_display, p.cumulative_sales_exact,
                p.daily_sales_delta, p.reason_code, p.reason_detail,
                p.claim_count, p.recovery_count
            FROM daily_sales_plans AS p
            JOIN products ON products.id=p.product_id
            WHERE p.batch_id=?
            ORDER BY p.sequence_no
            """,
            (batch["id"],),
        )
    )
    counts = {status: 0 for status in ALL_STATUSES}
    for item in items:
        counts[item["status"]] += 1
    return {
        "cycle_date": cycle,
        "batch_id": batch["id"],
        "batch_status": batch["status"],
        "hard_stop_reason": batch["hard_stop_reason"],
        "hard_stop_detail": batch["hard_stop_detail"],
        "snapshot_count": batch["snapshot_count"],
        "total": len(items),
        **counts,
        "all_items_final": len(items) == sum(counts[s] for s in TERMINAL_STATUSES),
        "items": items,
    }


def _normalize_followed_item(
    value: FollowedProductSnapshotItem | Mapping[str, Any],
) -> FollowedProductSnapshotItem:
    if isinstance(value, FollowedProductSnapshotItem):
        item = value
    elif isinstance(value, Mapping):
        try:
            item = FollowedProductSnapshotItem(
                product_id=value["product_id"],
                verified_direct_url=value["verified_direct_url"],
            )
        except KeyError as error:
            raise ValueError("followed_product_fields_required") from error
    else:
        raise ValueError("invalid_followed_product_item")
    if (
        not isinstance(item.product_id, int)
        or isinstance(item.product_id, bool)
        or item.product_id <= 0
    ):
        raise ValueError("invalid_product_id")
    if not _is_allowed_product_direct_url(item.verified_direct_url):
        raise ValueError(f"invalid_verified_direct_url:{item.product_id}")
    return FollowedProductSnapshotItem(
        product_id=item.product_id,
        verified_direct_url=item.verified_direct_url.strip(),
    )


def _is_allowed_product_direct_url(value: Any) -> bool:
    return isinstance(value, str) and is_supported_product_direct_url(value.strip())


def _hard_stop_reason(
    *,
    outcome: str,
    reason_code: str | None,
    observed_product_id: int | None,
    expected_product_id: int,
) -> str | None:
    if observed_product_id != expected_product_id:
        return "identity_unknown"
    if outcome in {"hard_stop", "risk_stopped"}:
        if reason_code not in HARD_STOP_REASONS:
            raise ValueError("hard_stop_reason_required")
        return reason_code
    if reason_code in HARD_STOP_REASONS:
        return reason_code
    return None


def _finalize_plan(
    conn: sqlite3.Connection,
    *,
    plan: dict[str, Any],
    status: str,
    owner: str,
    observed_at: str,
    display: str | None,
    exact: int | None,
    delta: int | None,
    reason_code: str | None,
    reason_detail: str | None,
    action_at: str,
) -> None:
    stored_exact = exact if type(exact) is int else None
    conn.execute(
        """
        UPDATE daily_sales_plans
        SET status=?, observed_at=?, cumulative_sales_display=?,
            cumulative_sales_exact=?, daily_sales_delta=?,
            reason_code=?, reason_detail=?, lease_expires_at=NULL,
            updated_at=?, completed_at=?
        WHERE id=? AND status='running' AND owner=?
        """,
        (
            status,
            observed_at,
            display,
            stored_exact,
            delta,
            reason_code,
            reason_detail,
            action_at,
            action_at,
            plan["id"],
            owner,
        ),
    )
    _add_event(
        conn,
        batch_id=plan["batch_id"],
        plan_id=plan["id"],
        event_type="result_recorded",
        from_status="running",
        to_status=status,
        owner=owner,
        reason_code=reason_code,
        event_at=action_at,
        details={"observed_at": observed_at},
    )


def _hard_stop_batch(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    plan_id: int | None,
    owner: str,
    reason_code: str,
    reason_detail: str | None,
    action_at: str,
) -> None:
    previous = _get_batch(conn, batch_id)
    conn.execute(
        """
        UPDATE daily_sales_batches
        SET status='hard_stopped', hard_stop_reason=?, hard_stop_detail=?,
            hard_stopped_at=?, updated_at=?
        WHERE id=? AND status='active'
        """,
        (reason_code, reason_detail, action_at, action_at, batch_id),
    )
    _add_event(
        conn,
        batch_id=batch_id,
        plan_id=plan_id,
        event_type="batch_hard_stopped",
        from_status=previous["status"],
        to_status="hard_stopped",
        owner=owner,
        reason_code=reason_code,
        event_at=action_at,
        details={"reason_detail": reason_detail},
    )


def _refresh_batch_completion(
    conn: sqlite3.Connection, batch_id: int, action_at: str
) -> None:
    remaining = conn.execute(
        """
        SELECT COUNT(*) FROM daily_sales_plans
        WHERE batch_id=? AND status IN ('pending', 'running')
        """,
        (batch_id,),
    ).fetchone()[0]
    if remaining == 0:
        conn.execute(
            """
            UPDATE daily_sales_batches
            SET status='completed', completed_at=?, updated_at=?
            WHERE id=? AND status='active'
            """,
            (action_at, action_at, batch_id),
        )


def _get_plan(conn: sqlite3.Connection, plan_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM daily_sales_plans WHERE id=?", (plan_id,)))


def _get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any]:
    batch = _row(conn.execute("SELECT * FROM daily_sales_batches WHERE id=?", (batch_id,)))
    if batch is None:
        raise RuntimeError("daily_sales_batch_missing")
    return batch


def _get_batch_by_cycle(
    conn: sqlite3.Connection, cycle_date: str
) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM daily_sales_batches WHERE cycle_date=?", (cycle_date,)
        )
    )


def _find_previous_exact_baseline(
    conn: sqlite3.Connection, *, product_id: int, cycle: date
) -> dict[str, Any] | None:
    previous_cycle = (cycle - timedelta(days=1)).isoformat()
    tracking = _row(
        conn.execute(
            """
            SELECT cumulative_sales_exact AS exact, observed_at
            FROM daily_sales_plans
            WHERE product_id=? AND cycle_date=? AND status='completed_exact'
              AND cumulative_sales_exact IS NOT NULL
            """,
            (product_id, previous_cycle),
        )
    )
    if tracking is not None:
        return tracking
    observations = _rows(
        conn.execute(
            """
            SELECT cumulative_sales_exact AS exact, observed_at
            FROM observations
            WHERE product_id=? AND cumulative_sales_exact IS NOT NULL
            ORDER BY id DESC
            """,
            (product_id,),
        )
    )
    previous_date = cycle - timedelta(days=1)
    for item in observations:
        if type(item["exact"]) is not int or item["exact"] < 0:
            continue
        try:
            if _in_cycle_window(item["observed_at"], previous_date):
                return item
        except (TypeError, ValueError):
            continue
    return None


def _add_event(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    plan_id: int | None,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    owner: str | None,
    reason_code: str | None,
    event_at: str,
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO daily_sales_events(
            batch_id, plan_id, event_type, from_status, to_status,
            owner, reason_code, event_at, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            plan_id,
            event_type,
            from_status,
            to_status,
            owner,
            reason_code,
            event_at,
            json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
        ),
    )
