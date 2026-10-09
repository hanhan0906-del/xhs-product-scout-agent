from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .config import Settings
from .emulator import AdbDevice, discover_adb, select_device_serial


@dataclass(frozen=True)
class DeviceLinkOpenError(RuntimeError):
    code: str
    message: str
    status_code: int

    def __str__(self) -> str:
        return self.message


def _online_serials(devices_output: str) -> list[str]:
    serials: list[str] = []
    for raw_line in devices_output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.rsplit(maxsplit=1)
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
            continue
        marker = " device "
        if marker in line:
            serials.append(line.split(marker, 1)[0])
    return serials


def configured_online_device(settings: Settings) -> AdbDevice:
    config = settings.emulator_config()
    try:
        adb = discover_adb(config.get("adb_path"))
        base_device = AdbDevice(adb=adb)
        devices_output = base_device.devices()
    except FileNotFoundError as exc:
        raise DeviceLinkOpenError("adb_not_found", "未找到配置的 ADB", 503) from exc
    except subprocess.TimeoutExpired as exc:
        raise DeviceLinkOpenError("adb_timeout", "读取设备状态超时", 504) from exc
    except subprocess.CalledProcessError as exc:
        raise DeviceLinkOpenError("adb_failed", "读取设备状态失败", 503) from exc

    configured_serial = str(config.get("serial") or "").strip()
    if configured_serial:
        if _online_serials(devices_output).count(configured_serial) != 1:
            raise DeviceLinkOpenError(
                "configured_device_offline",
                "配置的安卓设备未唯一在线",
                409,
            )
        return AdbDevice(adb=adb, serial=configured_serial)

    model = str(config.get("model") or "").strip()
    if not model:
        raise DeviceLinkOpenError(
            "device_identity_missing",
            "未配置设备 serial 或 model，拒绝盲选设备",
            409,
        )
    try:
        serial = select_device_serial(
            devices_output,
            model=model,
            service_name=str(config.get("mdns_service") or "").strip() or None,
        )
    except RuntimeError as exc:
        raise DeviceLinkOpenError(
            "configured_device_not_unique",
            "配置的安卓设备未唯一在线",
            409,
        ) from exc
    return AdbDevice(adb=adb, serial=serial)


def open_link_on_configured_device(settings: Settings, direct_url: str) -> dict:
    device = configured_online_device(settings)
    try:
        device.open_url(direct_url)
    except subprocess.TimeoutExpired as exc:
        raise DeviceLinkOpenError("device_open_timeout", "手机打开链接超时", 504) from exc
    except subprocess.CalledProcessError as exc:
        raise DeviceLinkOpenError("device_open_failed", "手机打开链接失败", 502) from exc
    except OSError as exc:
        raise DeviceLinkOpenError("device_open_failed", "手机打开链接失败", 503) from exc
    return {
        "launched": True,
        "page_verified": False,
        "device_serial": device.serial,
    }
