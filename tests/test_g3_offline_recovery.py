from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    get_monitor_state,
    set_monitor_desired_state,
)
from xhs_scout.scheduler import MonitorScheduler


class ImmediateWake:
    def __init__(self):
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)
        return False

    def clear(self):
        pass


def test_three_consecutive_failures_use_capped_backoff_then_pause(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    wake = ImmediateWake()
    calls = []

    monkeypatch.setattr(
        "xhs_scout.scheduler.ensure_portfolio_queue",
        lambda *_args, **_kwargs: {"queued": 0},
    )

    def always_fail(*_args, **_kwargs):
        calls.append(len(calls) + 1)
        raise OSError(f"g3 offline failure {len(calls)}")

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", always_fail)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(
        settings,
        recovery_initial_seconds=2,
        recovery_max_seconds=3,
        max_consecutive_failures=3,
    )
    scheduler._wake = wake
    scheduler._run()

    snapshot = scheduler.snapshot()
    assert calls == [1, 2, 3]
    assert wake.waits == [2, 3]
    assert snapshot["worker_state"] == "paused_after_error_budget"
    assert snapshot["consecutive_failures"] == 3
    assert snapshot["recovery_count"] == 2
    assert snapshot["next_retry_at"] is None
    assert snapshot["last_exception"]["message"] == "g3 offline failure 3"

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)

    assert state["desired_state"] == "paused"
    assert state["scheduler_running"] is False
    assert state["scheduler_recovery_state"] == "paused_after_error_budget"
    assert state["scheduler_consecutive_failures"] == 3
    assert state["scheduler_recovery_count"] == 2
    assert state["next_run_at"] is None
    assert state["risk_stop_reason"] is None
    assert state["last_block_reason"] == (
        "scheduler paused after repeated unexpected failures"
    )
