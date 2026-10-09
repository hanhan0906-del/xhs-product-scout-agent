import threading

import pytest

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    set_monitor_desired_state,
    set_monitor_state,
)
from xhs_scout.monitor import MonitorLimits, monitor_once
from xhs_scout.run_control import (
    RetryPolicy,
    acquire_monitor_lease,
    current_monitor_lease,
    mark_task_failed,
    mark_task_succeeded,
    release_monitor_lease,
    reserve_next_runnable_task,
)
from xhs_scout.scheduler import MonitorScheduler


FUTURE = "2099-01-01T00:00:00+00:00"


class BlockingRecoveryWake:
    """Expose the scheduler while it is inside its first recovery backoff."""

    def __init__(self):
        self.waits = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait(self, timeout):
        self.waits.append(timeout)
        self.entered.set()
        assert self.release.wait(2), "test did not release scheduler recovery wait"
        return False

    def clear(self):
        pass


class ImmediateWake:
    def __init__(self):
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)
        return False

    def clear(self):
        pass


class FakeDevice:
    def __init__(self):
        self.calls = []

    def tap(self, x, y):
        self.calls.append(("tap", x, y))

    def back(self):
        self.calls.append(("back",))


def _offline_report(settings, limit=20):
    return {
        "report_path": str(settings.reports_dir / "offline-t38.md"),
        "count": 0,
        "limit": limit,
    }


def _enqueue_and_reserve(settings, *, keyword, owner):
    with connect(settings.db_path) as conn:
        enqueue(conn, [keyword], source="t38")
        acquired = acquire_monitor_lease(
            conn,
            owner=owner,
            ttl_seconds=3600,
        )
        assert acquired["acquired"] is True
        task = reserve_next_runnable_task(
            conn,
            owner=owner,
            policy=RetryPolicy(task_lease_seconds=3600),
        )
        assert task is not None
        set_monitor_state(conn, "last_run_id", owner)
        return task["id"]


def test_scheduler_recovery_snapshot_matches_database_before_and_after_retry(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    wake = BlockingRecoveryWake()
    calls = []

    monkeypatch.setattr(
        "xhs_scout.scheduler.ensure_portfolio_queue",
        lambda *_args, **_kwargs: {"queued": 0},
    )

    def fail_once_then_pause(_settings, *, limits):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("t38 transient scheduler failure")
        with connect(settings.db_path) as conn:
            set_monitor_desired_state(conn, "paused")
        return {
            "run_id": "t38-recovered",
            "captured_products": 0,
            "blocked": "t38 complete",
            "busy": False,
        }

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fail_once_then_pause)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(
        settings,
        recovery_initial_seconds=7,
        recovery_max_seconds=20,
        max_consecutive_failures=3,
    )
    scheduler._wake = wake
    assert scheduler.start() is True
    assert wake.entered.wait(2), "scheduler never entered recovery backoff"

    during = scheduler.snapshot()
    with connect(settings.db_path) as conn:
        persisted_during = get_monitor_state(conn)

    assert during["thread_alive"] is True
    assert during["worker_state"] == "backing_off"
    assert during["consecutive_failures"] == 1
    assert during["next_retry_at"] == persisted_during["next_run_at"]
    assert persisted_during["scheduler_running"] is True
    assert persisted_during["scheduler_recovery_state"] == "backing_off"
    assert persisted_during["scheduler_consecutive_failures"] == 1

    wake.release.set()
    scheduler._thread.join(timeout=2)

    after = scheduler.snapshot()
    with connect(settings.db_path) as conn:
        persisted_after = get_monitor_state(conn)

    assert calls == [1, 2]
    assert wake.waits == [7]
    assert after["thread_alive"] is False
    assert after["worker_state"] == "stopped"
    assert after["consecutive_failures"] == 0
    assert after["recovery_count"] == 1
    assert persisted_after["scheduler_running"] is False
    assert persisted_after["scheduler_recovery_state"] == "stopped"
    assert persisted_after["scheduler_consecutive_failures"] == 0
    assert persisted_after["scheduler_recovery_count"] == 1
    assert persisted_after["next_run_at"] is None


