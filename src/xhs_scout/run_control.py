from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .db import (
    acquire_run_lease,
    get_run_lease,
    release_run_lease,
    utcnow,
)


MONITOR_LEASE_NAME = "monitor_once"
RUNNABLE_TASK_STATUSES = ("pending",)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_cooldown_seconds: int = 300
    max_cooldown_seconds: int = 3600
    task_lease_seconds: int = 900


@dataclass(frozen=True)
class LeaseSafetyResult:
    """Fail-closed ownership result for a device-operation boundary."""

    safe_to_continue: bool
    renewed: bool
    reason: str
    owner: str
    task_id: int
    checked_at: str
    monitor_expires_at: str | None = None
    task_expires_at: str | None = None
    database_error: str | None = None


def _add_seconds(timestamp: str, seconds: int) -> str:
    return (
        datetime.fromisoformat(timestamp)
        + timedelta(seconds=max(0, int(seconds)))
    ).isoformat(timespec="seconds")


def _cooldown_seconds(attempts: int, policy: RetryPolicy) -> int:
    if attempts <= 0:
        return 0
    cooldown = policy.base_cooldown_seconds * (2 ** max(0, attempts - 1))
    return min(cooldown, policy.max_cooldown_seconds)


def acquire_monitor_lease(
    conn: sqlite3.Connection,
    *,
    owner: str,
    ttl_seconds: int = 900,
    now: str | None = None,
    metadata: dict | None = None,
) -> dict:
    return acquire_run_lease(
        conn,
        name=MONITOR_LEASE_NAME,
        owner=owner,
        ttl_seconds=ttl_seconds,
        now=now,
        metadata=metadata,
    )


def heartbeat_monitor_lease(
    conn: sqlite3.Connection,
    *,
    owner: str,
    ttl_seconds: int = 900,
    now: str | None = None,
) -> bool:
    now = now or utcnow()
    expires_at = _add_seconds(now, ttl_seconds)
    cur = conn.execute(
        """
        UPDATE run_leases
        SET heartbeat_at=?, expires_at=?
        WHERE name=? AND owner=?
          AND julianday(expires_at) > julianday(?)
        """,
        (now, expires_at, MONITOR_LEASE_NAME, owner, now),
    )
    return bool(cur.rowcount)


def release_monitor_lease(conn: sqlite3.Connection, *, owner: str) -> bool:
    return release_run_lease(conn, name=MONITOR_LEASE_NAME, owner=owner)


def current_monitor_lease(conn: sqlite3.Connection) -> dict | None:
    return get_run_lease(conn, MONITOR_LEASE_NAME)


