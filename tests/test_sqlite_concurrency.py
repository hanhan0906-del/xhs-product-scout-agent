from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from xhs_scout.db import (
    connect,
    dashboard_stats,
    enqueue,
    get_monitor_state,
    set_monitor_state,
)
from xhs_scout.run_control import (
    RetryPolicy,
    acquire_monitor_lease,
    heartbeat_monitor_lease,
    mark_task_failed,
    mark_task_succeeded,
    release_monitor_lease,
    renew_lease_safety,
    reserve_next_runnable_task,
)


def test_wal_handles_concurrent_workbench_reads_and_short_monitor_writes(tmp_path):
    """Bounded offline contention model; this is not a wall-clock soak."""

    db_path = tmp_path / "sqlite-concurrency.sqlite3"
    task_count = 8
    reader_count = 3
    reader_iterations = 24
    monitor_iterations = 16
    owner = "offline-concurrency-owner"
    policy = RetryPolicy(
        max_attempts=3,
        base_cooldown_seconds=1,
        task_lease_seconds=300,
    )
    base_time = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)

    with connect(db_path) as conn:
        assert enqueue(
            conn,
            [f"offline-concurrency-{index}" for index in range(task_count)],
            source="t39-offline",
        ) == task_count

    start = threading.Barrier(reader_count + 2 + 1, timeout=5.0)
    errors: list[BaseException] = []
    error_guard = threading.Lock()
    read_counts = [0] * reader_count
    monitor_writes = []
    lifecycle_results = []

    def record_error(exc: BaseException) -> None:
        with error_guard:
            errors.append(exc)

    def reader(reader_index: int) -> None:
        try:
            start.wait()
            for _ in range(reader_iterations):
                with connect(db_path) as conn:
                    stats = dashboard_stats(conn)
                    state = get_monitor_state(conn)
                    task_states = {
                        row["status"]: row["count"]
                        for row in conn.execute(
                            """
                            SELECT status, COUNT(*) AS count
                            FROM search_tasks
                            GROUP BY status
                            """
                        )
                    }
                    lease = conn.execute(
                        """
                        SELECT owner, expires_at
                        FROM run_leases
                        WHERE name='monitor_once'
                        """
                    ).fetchone()

                assert stats["pending_tasks"] >= 0
                assert sum(task_states.values()) == task_count
                assert state["desired_state"] in {"paused", "running"}
                if lease is not None:
                    assert lease["owner"] == owner
                    assert lease["expires_at"]
                read_counts[reader_index] += 1
        except BaseException as exc:  # surfaced with all concurrent failures below
            record_error(exc)

    def monitor_short_writer() -> None:
        try:
            start.wait()
            for sequence in range(monitor_iterations):
                with connect(db_path) as conn:
                    set_monitor_state(conn, "last_heartbeat", f"offline-{sequence:02d}")
                    set_monitor_state(
                        conn,
                        "last_scheduler_output",
                        {"sequence": sequence, "mode": "t39-offline"},
                    )
                monitor_writes.append(sequence)
        except BaseException as exc:  # surfaced with all concurrent failures below
            record_error(exc)

    def lease_and_task_writer() -> None:
        try:
            start.wait()
            acquired_at = base_time.isoformat(timespec="seconds")
            with connect(db_path) as conn:
                acquired = acquire_monitor_lease(
                    conn,
                    owner=owner,
                    ttl_seconds=300,
                    now=acquired_at,
                    metadata={"mode": "t39-offline"},
                )
                assert acquired["acquired"] is True

            for sequence in range(task_count):
                now = (base_time + timedelta(seconds=sequence + 1)).isoformat(
                    timespec="seconds"
                )
                with connect(db_path) as conn:
                    assert heartbeat_monitor_lease(
                        conn,
                        owner=owner,
                        ttl_seconds=300,
                        now=now,
                    )
                    task = reserve_next_runnable_task(
                        conn,
                        owner=owner,
                        policy=policy,
                        now=now,
                    )
                    assert task is not None
                    renewed = renew_lease_safety(
                        conn,
                        task_id=task["id"],
                        owner=owner,
                        monitor_ttl_seconds=300,
                        policy=policy,
                        now=now,
                    )
                    assert renewed.safe_to_continue is True
                    assert renewed.renewed is True
                    if sequence % 2:
                        result = mark_task_failed(
                            conn,
                            task_id=task["id"],
                            owner=owner,
                            reason="bounded offline terminal outcome",
                            policy=policy,
                            retryable=False,
                            now=now,
                        )
                    else:
                        result = mark_task_succeeded(
                            conn,
                            task_id=task["id"],
                            owner=owner,
                            now=now,
                        )
                lifecycle_results.append(result)

            with connect(db_path) as conn:
                assert release_monitor_lease(conn, owner=owner) is True
        except BaseException as exc:  # surfaced with all concurrent failures below
            record_error(exc)

    threads = [
        *[
            threading.Thread(
                target=reader,
                args=(index,),
                name=f"t39-reader-{index}",
                daemon=True,
            )
            for index in range(reader_count)
        ],
        threading.Thread(
            target=monitor_short_writer,
            name="t39-monitor-writer",
            daemon=True,
        ),
        threading.Thread(
            target=lease_and_task_writer,
            name="t39-lease-task-writer",
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    start.wait()

    deadline = time.monotonic() + 15.0
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))

    still_running = [thread.name for thread in threads if thread.is_alive()]
    assert still_running == [], f"bounded workers exceeded 15 seconds: {still_running}"
    assert errors == []
    assert read_counts == [reader_iterations] * reader_count
    assert monitor_writes == list(range(monitor_iterations))
    assert len(lifecycle_results) == task_count

    with connect(db_path) as conn:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        final_state = get_monitor_state(conn)
        lease_count = conn.execute(
            "SELECT COUNT(*) FROM run_leases WHERE name='monitor_once'"
        ).fetchone()[0]
        task_rows = conn.execute(
            """
            SELECT status, attempts, run_owner, run_lease_expires_at, COUNT(*) AS count
            FROM search_tasks
            GROUP BY status, attempts, run_owner, run_lease_expires_at
            ORDER BY status
            """
        ).fetchall()

    assert quick_check == "ok"
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 10_000
    assert final_state["last_heartbeat"] == "offline-15"
    assert final_state["last_scheduler_output"] == {
        "sequence": 15,
        "mode": "t39-offline",
    }
    assert lease_count == 0
    assert [
        (
            row["status"],
            row["attempts"],
            row["run_owner"],
            row["run_lease_expires_at"],
            row["count"],
        )
        for row in task_rows
    ] == [
        ("completed", 1, None, None, task_count // 2),
        ("needs_manual_detail", 1, None, None, task_count // 2),
    ]
