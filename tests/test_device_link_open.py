from pathlib import Path
import subprocess

import pytest

from xhs_scout.device_link_open import (
    DeviceLinkOpenError,
    configured_online_device,
    open_link_on_configured_device,
)


class _Settings:
    def __init__(self, config):
        self._config = config

    def emulator_config(self):
        return self._config


def test_configured_serial_must_be_online(monkeypatch):
    monkeypatch.setattr("xhs_scout.device_link_open.discover_adb", lambda _value: Path("adb"))
    monkeypatch.setattr(
        "xhs_scout.device_link_open.AdbDevice.devices",
        lambda _self: "List of devices attached\nother device model:Phone\n",
    )

    with pytest.raises(DeviceLinkOpenError) as caught:
        configured_online_device(_Settings({"serial": "wanted"}))

    assert caught.value.code == "configured_device_offline"
    assert caught.value.status_code == 409


def test_model_selection_rejects_non_unique_devices(monkeypatch):
    monkeypatch.setattr("xhs_scout.device_link_open.discover_adb", lambda _value: Path("adb"))
    monkeypatch.setattr(
        "xhs_scout.device_link_open.AdbDevice.devices",
        lambda _self: (
            "List of devices attached\n"
            "one device model:Phone\n"
            "two device model:Phone\n"
        ),
    )

    with pytest.raises(DeviceLinkOpenError) as caught:
        configured_online_device(_Settings({"model": "Phone"}))

    assert caught.value.code == "configured_device_not_unique"


def test_adb_timeout_is_structured(monkeypatch):
    monkeypatch.setattr("xhs_scout.device_link_open.discover_adb", lambda _value: Path("adb"))
    monkeypatch.setattr(
        "xhs_scout.device_link_open.AdbDevice.devices",
        lambda _self: (_ for _ in ()).throw(subprocess.TimeoutExpired("adb", 30)),
    )

    with pytest.raises(DeviceLinkOpenError) as caught:
        configured_online_device(_Settings({"serial": "wanted"}))

    assert caught.value.code == "adb_timeout"
    assert caught.value.status_code == 504


def test_open_link_calls_device_once_without_page_verification(monkeypatch):
    calls = []
    monkeypatch.setattr("xhs_scout.device_link_open.discover_adb", lambda _value: Path("adb"))
    monkeypatch.setattr(
        "xhs_scout.device_link_open.AdbDevice.devices",
        lambda _self: "List of devices attached\nwanted device model:Phone\n",
    )
    monkeypatch.setattr(
        "xhs_scout.device_link_open.AdbDevice.open_url",
        lambda self, url: calls.append((self.serial, url)),
    )

    result = open_link_on_configured_device(
        _Settings({"serial": "wanted"}),
        "xhsdiscover://page/goods/product-1",
    )

    assert calls == [("wanted", "xhsdiscover://page/goods/product-1")]
    assert result == {
        "launched": True,
        "page_verified": False,
        "device_serial": "wanted",
    }
