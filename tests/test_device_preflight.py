from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from xhs_scout.device_preflight import CheckStatus, check_device_readiness


@dataclass
class FakeDevice:
    serial: str | None = "192.168.110.182:45678"
    state: str = "device"
    responses: dict[tuple[str, ...], str | Exception] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __post_init__(self):
        defaults: dict[tuple[str, ...], str | Exception] = {
            ("getprop", "ro.product.model"): "M2010J19SC\n",
            ("getprop", "ro.product.device"): "lime\n",
            ("getprop", "persist.security.adbinput"): "1\n",
            ("settings", "get", "global", "adb_enabled"): "1\n",
            ("dumpsys", "power"): "mWakefulness=Awake\nmInteractive=true\n",
            ("dumpsys", "window", "policy"): "mShowingLockscreen=false\n",
            ("pm", "path", "com.xingin.xhs"): "package:/data/app/xhs/base.apk\n",
            ("dumpsys", "battery"): (
                "AC powered: false\nUSB powered: true\nWireless powered: false\n"
                "status: 2\nlevel: 80\n"
            ),
        }
        defaults.update(self.responses)
        self.responses = defaults

    def devices(self) -> str:
        if not self.serial:
            return "List of devices attached\n"
        return (
            "List of devices attached\n"
            f"{self.serial}\t{self.state} product:lime model:M2010J19SC device:lime\n"
        )

    def shell(self, *args: str, timeout: int = 15) -> str:
        assert timeout == 15
        self.calls.append(args)
        response = self.responses[args]
        if isinstance(response, Exception):
            raise response
        return response


class FakeSettings:
    def emulator_config(self) -> dict:
        return {
            "model": "M2010J19SC",
            "device": "lime",
            "package": "com.xingin.xhs",
            "mdns_service": "adb-741da30b0920-cvuER5",
        }


def by_code(result, code):
    return next(check for check in result.checks if check.code == code)


def test_ready_device_passes_without_sending_input_or_changing_state():
    device = FakeDevice()

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is True
    assert result.hard_failures == ()
    assert result.warnings == ()
    assert all(check.status is CheckStatus.PASS for check in result.checks)
    assert all(call[:1] != ("input",) for call in device.calls)
    assert all(call[:2] != ("settings", "put") for call in device.calls)


def test_new_mdns_port_is_accepted_when_caller_passes_the_resolved_serial():
    device = FakeDevice(serial="192.168.110.182:59999")

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is True
    assert result.serial == "192.168.110.182:59999"


def test_mdns_serial_with_windows_duplicate_suffix_is_matched_exactly():
    serial = "adb-741da30b0920-cvuER5 (2)._adb-tls-connect._tcp"
    device = FakeDevice(serial=serial)

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is True
    assert result.serial == serial
    assert by_code(result, "adb_online").status is CheckStatus.PASS


def test_missing_explicit_serial_never_falls_back_to_first_device():
    device = FakeDevice(serial=None)

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is False
    assert by_code(result, "adb_online").status is CheckStatus.HARD_FAILURE
    assert device.calls == []


@pytest.mark.parametrize("state", ["offline", "unauthorized"])
def test_disconnected_or_unauthorized_device_fails_closed(state):
    device = FakeDevice(state=state)

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is False
    assert by_code(result, "adb_online").status is CheckStatus.HARD_FAILURE
    assert device.calls == []


@pytest.mark.parametrize(
    ("response_key", "response", "check_code"),
    [
        (("getprop", "ro.product.model"), "unexpected\n", "identity_model"),
        (("getprop", "ro.product.device"), "other\n", "identity_device"),
        (("getprop", "ro.product.model"), "\n", "identity_model"),
        (("getprop", "persist.security.adbinput"), "0\n", "adb_input"),
        (("settings", "get", "global", "adb_enabled"), "0\n", "usb_debugging"),
        (("dumpsys", "power"), "mInteractive=false\n", "screen_interactive"),
        (
            ("dumpsys", "window", "policy"),
            "mShowingLockscreen=true\n",
            "screen_unlocked",
        ),
        (("pm", "path", "com.xingin.xhs"), "\n", "package_installed"),
    ],
)
def test_required_device_conditions_fail_closed(response_key, response, check_code):
    device = FakeDevice(responses={response_key: response})

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is False
    assert by_code(result, check_code).status is CheckStatus.HARD_FAILURE


def test_unknown_lock_state_fails_closed():
    device = FakeDevice(responses={("dumpsys", "window", "policy"): "unknown\n"})

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is False
    assert by_code(result, "screen_unlocked").status is CheckStatus.HARD_FAILURE


def test_miui_keyguard_monitor_reports_unlocked():
    device = FakeDevice(
        responses={
            ("dumpsys", "window", "policy"): """
                KeyguardStateMonitor
                  mIsShowing=false
                mDreamingLockscreen=false
                isKeyguardShowing=false
            """,
        }
    )

    result = check_device_readiness(FakeSettings(), device)

    assert by_code(result, "screen_unlocked").status is CheckStatus.PASS


def test_unplugged_device_at_100_percent_is_ready():
    device = FakeDevice(
        responses={
            ("dumpsys", "battery"): (
                "AC powered: false\nUSB powered: false\nWireless powered: false\n"
                "status: 3\nlevel: 100\n"
            )
        }
    )

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is True
    assert by_code(result, "charging").status is CheckStatus.PASS
    assert by_code(result, "charging").details == {
        "required": False,
        "externally_powered": False,
    }


@pytest.mark.parametrize(
    ("level", "expected_status", "ready"),
    [
        (31, CheckStatus.PASS, True),
        (30, CheckStatus.HARD_FAILURE, False),
        (29, CheckStatus.HARD_FAILURE, False),
    ],
)
def test_unplugged_device_uses_strict_greater_than_30_percent_gate(
    level, expected_status, ready
):
    device = FakeDevice(
        responses={
            ("dumpsys", "battery"): (
                "USB powered: false\nstatus: 3\n" f"level: {level}\n"
            )
        }
    )

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is ready
    battery_check = by_code(result, "battery_level")
    assert battery_check.status is expected_status
    assert battery_check.details["minimum_exclusive"] == 30
    assert battery_check.details["required_condition"] == "level > 30"
    assert battery_check.details["eligible"] is ready
    assert by_code(result, "charging").status is CheckStatus.PASS
    if ready:
        assert result.warnings == ()


@pytest.mark.parametrize(
    "battery_response",
    [
        "USB powered: false\nstatus: 3\n",
        RuntimeError("battery probe failed"),
    ],
)
def test_unreadable_battery_level_fails_closed(battery_response):
    device = FakeDevice(responses={("dumpsys", "battery"): battery_response})

    result = check_device_readiness(FakeSettings(), device)

    battery_check = by_code(result, "battery_level")
    assert result.ready is False
    assert battery_check.status is CheckStatus.HARD_FAILURE
    assert battery_check.details["minimum_exclusive"] == 30
    assert battery_check.details["required_condition"] == "level > 30"
    assert by_code(result, "charging").status is not CheckStatus.HARD_FAILURE


def test_probe_command_error_becomes_hard_failure_instead_of_escaping():
    device = FakeDevice(
        responses={("getprop", "persist.security.adbinput"): RuntimeError("denied")}
    )

    result = check_device_readiness(FakeSettings(), device)

    assert result.ready is False
    assert by_code(result, "adb_input").status is CheckStatus.HARD_FAILURE
    assert "RuntimeError" in str(by_code(result, "adb_input").details["error"])
