import sqlite3

import pytest

from xhs_scout.db import connect, enqueue, utcnow
from xhs_scout.run_control import (
    RetryPolicy,
    acquire_monitor_lease,
    check_lease_safety,
    current_monitor_lease,
    extend_task_lease,
    heartbeat_monitor_lease,
    mark_task_failed,
    mark_task_succeeded,
    recover_expired_task_leases,
    release_monitor_lease,
    renew_lease_safety,
    reserve_next_runnable_task,
)
from xhs_scout.workflow import start_task


T0 = "2026-07-28T10:00:00+00:00"
T0_10S = "2026-07-28T10:00:10+00:00"
T0_20S = "2026-07-28T10:00:20+00:00"
T0_59S = "2026-07-28T10:00:59+00:00"
T0_60S = "2026-07-28T10:01:00+00:00"
T0_61S = "2026-07-28T10:01:01+00:00"
T0_70S = "2026-07-28T10:01:10+00:00"
T0_80S = "2026-07-28T10:01:20+00:00"
T0_81S = "2026-07-28T10:01:21+00:00"
T0_121S = "2026-07-28T10:02:01+00:00"


def _enqueue_one(conn, keyword="virtual-materials") -> int:
    enqueue(conn, [keyword], source="test")
    return conn.execute("SELECT id FROM search_tasks WHERE keyword=?", (keyword,)).fetchone()[0]


def test_monitor_lease_blocks_second_owner_until_expired(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    with connect(db_path) as conn:
        first = acquire_monitor_lease(
            conn,
            owner="run-a",
            ttl_seconds=60,
            now=T0,
            metadata={"pid": 100},
        )
        assert first["acquired"] is True

        second = acquire_monitor_lease(conn, owner="run-b", ttl_seconds=60, now=T0_10S)
        assert second["acquired"] is False
        assert second["lease"]["owner"] == "run-a"

        assert heartbeat_monitor_lease(conn, owner="run-a", ttl_seconds=60, now=T0_20S)
        assert acquire_monitor_lease(conn, owner="run-b", ttl_seconds=60, now=T0_70S)["acquired"] is False

        takeover = acquire_monitor_lease(conn, owner="run-b", ttl_seconds=60, now=T0_81S)
        assert takeover["acquired"] is True
        assert current_monitor_lease(conn)["owner"] == "run-b"
        assert release_monitor_lease(conn, owner="run-a") is False
        assert release_monitor_lease(conn, owner="run-b") is True
        assert current_monitor_lease(conn) is None


def test_reserve_next_task_sets_task_lease_and_attempt(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(max_attempts=3, base_cooldown_seconds=60, task_lease_seconds=120)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        reserved = reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)

        assert reserved["id"] == task_id
        assert reserved["status"] == "running"
        assert reserved["attempts"] == 1
        assert reserved["run_owner"] == "run-a"
        assert reserved["run_lease_expires_at"] == "2026-07-28T10:02:00+00:00"
        assert reserve_next_runnable_task(conn, owner="run-b", policy=policy, now=T0) is None


def test_workflow_accepts_task_reserved_by_same_monitor_owner(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        reserve_next_runnable_task(conn, owner="run-a", now=T0)

        task = start_task(conn, task_id, owner="run-a")

        assert task["status"] == "running"
        assert task["attempts"] == 1
        assert task["run_owner"] == "run-a"
        with pytest.raises(ValueError):
            start_task(conn, task_id, owner="run-b")


def test_failed_task_uses_backoff_and_next_run_at(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(max_attempts=3, base_cooldown_seconds=60, task_lease_seconds=120)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)

        failure = mark_task_failed(
            conn,
            task_id=task_id,
            owner="run-a",
            reason="opened page is unknown",
            policy=policy,
            now=T0,
        )
        assert failure["status"] == "pending"
        assert failure["next_run_at"] == T0_60S

        assert reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0_59S) is None
        retry = reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0_60S)
        assert retry["attempts"] == 2
        assert retry["last_error"] is None


