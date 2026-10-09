from pathlib import Path
import subprocess

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    get_monitor_state,
    set_monitor_desired_state,
    set_monitor_state,
)
from xhs_scout.monitor import (
    AppUnresponsive,
    MonitorLimits,
    _is_adb_timeout,
    _recover_xhs_after_unresponsive,
)


class RecoveryDevice:
    def __init__(self):
        self.calls = []

    def force_stop(self, package, *, timeout):
        self.calls.append(("force_stop", package, timeout))

    def launch_with_bluestacks_player(self, player, instance, package):
        self.calls.append(("launch", str(player), instance, package))


def _prepare_running_state(settings):
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")


def test_adb_timeout_detection_does_not_claim_other_subprocesses():
    assert _is_adb_timeout(
        subprocess.TimeoutExpired(
            ["C:\\Program Files\\BlueStacks_nxt\\HD-Adb.exe", "shell", "input", "tap"],
            30,
        )
    )
    assert not _is_adb_timeout(
        subprocess.TimeoutExpired(["powershell", "-NoProfile"], 10)
    )


def test_one_app_only_recovery_restores_running_state(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    _prepare_running_state(settings)
    device = RecoveryDevice()
    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor.discover_bluestacks_player",
        lambda _configured=None: Path("C:/BlueStacks/HD-Player.exe"),
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "page_kind": "home_feed",
            "has_anr": False,
            "risk_stop_reason": None,
        },
    )

    output = _recover_xhs_after_unresponsive(
        settings,
        run_id="recovery-test",
        limits=MonitorLimits(wait_seconds=0),
        error=AppUnresponsive(),
    )

    assert output["app_recovery"] == {
        "attempted": True,
        "recovered": True,
        "reason": "Xiaohongshu ANR detected",
        "page_kind": "home_feed",
        "resume_after_recovery": True,
    }
    assert "blocked" not in output
    assert device.calls == [
        ("force_stop", "com.xingin.xhs", 15),
        (
            "launch",
            "C:\\BlueStacks\\HD-Player.exe",
            "Rvc64",
            "com.xingin.xhs",
        ),
    ]
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "running"
        assert state["risk_stop_reason"] is None
        assert state["app_recovery_last_result"] == "recovered"


def test_recovery_keeps_a_manually_paused_scheduler_paused(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    device = RecoveryDevice()
    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor.discover_bluestacks_player",
        lambda _configured=None: Path("C:/BlueStacks/HD-Player.exe"),
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "page_kind": "search_input",
            "has_anr": False,
            "risk_stop_reason": None,
        },
    )

    output = _recover_xhs_after_unresponsive(
        settings,
        run_id="paused-recovery-test",
        limits=MonitorLimits(wait_seconds=0),
        error=AppUnresponsive(),
    )

    assert output["app_recovery"]["recovered"] is True
    assert output["app_recovery"]["resume_after_recovery"] is False
    with connect(settings.db_path) as conn:
        assert get_monitor_state(conn)["desired_state"] == "paused"


def test_stale_legacy_recovery_count_does_not_block_current_anr_recovery(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    _prepare_running_state(settings)
    device = RecoveryDevice()
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "app_recovery_consecutive_count", 1)
    monkeypatch.setattr(
        "xhs_scout.monitor._device",
        lambda _settings: device,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.discover_bluestacks_player",
        lambda _configured=None: Path("C:/BlueStacks/HD-Player.exe"),
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "page_kind": "home_feed",
            "has_anr": False,
            "risk_stop_reason": None,
        },
    )

    output = _recover_xhs_after_unresponsive(
        settings,
        run_id="recovery-after-legacy-count-test",
        limits=MonitorLimits(wait_seconds=0),
        error=AppUnresponsive(),
    )

    assert output["app_recovery"]["attempted"] is True
    assert output["app_recovery"]["recovered"] is True
    assert [call[0] for call in device.calls] == ["force_stop", "launch"]
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "running"
        assert state["risk_stop_reason"] is None


def test_unknown_page_after_restart_fails_closed(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    _prepare_running_state(settings)
    device = RecoveryDevice()
    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor.discover_bluestacks_player",
        lambda _configured=None: Path("C:/BlueStacks/HD-Player.exe"),
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "page_kind": "unknown",
            "has_anr": False,
            "risk_stop_reason": None,
        },
    )

    output = _recover_xhs_after_unresponsive(
        settings,
        run_id="unsafe-recovery-test",
        limits=MonitorLimits(wait_seconds=0),
        error=AppUnresponsive(),
    )

    assert "app-only recovery failed" in output["blocked"]
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["app_recovery_last_result"] == "failed"