def test_scheduler_exception_budget_pauses_and_only_cleans_failed_round_owner(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    wake = ImmediateWake()
    calls = []
    task_ids = []

    monkeypatch.setattr(
        "xhs_scout.scheduler.ensure_portfolio_queue",
        lambda *_args, **_kwargs: {"queued": 0},
    )

    with connect(settings.db_path) as conn:
        enqueue(conn, ["replacement-owned"], source="t38")
        conn.execute(
            """
            UPDATE search_tasks
            SET status='running', attempts=1, run_owner='replacement-owner',
                run_lease_expires_at=?
            WHERE keyword='replacement-owned'
            """,
            (FUTURE,),
        )
        set_monitor_desired_state(conn, "running")

    def always_fail(_settings, *, limits):
        call = len(calls) + 1
        calls.append(call)
        owner = f"failed-owner-{call}"
        task_ids.append(
            _enqueue_and_reserve(
                settings,
                keyword=f"failed-task-{call}",
                owner=owner,
            )
        )
        raise OSError(f"t38 failure {call}")

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", always_fail)
    scheduler = MonitorScheduler(
        settings,
        recovery_initial_seconds=2,
        recovery_max_seconds=2,
        max_consecutive_failures=2,
    )
    scheduler._wake = wake
    scheduler._run()

    snapshot = scheduler.snapshot()
    assert calls == [1, 2]
    assert wake.waits == [2]
    assert snapshot["thread_alive"] is False
    assert snapshot["worker_state"] == "paused_after_error_budget"
    assert snapshot["consecutive_failures"] == 2
    assert snapshot["recovery_count"] == 1
    assert snapshot["next_retry_at"] is None

    with connect(settings.db_path) as conn:
        failed = conn.execute(
            """
            SELECT id, status, run_owner, run_lease_expires_at, last_error
            FROM search_tasks
            WHERE id IN (?, ?)
            ORDER BY id
            """,
            task_ids,
        ).fetchall()
        replacement = conn.execute(
            """
            SELECT status, run_owner, run_lease_expires_at
            FROM search_tasks
            WHERE keyword='replacement-owned'
            """
        ).fetchone()
        state = get_monitor_state(conn)

    assert [row["status"] for row in failed] == ["pending", "pending"]
    assert all(row["run_owner"] is None for row in failed)
    assert all(row["run_lease_expires_at"] is None for row in failed)
    assert all("t38 failure" in row["last_error"] for row in failed)
    assert tuple(replacement) == ("running", "replacement-owner", FUTURE)
    assert state["desired_state"] == "paused"
    assert state["scheduler_running"] is False
    assert state["scheduler_recovery_state"] == "paused_after_error_budget"
    assert state["next_run_at"] is None
    assert state["risk_stop_reason"] is None


def test_scheduler_recovery_does_not_clear_risk_stop_from_failed_round(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    wake = ImmediateWake()
    calls = []

    monkeypatch.setattr(
        "xhs_scout.scheduler.ensure_portfolio_queue",
        lambda *_args, **_kwargs: {"queued": 0},
    )

    def fail_with_risk(_settings, *, limits):
        calls.append("monitor")
        _enqueue_and_reserve(
            settings,
            keyword="risk-owned-task",
            owner="risk-owner",
        )
        with connect(settings.db_path) as conn:
            set_monitor_state(conn, "risk_stop_reason", "t38 captcha risk")
        raise RuntimeError("device exception after risk stop")

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fail_with_risk)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(
        settings,
        recovery_initial_seconds=1,
        max_consecutive_failures=3,
    )
    scheduler._wake = wake
    scheduler._run()

    snapshot = scheduler.snapshot()
    assert calls == ["monitor"]
    assert wake.waits == [1]
    assert snapshot["thread_alive"] is False
    assert snapshot["worker_state"] == "risk_paused"
    assert snapshot["recovery_count"] == 0

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        task = conn.execute(
            """
            SELECT status, run_owner, run_lease_expires_at
            FROM search_tasks
            WHERE keyword='risk-owned-task'
            """
        ).fetchone()

    assert state["desired_state"] == "paused"
    assert state["risk_stop_reason"] == "t38 captcha risk"
    assert state["scheduler_running"] is False
    assert state["scheduler_recovery_state"] == "risk_paused"
    assert state["next_run_at"] is None
    assert task["status"] == "pending"
    assert task["run_owner"] is None
    assert task["run_lease_expires_at"] is None


def test_monitor_lease_takeover_stops_later_device_steps_and_preserves_new_owner(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
        wait_seconds=0,
    )
    device = FakeDevice()
    later_calls = []

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)

    def search_then_take_over(_settings, called_device, **_kwargs):
        called_device.tap(11, 22)
        with connect(settings.db_path) as conn:
            conn.execute(
                """
                UPDATE run_leases
                SET owner='replacement-owner', expires_at=?
                WHERE name='monitor_once'
                """,
                (FUTURE,),
            )
            conn.execute(
                """
                UPDATE search_tasks
                SET run_owner='replacement-owner', run_lease_expires_at=?
                WHERE keyword='lease takeover' AND status='running'
                """,
                (FUTURE,),
            )
        return {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        }

    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        search_then_take_over,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards",
        lambda *_args, **_kwargs: later_calls.append("find cards") or [],
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        lambda *_args, **_kwargs: later_calls.append("capture") or {},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._recover_to_search_results_after_detail",
        lambda *_args, **_kwargs: later_calls.append("return") or True,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        _offline_report,
    )
    with connect(settings.db_path) as conn:
        enqueue(conn, ["lease takeover"], source="t38")
        set_monitor_desired_state(conn, "running")

    output = monitor_once(settings, limits=limits)

    assert device.calls == [("tap", 11, 22)]
    assert later_calls == []
    assert output["lease_safety_blocked"] == {
        "phase": "after_search_stage",
        "reason": "monitor_owner_mismatch",
    }
    assert output["blocked"] == (
        "lease safety blocked at after_search_stage: monitor_owner_mismatch"
    )

    with connect(settings.db_path) as conn:
        task = conn.execute(
            """
            SELECT status, run_owner, run_lease_expires_at
            FROM search_tasks
            WHERE keyword='lease takeover'
            """
        ).fetchone()
        lease = current_monitor_lease(conn)
        state = get_monitor_state(conn)

    assert tuple(task) == ("running", "replacement-owner", FUTURE)
    assert lease["owner"] == "replacement-owner"
    assert lease["expires_at"] == FUTURE
    assert state["desired_state"] == "paused"
    assert state["risk_stop_reason"] == output["blocked"]
    assert state["last_block_reason"] == output["blocked"]