def test_retry_budget_exhaustion_moves_to_manual_detail(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(max_attempts=2, base_cooldown_seconds=60, task_lease_seconds=120)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)
        mark_task_failed(conn, task_id=task_id, owner="run-a", reason="first failure", policy=policy, now=T0)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0_60S)

        exhausted = mark_task_failed(
            conn,
            task_id=task_id,
            owner="run-a",
            reason="second failure",
            policy=policy,
            now=T0_60S,
        )
        assert exhausted["status"] == "needs_manual_detail"
        assert exhausted["retryable"] is False
        assert exhausted["next_run_at"] is None
        assert reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0_121S) is None


def test_expired_task_lease_is_recovered_with_cooldown(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(max_attempts=3, base_cooldown_seconds=60, task_lease_seconds=60)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)

        assert recover_expired_task_leases(conn, policy=policy, now=T0_59S) == []
        recovered = recover_expired_task_leases(conn, policy=policy, now=T0_61S)
        assert recovered == [
            {
                "task_id": task_id,
                "keyword": "virtual-materials",
                "previous_owner": "run-a",
                "attempts": 1,
                "status": "pending",
                "next_run_at": T0_121S,
                "reason": "running task lease expired; recovered for retry",
            }
        ]
        assert reserve_next_runnable_task(conn, owner="run-b", policy=policy, now=T0_80S) is None
        retry = reserve_next_runnable_task(conn, owner="run-b", policy=policy, now=T0_121S)
        assert retry["attempts"] == 2
        assert retry["run_owner"] == "run-b"


