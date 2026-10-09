from xhs_scout.config import Settings
from xhs_scout.db import connect, enqueue, get_monitor_state, set_monitor_state
from xhs_scout.device_preflight import CheckStatus, DeviceCheck, DeviceReadiness
from xhs_scout.monitor import MonitorLimits, monitor_once
from xhs_scout.run_control import acquire_monitor_lease


def test_monitor_once_returns_busy_before_touching_device(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        acquire_monitor_lease(conn, owner="existing-run", ttl_seconds=900)

    monkeypatch.setattr(
        "xhs_scout.monitor._device",
        lambda _settings: (_ for _ in ()).throw(AssertionError("device must not be opened")),
    )

    output = monitor_once(
        settings,
        limits=MonitorLimits(max_keywords=1, max_products_per_keyword=1),
        ignore_paused=True,
    )

    assert output["busy"] is True
    assert output["captured_products"] == 0
    assert output["active_lease"]["owner"] == "existing-run"


def test_ignore_paused_does_not_override_risk_stop_or_touch_device(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", "captcha detected")

    monkeypatch.setattr(
        "xhs_scout.monitor._device",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("risk-stopped run must not open the device")
        ),
    )

    output = monitor_once(
        settings,
        limits=MonitorLimits(max_keywords=1, max_products_per_keyword=1),
        ignore_paused=True,
    )

    assert output["blocked"] == "captcha detected"
    assert output["skipped"] == ["risk stop requires explicit resume"]
    with connect(settings.db_path) as conn:
        assert get_monitor_state(conn)["risk_stop_reason"] == "captcha detected"


def test_android_preflight_failure_pauses_before_reserving_task(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["真机预检任务"], source="test")
    monkeypatch.setattr(
        Settings,
        "emulator_config",
        lambda _self: {"backend": "android"},
    )
    device = type("Device", (), {"serial": "phone-mdns"})()
    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor.check_device_readiness",
        lambda _settings, _device: DeviceReadiness(
            serial="phone-mdns",
            checks=(
                DeviceCheck(
                    code="battery_level",
                    status=CheckStatus.HARD_FAILURE,
                    message="battery level must be greater than 30 percent",
                ),
            ),
        ),
    )

    output = monitor_once(
        settings,
        limits=MonitorLimits(max_keywords=1, max_products_per_keyword=1),
        ignore_paused=True,
    )

    assert output["blocked"] == "device preflight failed: battery_level"
    assert output["device_preflight"]["ready"] is False
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE keyword=?",
            ("真机预检任务",),
        ).fetchone()
        state = get_monitor_state(conn)
    assert tuple(task) == ("pending", 0, None)
    assert state["desired_state"] == "paused"
    assert state["risk_stop_reason"] is None
    assert state["last_block_reason"] == "device preflight failed: battery_level"


def test_non_xhs_foreground_failure_does_not_reserve_or_consume_task(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["前台恢复任务"], source="test")
    monkeypatch.setattr(
        Settings,
        "emulator_config",
        lambda _self: {
            "backend": "android",
            "package": "com.xingin.xhs",
        },
    )

    class Device:
        serial = "phone-mdns"

        def window_focus(self):
            return (
                "mCurrentFocus=Window{abc u0 "
                "com.android.settings/com.android.settings.SubSettings}"
            )

    device = Device()
    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor.check_device_readiness",
        lambda _settings, _device: DeviceReadiness(
            serial="phone-mdns",
            checks=(
                DeviceCheck(
                    code="adb_online",
                    status=CheckStatus.PASS,
                    message="online",
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._android_unicode_input_preflight",
        lambda _settings, _device: {"ready": True},
    )
    launched = []
    monkeypatch.setattr(
        "xhs_scout.monitor._launch_xhs",
        lambda _settings, _device, package: launched.append(package),
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "activity": "com.android.settings/com.android.settings.SubSettings",
            "page_kind": "unknown",
            "risk_stop_reason": None,
            "has_anr": False,
            "probe_dir": "settings-probe",
        },
    )

    output = monitor_once(
        settings,
        limits=MonitorLimits(max_keywords=1, max_products_per_keyword=1),
        ignore_paused=True,
    )

    assert launched == ["com.xingin.xhs"]
    assert output["blocked"].startswith(
        "Xiaohongshu foreground preflight failed before task reservation"
    )
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE keyword=?",
            ("前台恢复任务",),
        ).fetchone()
        state = get_monitor_state(conn)
    assert tuple(task) == ("pending", 0, None)
    assert state["desired_state"] == "paused"
    assert state["risk_stop_reason"] is None
