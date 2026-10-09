from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    set_monitor_desired_state,
    set_monitor_state,
)
from xhs_scout.scheduler import MonitorScheduler


def test_scheduler_snapshot_uses_conservative_defaults(tmp_path):
    settings = Settings.load(tmp_path)
    scheduler = MonitorScheduler(settings)
    snapshot = scheduler.snapshot()

    assert snapshot["thread_alive"] is False
    assert snapshot["interval_seconds"] == 3600
    assert snapshot["idle_interval_seconds"] == 60
    assert snapshot["limits"] == {
        "max_keywords": 1,
        "max_products_per_keyword": 1,
        "metrics_max_frames": 3,
        "note_evidence": False,
        "restart_app_before_round": False,
    }


def test_scheduler_does_not_cold_restart_app_before_each_round(tmp_path):
    settings = Settings.load(tmp_path)

    scheduler = MonitorScheduler(settings)

    assert scheduler.limits.restart_app_before_round is False


def test_scheduler_uses_immediate_success_and_bounded_idle_delays(tmp_path):
    settings = Settings.load(tmp_path)
    scheduler = MonitorScheduler(
        settings,
        interval_seconds=0,
        idle_interval_seconds=60,
    )

    assert scheduler._delay_after_round(
        scheduler.limits,
        {"captured_products": 1, "busy": False},
    ) == 0
    assert scheduler._delay_after_round(
        None,
        {"captured_products": 0, "busy": False},
    ) == 60
    assert scheduler._delay_after_round(
        scheduler.limits,
        {"captured_products": 0, "busy": False},
    ) == 60
    assert scheduler._delay_after_round(
        scheduler.limits,
        {"captured_products": 1, "busy": True},
    ) == 60


def test_scheduler_start_is_single_thread(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    started = []

    class FakeThread:
        def __init__(self, **kwargs):
            started.append(kwargs)
            self.alive = False

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    monkeypatch.setattr("xhs_scout.scheduler.threading.Thread", FakeThread)
    scheduler = MonitorScheduler(settings)

    assert scheduler.start() is True
    assert scheduler.start() is False
    assert len(started) == 1


class ImmediateWake:
    def __init__(self):
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)
        return False

    def clear(self):
        pass