def test_task_success_and_extension_require_matching_owner(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(max_attempts=3, task_lease_seconds=60)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)

        assert extend_task_lease(conn, task_id=task_id, owner="run-b", policy=policy, now=T0_10S) is False
        assert extend_task_lease(conn, task_id=task_id, owner="run-a", policy=policy, now=T0_10S) is True
        with pytest.raises(RuntimeError):
            mark_task_failed(conn, task_id=task_id, owner="run-b", reason="wrong owner", policy=policy, now=T0_10S)

        success = mark_task_succeeded(conn, task_id=task_id, owner="run-a", now=T0_20S)
        assert success["status"] == "completed"
        row = conn.execute(
            "SELECT status, run_owner, run_lease_expires_at, last_finished_at FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(row) == ("completed", None, None, T0_20S)


def test_lease_safety_renewal_is_atomic_and_idempotent(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(task_lease_seconds=60)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        assert acquire_monitor_lease(
            conn, owner="run-a", ttl_seconds=60, now=T0
        )["acquired"]
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)

        before = check_lease_safety(conn, task_id=task_id, owner="run-a", now=T0_10S)
        assert before.safe_to_continue is True
        assert before.renewed is False

        first = renew_lease_safety(
            conn,
            task_id=task_id,
            owner="run-a",
            monitor_ttl_seconds=60,
            policy=policy,
            now=T0_10S,
        )
        second = renew_lease_safety(
            conn,
            task_id=task_id,
            owner="run-a",
            monitor_ttl_seconds=60,
            policy=policy,
            now=T0_10S,
        )

        assert first.safe_to_continue is True
        assert first.renewed is True
        assert first.reason == "owned_leases_renewed"
        assert second == first
        assert current_monitor_lease(conn)["expires_at"] == T0_70S
        task_expiry = conn.execute(
            "SELECT run_lease_expires_at FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()[0]
        assert task_expiry == T0_70S


def test_expired_leases_cannot_be_revived_by_old_owner(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(task_lease_seconds=60)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        acquire_monitor_lease(conn, owner="run-a", ttl_seconds=60, now=T0)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)

        result = renew_lease_safety(
            conn,
            task_id=task_id,
            owner="run-a",
            monitor_ttl_seconds=60,
            policy=policy,
            now=T0_61S,
        )

        assert result.safe_to_continue is False
        assert result.reason == "monitor_lease_expired"
        assert heartbeat_monitor_lease(
            conn, owner="run-a", ttl_seconds=60, now=T0_61S
        ) is False
        assert extend_task_lease(
            conn, task_id=task_id, owner="run-a", policy=policy, now=T0_61S
        ) is False
        takeover = acquire_monitor_lease(
            conn, owner="run-b", ttl_seconds=60, now=T0_61S
        )
        assert takeover["acquired"] is True
        assert takeover["lease"]["owner"] == "run-b"


def test_lease_safety_rejects_wrong_owner_without_mutation(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(task_lease_seconds=60)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        acquire_monitor_lease(conn, owner="run-a", ttl_seconds=60, now=T0)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)

        result = renew_lease_safety(
            conn,
            task_id=task_id,
            owner="run-b",
            monitor_ttl_seconds=60,
            policy=policy,
            now=T0_10S,
        )

        assert result.safe_to_continue is False
        assert result.reason == "monitor_owner_mismatch"
        assert current_monitor_lease(conn)["expires_at"] == T0_60S
        task_expiry = conn.execute(
            "SELECT run_lease_expires_at FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()[0]
        assert task_expiry == T0_60S


def test_lease_safety_fails_closed_after_task_release_and_rolls_back_monitor(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(task_lease_seconds=60)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        acquire_monitor_lease(conn, owner="run-a", ttl_seconds=60, now=T0)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)
        mark_task_succeeded(conn, task_id=task_id, owner="run-a", now=T0_10S)

        result = renew_lease_safety(
            conn,
            task_id=task_id,
            owner="run-a",
            monitor_ttl_seconds=60,
            policy=policy,
            now=T0_20S,
        )

        assert result.safe_to_continue is False
        assert result.reason == "task_not_running"
        assert current_monitor_lease(conn)["expires_at"] == T0_60S
        assert release_monitor_lease(conn, owner="run-a") is True
        released = check_lease_safety(
            conn, task_id=task_id, owner="run-a", now=T0_20S
        )
        assert released.safe_to_continue is False
        assert released.reason == "monitor_lease_missing"


def test_lease_safety_database_busy_is_fail_closed(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    policy = RetryPolicy(task_lease_seconds=60)
    with connect(db_path) as conn:
        task_id = _enqueue_one(conn)
        acquire_monitor_lease(conn, owner="run-a", ttl_seconds=60, now=T0)
        reserve_next_runnable_task(conn, owner="run-a", policy=policy, now=T0)

    worker = sqlite3.connect(db_path)
    worker.row_factory = sqlite3.Row
    worker.execute("PRAGMA busy_timeout=1")
    locker = sqlite3.connect(db_path)
    try:
        locker.execute("BEGIN IMMEDIATE")
        result = renew_lease_safety(
            worker,
            task_id=task_id,
            owner="run-a",
            monitor_ttl_seconds=60,
            policy=policy,
            now=T0_10S,
        )
        assert result.safe_to_continue is False
        assert result.renewed is False
        assert result.reason == "database_unavailable"
        assert "locked" in (result.database_error or "").lower()
    finally:
        locker.rollback()
        locker.close()
        worker.close()

    with connect(db_path) as conn:
        assert current_monitor_lease(conn)["expires_at"] == T0_60S
        task_expiry = conn.execute(
            "SELECT run_lease_expires_at FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()[0]
        assert task_expiry == T0_60S


def test_legacy_search_tasks_get_run_control_columns(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(db_path)
    now = utcnow()
    legacy.execute(
        """
        CREATE TABLE search_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            priority INTEGER NOT NULL DEFAULT 50,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    legacy.execute(
        """
        INSERT INTO search_tasks(keyword, source, created_at, updated_at)
        VALUES ('legacy', 'test', ?, ?)
        """,
        (now, now),
    )
    legacy.commit()
    legacy.close()

    with connect(db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(search_tasks)")}
        assert {
            "max_attempts",
            "next_run_at",
            "run_owner",
            "run_lease_expires_at",
            "last_started_at",
            "last_finished_at",
        }.issubset(columns)
        reserved = reserve_next_runnable_task(conn, owner="run-a", now=T0)
        assert reserved["keyword"] == "legacy"
