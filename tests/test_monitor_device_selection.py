"""Coverage for xhs_scout.monitor._device: the real device-selection and
stable-mDNS-reconnect path that gates every real scheduler run. Before this
file, this function had zero direct tests -- every other test monkeypatches
``xhs_scout.monitor._device`` away entirely, so a bug here (an unscoped
device fallback, or a broken reconnect) would only ever surface on a real
phone."""

from pathlib import Path

import pytest

from xhs_scout.config import Settings
from xhs_scout.emulator import AdbDevice
from xhs_scout.monitor import _device


def _android_settings(monkeypatch, tmp_path, **overrides) -> Settings:
    settings = Settings.load(tmp_path)
    config = {
        "backend": "android",
        "adb_path": "C:/Android/platform-tools/adb.exe",
        "model": "M2010J19SC",
        "device": "lime",
        "mdns_service": "adb-741da30b0920-cvuER5",
        **overrides,
    }
    monkeypatch.setattr(Settings, "emulator_config", lambda _self: config)
    monkeypatch.setattr(
        "xhs_scout.monitor.discover_adb",
        lambda _configured=None: Path("C:/Android/platform-tools/adb.exe"),
    )
    return settings


def test_device_refuses_an_unscoped_fallback_when_model_is_not_configured(
    tmp_path, monkeypatch
):
    """Regression test: with ``model`` missing/blank, the previous
    implementation's ``if not serial and config.get("model"):`` guard was
    False, so it silently fell through to ``return AdbDevice(adb=adb,
    serial=None)`` -- an *unscoped* device handle that would target whatever
    single device ADB happens to see, violating "never pick an arbitrary
    device"."""

    settings = _android_settings(tmp_path=tmp_path, monkeypatch=monkeypatch, model="")
    monkeypatch.setattr(
        AdbDevice,
        "devices",
        lambda _self: (
            "List of devices attached\n"
            "phone-serial device product:lime model:M2010J19SC device:lime\n"
        ),
    )
    monkeypatch.setattr(
        AdbDevice,
        "mdns_services",
        lambda _self: pytest.fail("must fail closed before touching mDNS"),
    )

    with pytest.raises(RuntimeError, match="model"):
        _device(settings)


def test_device_ignores_stale_offline_ip_and_selects_the_online_mdns_serial(
    tmp_path, monkeypatch
):
    """Real production log observed both a stale offline IP entry and the
    live stable mDNS-derived serial for the same physical phone in one
    ``adb devices -l`` listing; only the online entry may be selected."""

    settings = _android_settings(tmp_path=tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        AdbDevice,
        "devices",
        lambda _self: (
            "List of devices attached\n"
            "192.168.1.119:39325 offline product:lime model:M2010J19SC device:lime\n"
            "adb-741da30b0920-cvuER5._adb-tls-connect._tcp device product:lime "
            "model:M2010J19SC device:lime\n"
        ),
    )
    monkeypatch.setattr(
        AdbDevice,
        "mdns_services",
        lambda _self: pytest.fail("an already-online match must not touch mDNS"),
    )

    device = _device(settings)

    assert device.serial == "adb-741da30b0920-cvuER5._adb-tls-connect._tcp"


def test_device_reconnects_via_stable_mdns_service_when_offline(
    tmp_path, monkeypatch
):
    """When the phone's wireless-debug IP has changed and nothing is online
    yet, resolve the *stable* mdns_service name to its current address,
    connect once, and re-select -- never scan ports, never guess."""

    settings = _android_settings(tmp_path=tmp_path, monkeypatch=monkeypatch)
    device_outputs = iter(
        [
            "List of devices attached\n",
            (
                "List of devices attached\n"
                "adb-741da30b0920-cvuER5._adb-tls-connect._tcp device product:lime "
                "model:M2010J19SC device:lime\n"
            ),
        ]
    )
    connections = []
    monkeypatch.setattr(AdbDevice, "devices", lambda _self: next(device_outputs))
    monkeypatch.setattr(
        AdbDevice,
        "mdns_services",
        lambda _self: (
            "adb-741da30b0920-cvuER5 _adb-tls-connect._tcp 192.168.1.119:39325\n"
        ),
    )
    monkeypatch.setattr(
        AdbDevice, "connect", lambda _self, address: connections.append(address)
    )

    device = _device(settings)

    assert connections == ["192.168.1.119:39325"]
    assert device.serial == "adb-741da30b0920-cvuER5._adb-tls-connect._tcp"


def test_device_fails_closed_without_scanning_when_mdns_has_nothing(
    tmp_path, monkeypatch
):
    """Matches the real production block: ADB list empty and the mDNS
    service no longer advertised. Must fail closed with a clear error, not
    scan ports or silently pick any attached device."""

    settings = _android_settings(tmp_path=tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        AdbDevice, "devices", lambda _self: "List of devices attached\n"
    )
    monkeypatch.setattr(AdbDevice, "mdns_services", lambda _self: "")
    monkeypatch.setattr(
        AdbDevice,
        "connect",
        lambda _self, address: pytest.fail("must not attempt to connect anywhere"),
    )

    with pytest.raises(RuntimeError, match="未发现指定的无线调试服务"):
        _device(settings)
