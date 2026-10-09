from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from .config import Settings


class CheckStatus(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    HARD_FAILURE = "hard_failure"


@dataclass(frozen=True)
class DeviceCheck:
    code: str
    status: CheckStatus
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status.value,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class DeviceReadiness:
    serial: str | None
    checks: tuple[DeviceCheck, ...]

    @property
    def ready(self) -> bool:
        return not self.hard_failures

    @property
    def hard_failures(self) -> tuple[DeviceCheck, ...]:
        return tuple(
            check for check in self.checks if check.status is CheckStatus.HARD_FAILURE
        )

    @property
    def warnings(self) -> tuple[DeviceCheck, ...]:
        return tuple(check for check in self.checks if check.status is CheckStatus.WARNING)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "serial": self.serial,
            "checks": [check.as_dict() for check in self.checks],
        }


class DeviceProbe(Protocol):
    serial: str | None

    def devices(self) -> str: ...

    def shell(self, *args: str, timeout: int = 15) -> str: ...


_DEPENDENT_CHECKS = (
    "identity_model",
    "identity_device",
    "adb_input",
    "usb_debugging",
    "screen_interactive",
    "screen_unlocked",
    "package_installed",
    "charging",
    "battery_level",
)


def _check(
    code: str,
    status: CheckStatus,
    message: str,
    **details: Any,
) -> DeviceCheck:
    return DeviceCheck(code=code, status=status, message=message, details=details)


def _selected_device_state(devices_output: str, serial: str) -> str | None:
    matches = []
    for line in devices_output.splitlines():
        match = re.match(
            rf"^{re.escape(serial)}\s+(?P<state>\S+)(?:\s+|$)",
            line.strip(),
        )
        if match:
            matches.append(match.group("state"))
    if len(matches) != 1:
        return None
    return matches[0]


def _shell(device: DeviceProbe, *args: str) -> tuple[str | None, str | None]:
    try:
        return device.shell(*args, timeout=15).strip(), None
    except Exception as exc:  # A preflight must turn probe errors into fail-closed results.
        return None, f"{type(exc).__name__}: {exc}"


def _property_check(
    device: DeviceProbe,
    *,
    code: str,
    property_name: str,
    expected: str | None,
) -> DeviceCheck:
    if not expected:
        return _check(
            code,
            CheckStatus.HARD_FAILURE,
            f"expected {property_name} is not configured",
        )
    actual, error = _shell(device, "getprop", property_name)
    if error or not actual:
        return _check(
            code,
            CheckStatus.HARD_FAILURE,
            f"could not confirm {property_name}",
            expected=expected,
            error=error,
        )
    if actual != expected:
        return _check(
            code,
            CheckStatus.HARD_FAILURE,
            f"unexpected {property_name}",
            expected=expected,
            actual=actual,
        )
    return _check(
        code,
        CheckStatus.PASS,
        f"{property_name} matches",
        expected=expected,
        actual=actual,
    )


def _boolean_probe_check(
    *,
    code: str,
    output: str | None,
    error: str | None,
    true_patterns: tuple[str, ...],
    false_patterns: tuple[str, ...],
    pass_message: str,
    failure_message: str,
) -> DeviceCheck:
    if error or output is None:
        return _check(
            code,
            CheckStatus.HARD_FAILURE,
            f"could not confirm {failure_message}",
            error=error,
        )
    true_found = any(re.search(pattern, output, re.IGNORECASE) for pattern in true_patterns)
    false_found = any(re.search(pattern, output, re.IGNORECASE) for pattern in false_patterns)
    if true_found and not false_found:
        return _check(code, CheckStatus.PASS, pass_message)
    if false_found and not true_found:
        return _check(code, CheckStatus.HARD_FAILURE, failure_message)
    return _check(
        code,
        CheckStatus.HARD_FAILURE,
        f"could not unambiguously confirm {failure_message}",
    )