def test_scheduler_runs_next_successful_round_without_positive_wait(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    calls = []
    wake = ImmediateWake()

    monkeypatch.setattr(
        "xhs_scout.scheduler.ensure_portfolio_queue",
        lambda *args, **kwargs: {"queued": 0},
    )

    def complete_then_stop(*args, **kwargs):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return {
                "run_id": "success-1",
                "captured_products": 1,
                "blocked": None,
                "busy": False,
            }
        with connect(settings.db_path) as conn:
            set_monitor_desired_state(conn, "paused")
        return {
            "run_id": "stop-2",
            "captured_products": 0,
            "blocked": "test complete",
            "busy": False,
        }

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", complete_then_stop)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(settings, interval_seconds=0)
    scheduler._wake = wake
    scheduler._run()

    assert calls == [1, 2]
    assert wake.waits == [0]


def test_scheduler_backs_off_when_no_round_is_runnable(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    monitor_calls = []

    class NoRunnableScheduler(MonitorScheduler):
        def _prepare_round(self, conn):
            return {"queued": 0, "reason": "no runnable task"}, None

    class PauseOnWait:
        def __init__(self):
            self.waits = []

        def wait(self, timeout):
            self.waits.append(timeout)
            with connect(settings.db_path) as conn:
                set_monitor_desired_state(conn, "paused")
            return False

        def clear(self):
            pass

    monkeypatch.setattr(
        "xhs_scout.scheduler.monitor_once",
        lambda *args, **kwargs: monitor_calls.append(True),
    )
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = NoRunnableScheduler(
        settings,
        interval_seconds=0,
        idle_interval_seconds=60,
    )
    wake = PauseOnWait()
    scheduler._wake = wake
    scheduler._run()

    assert monitor_calls == []
    assert wake.waits == [60]


def test_scheduler_recovers_worker_after_round_exception_and_cleans_running_task(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    calls = []
    wake = ImmediateWake()

    monkeypatch.setattr(
        "xhs_scout.scheduler.ensure_portfolio_queue",
        lambda *args, **kwargs: {"queued": 0},
    )

    def fake_monitor_once(called_settings, *, limits):
        assert called_settings == settings
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            with connect(settings.db_path) as conn:
                enqueue(conn, ["offline recovery task"], source="test")
                conn.execute(
                    """
                    UPDATE search_tasks
                    SET status='running', attempts=1, run_owner='offline-run',
                        run_lease_expires_at='2099-01-01T00:00:00+00:00'
                    WHERE keyword='offline recovery task'
                    """
                )
                set_monitor_state(conn, "last_run_id", "offline-run")
            raise RuntimeError("offline injected crash")

        assert scheduler.snapshot()["thread_alive"] is True
        with connect(settings.db_path) as conn:
            task = conn.execute(
                """
                SELECT status, run_owner, run_lease_expires_at, last_error
                FROM search_tasks WHERE keyword='offline recovery task'
                """
            ).fetchone()
            assert task["status"] == "pending"
            assert task["run_owner"] is None
            assert task["run_lease_expires_at"] is None
            assert "offline injected crash" in task["last_error"]
            set_monitor_desired_state(conn, "paused")
        return {
            "run_id": "offline-recovered-run",
            "captured_products": 0,
            "blocked": "offline test complete",
            "busy": False,
        }

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fake_monitor_once)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(
        settings,
        recovery_initial_seconds=2,
        recovery_max_seconds=8,
        max_consecutive_failures=3,
    )
    scheduler._wake = wake
    assert scheduler.start() is True
    scheduler._thread.join(timeout=2)

    assert calls == [1, 2]
    assert wake.waits == [2]
    snapshot = scheduler.snapshot()
    assert snapshot["thread_alive"] is False
    assert snapshot["worker_state"] == "stopped"
    assert snapshot["last_exception"]["type"] == "RuntimeError"
    assert snapshot["last_exception"]["run_id"] == "offline-run"
    assert len(snapshot["last_exception"]["recovered_tasks"]) == 1
    assert snapshot["consecutive_failures"] == 0
    assert snapshot["recovery_count"] == 1
    assert snapshot["next_retry_at"] is None

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
    assert state["scheduler_running"] is False
    assert state["scheduler_consecutive_failures"] == 0
    assert state["scheduler_recovery_count"] == 1
    assert state["last_scheduler_exception"]["type"] == "RuntimeError"


def test_scheduler_pauses_after_finite_exception_budget(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    calls = []
    wake = ImmediateWake()

    monkeypatch.setattr(
        "xhs_scout.scheduler.ensure_portfolio_queue",
        lambda *args, **kwargs: {"queued": 0},
    )

    def always_fail(*args, **kwargs):
        calls.append(len(calls) + 1)
        raise OSError(f"offline failure {len(calls)}")

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", always_fail)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(
        settings,
        recovery_initial_seconds=3,
        recovery_max_seconds=4,
        max_consecutive_failures=2,
    )
    scheduler._wake = wake
    scheduler._run()

    assert calls == [1, 2]
    assert wake.waits == [3]
    snapshot = scheduler.snapshot()
    assert snapshot["worker_state"] == "paused_after_error_budget"
    assert snapshot["consecutive_failures"] == 2
    assert snapshot["recovery_count"] == 1
    assert snapshot["next_retry_at"] is None
    assert snapshot["last_exception"]["message"] == "offline failure 2"

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
    assert state["desired_state"] == "paused"
    assert state["scheduler_running"] is False
    assert state["scheduler_recovery_state"] == "paused_after_error_budget"
    assert state["next_run_at"] is None
    assert state["risk_stop_reason"] is None
    assert state["last_block_reason"] == (
        "scheduler paused after repeated unexpected failures"
    )


def test_scheduler_does_not_clean_another_owner_for_pre_monitor_exception(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    portfolio_calls = []
    wake = ImmediateWake()

    with connect(settings.db_path) as conn:
        enqueue(conn, ["other owner task"], source="test")
        conn.execute(
            """
            UPDATE search_tasks
            SET status='running', attempts=1, run_owner='other-run',
                run_lease_expires_at='2099-01-01T00:00:00+00:00'
            WHERE keyword='other owner task'
            """
        )
        set_monitor_state(conn, "last_run_id", "other-run")
        set_monitor_desired_state(conn, "running")

    def flaky_portfolio(*args, **kwargs):
        portfolio_calls.append(len(portfolio_calls) + 1)
        if len(portfolio_calls) == 1:
            raise RuntimeError("offline portfolio failure")
        return {"queued": 0}

    def finish_without_touching_task(*args, **kwargs):
        with connect(settings.db_path) as conn:
            set_monitor_desired_state(conn, "paused")
        return {
            "run_id": "offline-finish",
            "captured_products": 0,
            "blocked": "offline test complete",
            "busy": False,
        }

    monkeypatch.setattr(
        "xhs_scout.scheduler.ensure_portfolio_queue",
        flaky_portfolio,
    )
    monkeypatch.setattr(
        "xhs_scout.scheduler.monitor_once",
        finish_without_touching_task,
    )

    scheduler = MonitorScheduler(settings, recovery_initial_seconds=1)
    scheduler._wake = wake
    scheduler._run()

    assert portfolio_calls == [1, 2]
    assert wake.waits == [1]
    with connect(settings.db_path) as conn:
        task = conn.execute(
            """
            SELECT status, run_owner, run_lease_expires_at
            FROM search_tasks WHERE keyword='other owner task'
            """
        ).fetchone()
    assert task["status"] == "running"
    assert task["run_owner"] == "other-run"
    assert task["run_lease_expires_at"] == "2099-01-01T00:00:00+00:00"
    assert scheduler.snapshot()["last_exception"]["run_id"] is None
    assert scheduler.snapshot()["last_exception"]["recovered_tasks"] == []


def test_scheduler_never_runs_or_clears_an_active_risk_stop(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)

    def fail_if_monitor_starts(*args, **kwargs):
        raise AssertionError("active risk stop must block scheduler recovery")

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fail_if_monitor_starts)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "desired_state", "running")
        set_monitor_state(conn, "risk_stop_reason", "offline captcha risk")

    scheduler = MonitorScheduler(settings)
    scheduler._run()

    snapshot = scheduler.snapshot()
    assert snapshot["worker_state"] == "risk_paused"
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
    assert state["desired_state"] == "paused"
    assert state["risk_stop_reason"] == "offline captcha risk"
    assert state["scheduler_running"] is False
    assert state["next_run_at"] is None
