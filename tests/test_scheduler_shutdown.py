import threading

from xhs_scout.config import Settings
from xhs_scout.db import connect, get_monitor_state, set_monitor_desired_state
from xhs_scout.scheduler import MonitorScheduler


class ObservedEvent:
    def __init__(self):
        self._event = threading.Event()
        self.waiting = threading.Event()

    def set(self):
        self._event.set()

    def clear(self):
        self._event.clear()

    def wait(self, timeout):
        self.waiting.set()
        return self._event.wait(timeout)


def _running_scheduler(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    calls = []
    round_started = threading.Event()

    def fake_monitor_once(called_settings, *, limits):
        calls.append((called_settings, limits))
        round_started.set()
        return {
            "run_id": f"test-run-{len(calls)}",
            "captured_products": 0,
            "blocked": None,
            "busy": False,
        }

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fake_monitor_once)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(settings)
    wake = ObservedEvent()
    scheduler._wake = wake
    assert scheduler.start() is True
    assert round_started.wait(timeout=2)
    assert wake.waiting.wait(timeout=2)
    return scheduler, settings, calls


def test_stop_exits_while_desired_state_remains_running(tmp_path, monkeypatch):
    scheduler, settings, calls = _running_scheduler(tmp_path, monkeypatch)

    scheduler.stop(timeout=2)

    assert scheduler.snapshot()["thread_alive"] is False
    assert len(calls) == 1
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "running"
        assert state["scheduler_running"] is False
        assert state["next_run_at"] is None


def test_start_after_stop_creates_a_new_running_thread(tmp_path, monkeypatch):
    scheduler, settings, calls = _running_scheduler(tmp_path, monkeypatch)
    scheduler.stop(timeout=2)
    first_thread = scheduler._thread
    second_round_started = threading.Event()

    def stop_after_restart(called_settings, *, limits):
        calls.append((called_settings, limits))
        second_round_started.set()
        return {
            "run_id": "restart-run",
            "captured_products": 0,
            "blocked": "test complete",
            "busy": False,
        }

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", stop_after_restart)

    assert scheduler.start() is True
    assert scheduler._thread is not first_thread
    assert second_round_started.wait(timeout=2)
    scheduler._thread.join(timeout=2)

    assert scheduler.snapshot()["thread_alive"] is False
    assert len(calls) == 2
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "running"
        assert state["scheduler_running"] is False