def test_wrong_owner_cannot_complete_fail_or_release_owned_work(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["owner guarded"], source="t38")
        acquired = acquire_monitor_lease(
            conn,
            owner="owner-a",
            ttl_seconds=3600,
        )
        assert acquired["acquired"] is True
        task = reserve_next_runnable_task(
            conn,
            owner="owner-a",
            policy=RetryPolicy(task_lease_seconds=3600),
        )
        assert task is not None

        with pytest.raises(RuntimeError, match="owner-b"):
            mark_task_succeeded(
                conn,
                task_id=task["id"],
                owner="owner-b",
            )
        with pytest.raises(RuntimeError, match="owner-b"):
            mark_task_failed(
                conn,
                task_id=task["id"],
                owner="owner-b",
                reason="must not mutate",
            )
        assert release_monitor_lease(conn, owner="owner-b") is False

        stored = conn.execute(
            """
            SELECT status, attempts, run_owner, run_lease_expires_at, last_error
            FROM search_tasks
            WHERE id=?
            """,
            (task["id"],),
        ).fetchone()
        lease = current_monitor_lease(conn)

    assert stored["status"] == "running"
    assert stored["attempts"] == 1
    assert stored["run_owner"] == "owner-a"
    assert stored["run_lease_expires_at"] == task["run_lease_expires_at"]
    assert stored["last_error"] is None
    assert lease["owner"] == "owner-a"