def check_lease_safety(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    owner: str,
    now: str | None = None,
) -> LeaseSafetyResult:
    """Check that both leases are current and owned; any uncertainty is unsafe."""

    now = now or utcnow()
    try:
        monitor = conn.execute(
            """
            SELECT owner, expires_at
            FROM run_leases
            WHERE name=?
            """,
            (MONITOR_LEASE_NAME,),
        ).fetchone()
        task = conn.execute(
            """
            SELECT status, run_owner, run_lease_expires_at
            FROM search_tasks
            WHERE id=?
            """,
            (task_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        return _unsafe_lease_result(
            owner=owner,
            task_id=task_id,
            now=now,
            reason="database_unavailable",
            database_error=str(exc),
        )

    monitor_expires_at = monitor["expires_at"] if monitor else None
    task_expires_at = task["run_lease_expires_at"] if task else None
    if monitor is None:
        reason = "monitor_lease_missing"
    elif monitor["owner"] != owner:
        reason = "monitor_owner_mismatch"
    elif not _expires_after(monitor_expires_at, now):
        reason = "monitor_lease_expired"
    elif task is None:
        reason = "task_missing"
    elif task["status"] != "running":
        reason = "task_not_running"
    elif task["run_owner"] != owner:
        reason = "task_owner_mismatch"
    elif not _expires_after(task_expires_at, now):
        reason = "task_lease_expired"
    else:
        return LeaseSafetyResult(
            safe_to_continue=True,
            renewed=False,
            reason="owned_leases_active",
            owner=owner,
            task_id=task_id,
            checked_at=now,
            monitor_expires_at=monitor_expires_at,
            task_expires_at=task_expires_at,
        )
    return _unsafe_lease_result(
        owner=owner,
        task_id=task_id,
        now=now,
        reason=reason,
        monitor_expires_at=monitor_expires_at,
        task_expires_at=task_expires_at,
    )


def renew_lease_safety(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    owner: str,
    monitor_ttl_seconds: int = 900,
    policy: RetryPolicy = RetryPolicy(),
    now: str | None = None,
) -> LeaseSafetyResult:
    """Atomically renew active monitor/task leases, or fail closed.

    Expired leases are never revived. Callers must stop all device operations
    whenever ``safe_to_continue`` is false, including database busy/errors.
    """

    now = now or utcnow()
    task_ttl_seconds = int(policy.task_lease_seconds)
    monitor_ttl_seconds = int(monitor_ttl_seconds)
    if monitor_ttl_seconds <= 0 or task_ttl_seconds <= 0:
        return _unsafe_lease_result(
            owner=owner,
            task_id=task_id,
            now=now,
            reason="invalid_lease_ttl",
        )

    monitor_expires_at = _add_seconds(now, monitor_ttl_seconds)
    task_expires_at = _add_seconds(now, task_ttl_seconds)
    savepoint_active = False
    try:
        conn.execute("SAVEPOINT lease_safety_renewal")
        savepoint_active = True
        monitor_cur = conn.execute(
            """
            UPDATE run_leases
            SET heartbeat_at=?, expires_at=?
            WHERE name=? AND owner=?
              AND julianday(expires_at) > julianday(?)
            """,
            (now, monitor_expires_at, MONITOR_LEASE_NAME, owner, now),
        )
        task_cur = conn.execute(
            """
            UPDATE search_tasks
            SET run_lease_expires_at=?, updated_at=?
            WHERE id=? AND status='running' AND run_owner=?
              AND julianday(run_lease_expires_at) > julianday(?)
            """,
            (task_expires_at, now, task_id, owner, now),
        )
        if monitor_cur.rowcount != 1 or task_cur.rowcount != 1:
            conn.execute("ROLLBACK TO SAVEPOINT lease_safety_renewal")
            conn.execute("RELEASE SAVEPOINT lease_safety_renewal")
            savepoint_active = False
            return check_lease_safety(conn, task_id=task_id, owner=owner, now=now)
        conn.execute("RELEASE SAVEPOINT lease_safety_renewal")
        savepoint_active = False
    except sqlite3.Error as exc:
        if savepoint_active:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT lease_safety_renewal")
                conn.execute("RELEASE SAVEPOINT lease_safety_renewal")
            except sqlite3.Error:
                pass
        return _unsafe_lease_result(
            owner=owner,
            task_id=task_id,
            now=now,
            reason="database_unavailable",
            database_error=str(exc),
        )

    return LeaseSafetyResult(
        safe_to_continue=True,
        renewed=True,
        reason="owned_leases_renewed",
        owner=owner,
        task_id=task_id,
        checked_at=now,
        monitor_expires_at=monitor_expires_at,
        task_expires_at=task_expires_at,
    )


def recover_expired_task_leases(
    conn: sqlite3.Connection,
    *,
    policy: RetryPolicy = RetryPolicy(),
    now: str | None = None,
) -> list[dict]:
    now = now or utcnow()
    rows = conn.execute(
        """
        SELECT id, keyword, attempts, max_attempts, run_owner, run_lease_expires_at
        FROM search_tasks
        WHERE status='running'
          AND run_lease_expires_at IS NOT NULL
          AND julianday(run_lease_expires_at) <= julianday(?)
        ORDER BY id
        """,
        (now,),
    ).fetchall()
    recovered: list[dict] = []
    for row in rows:
        attempts = int(row["attempts"] or 0)
        max_attempts = int(row["max_attempts"] or policy.max_attempts)
        exhausted = attempts >= max_attempts
        status = "needs_manual_detail" if exhausted else "pending"
        next_run_at = None if exhausted else _add_seconds(now, _cooldown_seconds(attempts, policy))
        reason = (
            "running task lease expired; retry budget exhausted"
            if exhausted
            else "running task lease expired; recovered for retry"
        )
        conn.execute(
            """
            UPDATE search_tasks
            SET status=?, next_run_at=?, run_owner=NULL, run_lease_expires_at=NULL,
                last_finished_at=?, last_error=?, updated_at=?
            WHERE id=?
            """,
            (status, next_run_at, now, reason, now, row["id"]),
        )
        recovered.append(
            {
                "task_id": row["id"],
                "keyword": row["keyword"],
                "previous_owner": row["run_owner"],
                "attempts": attempts,
                "status": status,
                "next_run_at": next_run_at,
                "reason": reason,
            }
        )
    return recovered


def reserve_next_runnable_task(
    conn: sqlite3.Connection,
    *,
    owner: str,
    policy: RetryPolicy = RetryPolicy(),
    now: str | None = None,
    statuses: Iterable[str] = RUNNABLE_TASK_STATUSES,
    task_id: int | None = None,
    expected_keyword: str | None = None,
) -> dict | None:
    now = now or utcnow()
    recover_expired_task_leases(conn, policy=policy, now=now)
    status_values = tuple(statuses)
    if not status_values:
        raise ValueError("At least one runnable status is required")
    placeholders = ",".join("?" for _ in status_values)
    target_sql = ""
    target_params: list[object] = []
    if task_id is not None:
        target_sql += " AND id=?"
        target_params.append(task_id)
    if expected_keyword is not None:
        target_sql += " AND keyword=?"
        target_params.append(expected_keyword)
    row = conn.execute(
        f"""
        SELECT id, keyword, source, priority, status, attempts, max_attempts,
               next_run_at, last_error
        FROM search_tasks
        WHERE status IN ({placeholders})
          AND attempts < COALESCE(max_attempts, ?)
          AND (next_run_at IS NULL OR julianday(next_run_at) <= julianday(?))
          {target_sql}
        ORDER BY priority DESC, id
        LIMIT 1
        """,
        (*status_values, policy.max_attempts, now, *target_params),
    ).fetchone()
    if row is None:
        return None
    expires_at = _add_seconds(now, policy.task_lease_seconds)
    cur = conn.execute(
        f"""
        UPDATE search_tasks
        SET status='running',
            attempts=attempts+1,
            max_attempts=?,
            run_owner=?,
            run_lease_expires_at=?,
            last_started_at=?,
            last_finished_at=NULL,
            last_error=NULL,
            updated_at=?
        WHERE id=?
          AND status IN ({placeholders})
          AND attempts < COALESCE(max_attempts, ?)
          AND (next_run_at IS NULL OR julianday(next_run_at) <= julianday(?))
          {target_sql}
        """,
        (
            policy.max_attempts,
            owner,
            expires_at,
            now,
            now,
            row["id"],
            *status_values,
            policy.max_attempts,
            now,
            *target_params,
        ),
    )
    if not cur.rowcount:
        return None
    reserved = conn.execute(
        """
        SELECT id, keyword, source, priority, status, attempts, max_attempts,
               next_run_at, run_owner, run_lease_expires_at, last_started_at,
               last_error
        FROM search_tasks
        WHERE id=?
        """,
        (row["id"],),
    ).fetchone()
    return dict(reserved)


def extend_task_lease(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    owner: str,
    policy: RetryPolicy = RetryPolicy(),
    now: str | None = None,
) -> bool:
    now = now or utcnow()
    expires_at = _add_seconds(now, policy.task_lease_seconds)
    cur = conn.execute(
        """
        UPDATE search_tasks
        SET run_lease_expires_at=?, updated_at=?
        WHERE id=? AND status='running' AND run_owner=?
          AND julianday(run_lease_expires_at) > julianday(?)
        """,
        (expires_at, now, task_id, owner, now),
    )
    return bool(cur.rowcount)


def mark_task_succeeded(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    owner: str,
    now: str | None = None,
) -> dict:
    now = now or utcnow()
    row = _running_task_for_owner(conn, task_id=task_id, owner=owner)
    conn.execute(
        """
        UPDATE search_tasks
        SET status='completed', next_run_at=NULL, run_owner=NULL,
            run_lease_expires_at=NULL, last_finished_at=?, last_error=NULL,
            updated_at=?
        WHERE id=?
        """,
        (now, now, task_id),
    )
    return {"task_id": task_id, "keyword": row["keyword"], "status": "completed"}


def mark_task_failed(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    owner: str,
    reason: str,
    policy: RetryPolicy = RetryPolicy(),
    retryable: bool = True,
    now: str | None = None,
) -> dict:
    now = now or utcnow()
    row = _running_task_for_owner(conn, task_id=task_id, owner=owner)
    attempts = int(row["attempts"] or 0)
    max_attempts = int(row["max_attempts"] or policy.max_attempts)
    exhausted = (not retryable) or attempts >= max_attempts
    status = "needs_manual_detail" if exhausted else "pending"
    next_run_at = None if exhausted else _add_seconds(now, _cooldown_seconds(attempts, policy))
    conn.execute(
        """
        UPDATE search_tasks
        SET status=?, next_run_at=?, run_owner=NULL, run_lease_expires_at=NULL,
            last_finished_at=?, last_error=?, updated_at=?
        WHERE id=?
        """,
        (status, next_run_at, now, reason, now, task_id),
    )
    return {
        "task_id": task_id,
        "keyword": row["keyword"],
        "attempts": attempts,
        "max_attempts": max_attempts,
        "status": status,
        "next_run_at": next_run_at,
        "retryable": retryable and not exhausted,
        "reason": reason,
    }


def _running_task_for_owner(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    owner: str,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT id, keyword, status, attempts, max_attempts, run_owner
        FROM search_tasks
        WHERE id=?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"搜索任务不存在：{task_id}")
    if row["status"] != "running" or row["run_owner"] != owner:
        raise RuntimeError(f"任务 {task_id} 当前不由 {owner} 持有")
    return row


def _expires_after(expires_at: str | None, now: str) -> bool:
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) > datetime.fromisoformat(now)
    except (TypeError, ValueError):
        return False


def _unsafe_lease_result(
    *,
    owner: str,
    task_id: int,
    now: str,
    reason: str,
    monitor_expires_at: str | None = None,
    task_expires_at: str | None = None,
    database_error: str | None = None,
) -> LeaseSafetyResult:
    return LeaseSafetyResult(
        safe_to_continue=False,
        renewed=False,
        reason=reason,
        owner=owner,
        task_id=task_id,
        checked_at=now,
        monitor_expires_at=monitor_expires_at,
        task_expires_at=task_expires_at,
        database_error=database_error,
    )