def check_device_readiness(
    settings: Settings,
    device: DeviceProbe,
    *,
    minimum_battery_percent: int = 30,
    recommended_battery_percent: int | None = None,
) -> DeviceReadiness:
    """Probe one explicitly selected Android device without changing its state.

    The caller owns device discovery and wireless mDNS reconnection. This function
    never connects, selects the first listed device, sends input, unlocks the
    screen, launches an app, or changes Android settings.

    External power is informational. Battery readiness is fail-closed and uses
    a strict gate: the reported level must be greater than the configured minimum.
    """

    config = settings.emulator_config()
    serial = str(device.serial).strip() if device.serial else None
    checks: list[DeviceCheck] = []

    if not serial:
        checks.append(
            _check(
                "adb_online",
                CheckStatus.HARD_FAILURE,
                "an explicit device serial is required",
            )
        )
    else:
        try:
            devices_output = device.devices()
            state = _selected_device_state(devices_output, serial)
        except Exception as exc:
            state = None
            devices_output = ""
            error = f"{type(exc).__name__}: {exc}"
        else:
            error = None
        if state == "device":
            checks.append(
                _check(
                    "adb_online",
                    CheckStatus.PASS,
                    "selected ADB device is online",
                    serial=serial,
                )
            )
        else:
            checks.append(
                _check(
                    "adb_online",
                    CheckStatus.HARD_FAILURE,
                    "selected ADB device is absent, ambiguous, or not online",
                    serial=serial,
                    state=state,
                    error=error,
                )
            )

    if checks[-1].status is CheckStatus.HARD_FAILURE:
        checks.extend(
            _check(
                code,
                CheckStatus.WARNING
                if code == "charging"
                else CheckStatus.HARD_FAILURE,
                "check skipped because the selected ADB device is not online",
                **({"required": False} if code == "charging" else {}),
            )
            for code in _DEPENDENT_CHECKS
        )
        return DeviceReadiness(serial=serial, checks=tuple(checks))

    checks.append(
        _property_check(
            device,
            code="identity_model",
            property_name="ro.product.model",
            expected=str(config.get("model") or "").strip() or None,
        )
    )
    checks.append(
        _property_check(
            device,
            code="identity_device",
            property_name="ro.product.device",
            expected=str(config.get("device") or "").strip() or None,
        )
    )

    adb_input, adb_input_error = _shell(device, "getprop", "persist.security.adbinput")
    if adb_input_error or adb_input != "1":
        checks.append(
            _check(
                "adb_input",
                CheckStatus.HARD_FAILURE,
                "ADB input permission is not enabled or could not be confirmed",
                actual=adb_input,
                error=adb_input_error,
            )
        )
    else:
        checks.append(
            _check("adb_input", CheckStatus.PASS, "ADB input permission is enabled")
        )

    adb_enabled, adb_enabled_error = _shell(
        device, "settings", "get", "global", "adb_enabled"
    )
    if adb_enabled_error or adb_enabled != "1":
        checks.append(
            _check(
                "usb_debugging",
                CheckStatus.HARD_FAILURE,
                "Android USB debugging is not enabled or could not be confirmed",
                actual=adb_enabled,
                error=adb_enabled_error,
            )
        )
    else:
        checks.append(
            _check("usb_debugging", CheckStatus.PASS, "Android USB debugging is enabled")
        )

    power_output, power_error = _shell(device, "dumpsys", "power")
    checks.append(
        _boolean_probe_check(
            code="screen_interactive",
            output=power_output,
            error=power_error,
            true_patterns=(r"\bmInteractive\s*=\s*true\b", r"\bmWakefulness\s*=\s*Awake\b"),
            false_patterns=(
                r"\bmInteractive\s*=\s*false\b",
                r"\bmWakefulness\s*=\s*(?:Asleep|Dozing)\b",
            ),
            pass_message="screen is interactive",
            failure_message="screen is interactive",
        )
    )

    policy_output, policy_error = _shell(device, "dumpsys", "window", "policy")
    checks.append(
        _boolean_probe_check(
            code="screen_unlocked",
            output=policy_output,
            error=policy_error,
            true_patterns=(
                r"\bmShowingLockscreen\s*=\s*false\b",
                r"\bisStatusBarKeyguard\s*=\s*false\b",
                r"\bkeyguardShowing\s*=\s*false\b",
                r"\bmIsShowing\s*=\s*false\b",
                r"\bisKeyguardShowing\s*=\s*false\b",
                r"\bmDreamingLockscreen\s*=\s*false\b",
            ),
            false_patterns=(
                r"\bmShowingLockscreen\s*=\s*true\b",
                r"\bisStatusBarKeyguard\s*=\s*true\b",
                r"\bkeyguardShowing\s*=\s*true\b",
                r"\bmIsShowing\s*=\s*true\b",
                r"\bisKeyguardShowing\s*=\s*true\b",
                r"\bmDreamingLockscreen\s*=\s*true\b",
            ),
            pass_message="screen is unlocked",
            failure_message="screen is unlocked",
        )
    )

    package = str(config.get("package") or "com.xingin.xhs").strip()
    package_output, package_error = _shell(device, "pm", "path", package)
    if package_error or not package_output or not any(
        line.startswith("package:") for line in package_output.splitlines()
    ):
        checks.append(
            _check(
                "package_installed",
                CheckStatus.HARD_FAILURE,
                "Xiaohongshu package is not installed or could not be confirmed",
                package=package,
                error=package_error,
            )
        )
    else:
        checks.append(
            _check(
                "package_installed",
                CheckStatus.PASS,
                "Xiaohongshu package is installed",
                package=package,
            )
        )

    battery_output, battery_error = _shell(device, "dumpsys", "battery")
    if battery_error or battery_output is None:
        checks.append(
            _check(
                "charging",
                CheckStatus.WARNING,
                "charging state could not be confirmed; external power is not required",
                required=False,
                error=battery_error,
            )
        )
        checks.append(
            _check(
                "battery_level",
                CheckStatus.HARD_FAILURE,
                (
                    "battery level could not be confirmed; readiness requires "
                    f"level > {minimum_battery_percent}%"
                ),
                minimum_exclusive=minimum_battery_percent,
                required_condition=f"level > {minimum_battery_percent}",
                error=battery_error,
            )
        )
        return DeviceReadiness(serial=serial, checks=tuple(checks))

    powered = bool(
        re.search(
            r"^\s*(?:AC|USB|Wireless|Dock) powered:\s*true\s*$",
            battery_output,
            re.IGNORECASE | re.MULTILINE,
        )
    )
    status_match = re.search(r"^\s*status:\s*(\d+)\s*$", battery_output, re.MULTILINE)
    charging = powered or bool(status_match and status_match.group(1) in {"2", "5"})
    checks.append(
        _check(
            "charging",
            CheckStatus.PASS,
            "device is externally powered"
            if charging
            else "device is on battery power; external power is not required",
            required=False,
            externally_powered=charging,
        )
    )

    level_match = re.search(r"^\s*level:\s*(\d+)\s*$", battery_output, re.MULTILINE)
    if not level_match:
        checks.append(
            _check(
                "battery_level",
                CheckStatus.HARD_FAILURE,
                (
                    "battery level could not be confirmed; readiness requires "
                    f"level > {minimum_battery_percent}%"
                ),
                minimum_exclusive=minimum_battery_percent,
                required_condition=f"level > {minimum_battery_percent}",
            )
        )
    else:
        level = int(level_match.group(1))
        if level <= minimum_battery_percent:
            status = CheckStatus.HARD_FAILURE
            message = (
                "battery level does not satisfy the strict readiness gate: "
                f"level must be > {minimum_battery_percent}%"
            )
        elif (
            recommended_battery_percent is not None
            and level < recommended_battery_percent
        ):
            status = CheckStatus.WARNING
            message = "battery level is below the recommended threshold"
        else:
            status = CheckStatus.PASS
            message = (
                "battery level satisfies the strict readiness gate: "
                f"level > {minimum_battery_percent}%"
            )
        checks.append(
            _check(
                "battery_level",
                status,
                message,
                level=level,
                minimum_exclusive=minimum_battery_percent,
                required_condition=f"level > {minimum_battery_percent}",
                eligible=level > minimum_battery_percent,
                recommended=recommended_battery_percent,
            )
        )

    return DeviceReadiness(serial=serial, checks=tuple(checks))
