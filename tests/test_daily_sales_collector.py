from pathlib import Path

import pytest

from xhs_scout.config import Settings
from xhs_scout.daily_sales_collector import (
    DirectLinkDailySalesCollector,
    _device,
    _identity_matches,
)
from xhs_scout.emulator import AdbDevice
from xhs_scout.db import connect


class FakeDevice:
    def __init__(self):
        self.opened = []
        self.back_count = 0

    def open_url(self, url):
        self.opened.append(url)

    def back(self):
        self.back_count += 1


class RecoveringFakeDevice(FakeDevice):
    def __init__(self):
        super().__init__()
        self.recovery_calls = []

    def force_stop(self, package, *, timeout):
        self.recovery_calls.append(("force_stop", package, timeout))

    def launch_with_bluestacks_player(self, player, instance, package):
        self.recovery_calls.append(
            ("launch", str(player), instance, package)
        )

    def launch_android_package(self, package):
        self.recovery_calls.append(("launch_android", package))


def _insert_product(settings, title="普通人社会化成长指南I人社交技巧"):
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO products(title, shop_name, share_url, fingerprint, first_seen_at, last_seen_at)
            VALUES (?, '测试店铺', 'https://www.xiaohongshu.com/goods-detail/abc123', 'daily-test',
                    '2026-07-30T00:00:00+08:00', '2026-07-30T00:00:00+08:00')
            """,
            (title,),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _android_device_settings(monkeypatch, settings, **overrides):
    config = {
        "backend": "android",
        "adb_path": "C:/Android/platform-tools/adb.exe",
        "model": "M2010J19SC",
        "mdns_service": "adb-stable-device",
        **overrides,
    }
    monkeypatch.setattr(Settings, "emulator_config", lambda _self: config)
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.discover_adb",
        lambda _configured=None: Path("C:/Android/platform-tools/adb.exe"),
    )
    return settings


def test_device_selects_already_connected_android_by_model(tmp_path, monkeypatch):
    settings = _android_device_settings(
        monkeypatch,
        Settings.load(tmp_path),
    )
    monkeypatch.setattr(
        AdbDevice,
        "devices",
        lambda _self: (
            "List of devices attached\n"
            "emulator-5554 device product:x model:Rvc64 device:x\n"
            "phone-serial device product:lime model:M2010J19SC device:lime\n"
        ),
    )
    monkeypatch.setattr(
        AdbDevice,
        "mdns_services",
        lambda _self: pytest.fail("already connected device must not use mDNS"),
    )

    device = _device(settings)

    assert device.serial == "phone-serial"


def test_device_prefers_stable_mdns_serial_for_duplicate_same_phone_entries(
    tmp_path, monkeypatch
):
    settings = _android_device_settings(
        monkeypatch,
        Settings.load(tmp_path),
    )
    monkeypatch.setattr(
        AdbDevice,
        "devices",
        lambda _self: (
            "List of devices attached\n"
            "192.168.110.182:43217 device product:lime "
            "model:M2010J19SC device:lime\n"
            "adb-stable-device._adb-tls-connect._tcp device product:lime "
            "model:M2010J19SC device:lime\n"
        ),
    )
    monkeypatch.setattr(
        AdbDevice,
        "mdns_services",
        lambda _self: pytest.fail("stable mDNS serial is already connected"),
    )

    device = _device(settings)

    assert device.serial == "adb-stable-device._adb-tls-connect._tcp"


def test_device_reconnects_stable_mdns_service_then_selects_model(
    tmp_path, monkeypatch
):
    settings = _android_device_settings(
        monkeypatch,
        Settings.load(tmp_path),
    )
    device_outputs = iter(
        [
            "List of devices attached\n",
            (
                "List of devices attached\n"
                "192.168.1.8:45678 device product:lime "
                "model:M2010J19SC device:lime\n"
                "adb-stable-device._adb-tls-connect._tcp device product:lime "
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
            "adb-stable-device _adb-tls-connect._tcp 192.168.1.8:45678\n"
        ),
    )
    monkeypatch.setattr(
        AdbDevice,
        "connect",
        lambda _self, address: connections.append(address),
    )

    device = _device(settings)

    assert connections == ["192.168.1.8:45678"]
    assert device.serial == "adb-stable-device._adb-tls-connect._tcp"


@pytest.mark.parametrize(
    ("overrides", "devices_output", "message"),
    [
        ({"model": ""}, "List of devices attached\n", "必须配置 model"),
        (
            {"mdns_service": ""},
            "List of devices attached\n",
            "未配置 mdns_service",
        ),
    ],
)
def test_device_fails_closed_when_android_identity_config_is_missing(
    tmp_path,
    monkeypatch,
    overrides,
    devices_output,
    message,
):
    settings = _android_device_settings(
        monkeypatch,
        Settings.load(tmp_path),
        **overrides,
    )
    monkeypatch.setattr(AdbDevice, "devices", lambda _self: devices_output)

    with pytest.raises(RuntimeError, match=message):
        _device(settings)


def test_device_fails_closed_when_mdns_service_does_not_match(
    tmp_path, monkeypatch
):
    settings = _android_device_settings(
        monkeypatch,
        Settings.load(tmp_path),
    )
    monkeypatch.setattr(
        AdbDevice,
        "devices",
        lambda _self: "List of devices attached\n",
    )
    monkeypatch.setattr(
        AdbDevice,
        "mdns_services",
        lambda _self: (
            "another-device _adb-tls-connect._tcp 192.168.1.9:40000\n"
        ),
    )

    with pytest.raises(RuntimeError, match="未发现指定的无线调试服务"):
        _device(settings)


def test_device_fails_closed_when_reconnected_device_model_does_not_match(
    tmp_path, monkeypatch
):
    settings = _android_device_settings(
        monkeypatch,
        Settings.load(tmp_path),
    )
    monkeypatch.setattr(
        AdbDevice,
        "devices",
        lambda _self: (
            "List of devices attached\n"
            "other-phone device product:x model:OTHER device:x\n"
        ),
    )
    monkeypatch.setattr(
        AdbDevice,
        "mdns_services",
        lambda _self: (
            "adb-stable-device _adb-tls-connect._tcp 192.168.1.8:45678\n"
        ),
    )
    monkeypatch.setattr(AdbDevice, "connect", lambda _self, _address: None)

    with pytest.raises(RuntimeError, match="未找到已连接的指定安卓设备"):
        _device(settings)


def test_identity_match_accepts_full_title_or_stable_long_prefix():
    title = "普通人社会化成长指南I人社交技巧人情世故保姆级攻略"
    assert _identity_matches(
        expected_title=title,
        observed_title=title,
        page_text=f"¥19.8\n已售19000\n{title}",
    )
    assert _identity_matches(
        expected_title=title,
        observed_title=None,
        page_text="普通人社会化成长指南I人社交技巧\n已售19000",
    )
    assert not _identity_matches(
        expected_title=title,
        observed_title="小学语文暑假衔接讲义",
        page_text="¥19.8\n已售19000\n小学语文暑假衔接讲义",
    )


def test_collector_reads_exact_sales_and_returns_to_previous_page(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    product_id = _insert_product(settings)
    device = FakeDevice()
    monkeypatch.setattr("xhs_scout.daily_sales_collector.time.sleep", lambda _value: None)
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.probe_current_page",
        lambda *_args, **_kwargs: {
            "has_anr": False,
            "risk_stop_reason": None,
            "page_kind": "product_detail",
            "text": "¥19.8\n目前已售 19000\n普通人社会化成长指南I人社交技巧",
            "probe_dir": "offline-probe",
        },
    )

    result = DirectLinkDailySalesCollector(
        settings, device=device, wait_seconds=0
    )(
        product_id=product_id,
        verified_direct_url="xhsdiscover://page/goods/abc123",
    )

    assert result["kind"] == "exact"
    assert result["cumulative_sales_exact"] == 19000
    assert device.opened == ["xhsdiscover://page/goods/abc123"]
    assert device.back_count == 1


def test_collector_hard_stops_without_back_on_unknown_page(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    product_id = _insert_product(settings)
    device = FakeDevice()
    monkeypatch.setattr("xhs_scout.daily_sales_collector.time.sleep", lambda _value: None)
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.probe_current_page",
        lambda *_args, **_kwargs: {
            "has_anr": False,
            "risk_stop_reason": None,
            "page_kind": "home_feed",
            "text": "首页",
        },
    )

    result = DirectLinkDailySalesCollector(
        settings, device=device, wait_seconds=0
    )(
        product_id=product_id,
        verified_direct_url="xhsdiscover://page/goods/abc123",
    )

    assert result["kind"] == "hard_stop"
    assert result["reason_code"] == "unknown_page"
    assert device.back_count == 0


def test_visible_captcha_is_a_batch_hard_stop(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    product_id = _insert_product(settings)
    device = FakeDevice()
    monkeypatch.setattr("xhs_scout.daily_sales_collector.time.sleep", lambda _value: None)
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.probe_current_page",
        lambda *_args, **_kwargs: {
            "has_anr": False,
            "risk_stop_reason": "请完成验证码",
            "page_kind": "risk_stop",
            "text": "请完成验证码",
        },
    )

    result = DirectLinkDailySalesCollector(
        settings, device=device, wait_seconds=0
    )(
        product_id=product_id,
        verified_direct_url="xhsdiscover://page/goods/abc123",
    )

    assert result["kind"] == "hard_stop"
    assert result["reason_code"] == "captcha"
    assert device.back_count == 0


def test_ocr_timeout_is_reported_explicitly_without_guessing_page(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    product_id = _insert_product(settings)
    device = FakeDevice()
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.time.sleep",
        lambda _value: None,
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.probe_current_page",
        lambda *_args, **_kwargs: {
            "has_anr": False,
            "risk_stop_reason": "RapidOCR timed out after 60 seconds",
            "page_kind": "ocr_timeout",
            "text": "",
        },
    )

    result = DirectLinkDailySalesCollector(
        settings,
        device=device,
        wait_seconds=0,
    )(
        product_id=product_id,
        verified_direct_url="xhsdiscover://page/goods/abc123",
    )

    assert result["kind"] == "hard_stop"
    assert result["reason_code"] == "ocr_timeout"
    assert "60 seconds" in result["reason_detail"]
    assert device.back_count == 0


def test_collector_rejects_expiring_short_link_before_opening_device(tmp_path):
    settings = Settings.load(tmp_path)
    product_id = _insert_product(settings)
    device = FakeDevice()

    result = DirectLinkDailySalesCollector(
        settings, device=device, wait_seconds=0
    )(
        product_id=product_id,
        verified_direct_url="https://xhslink.com/m/abc123",
    )

    assert result["kind"] == "hard_stop"
    assert result["reason_code"] == "identity_unknown"
    assert device.opened == []


def test_daily_sales_anr_restarts_app_once_and_retries_same_product(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    monkeypatch.setattr(
        Settings,
        "emulator_config",
        lambda _self: {
            "backend": "bluestacks",
            "package": "com.xingin.xhs",
            "instance": "Rvc64",
        },
    )
    product_id = _insert_product(settings)
    device = RecoveringFakeDevice()
    probes = iter(
        [
            {
                "has_anr": True,
                "risk_stop_reason": None,
                "page_kind": "unknown",
                "text": "小红书没有响应",
            },
            {
                "has_anr": False,
                "risk_stop_reason": None,
                "page_kind": "home_feed",
                "text": "首页",
            },
            {
                "has_anr": False,
                "risk_stop_reason": None,
                "page_kind": "product_detail",
                "text": "目前已售 19000\n普通人社会化成长指南I人社交技巧",
                "probe_dir": "recovered-product-probe",
            },
        ]
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.time.sleep",
        lambda _value: None,
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.discover_bluestacks_player",
        lambda _configured=None: __import__("pathlib").Path(
            "C:/BlueStacks/HD-Player.exe"
        ),
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )

    result = DirectLinkDailySalesCollector(
        settings, device=device, wait_seconds=0
    )(
        product_id=product_id,
        verified_direct_url="xhsdiscover://page/goods/abc123",
    )

    assert result["kind"] == "exact"
    assert result["cumulative_sales_exact"] == 19000
    assert result["app_recovery"]["recovered"] is True
    assert device.opened == [
        "xhsdiscover://page/goods/abc123",
        "xhsdiscover://page/goods/abc123",
    ]
    assert device.recovery_calls == [
        ("force_stop", "com.xingin.xhs", 15),
        (
            "launch",
            "C:\\BlueStacks\\HD-Player.exe",
            "Rvc64",
            "com.xingin.xhs",
        ),
    ]
    assert device.back_count == 1


def test_daily_sales_android_recovery_uses_native_launch_without_bluestacks(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    monkeypatch.setattr(
        Settings,
        "emulator_config",
        lambda _self: {
            "backend": "android",
            "package": "com.xingin.xhs",
        },
    )
    product_id = _insert_product(settings)
    device = RecoveringFakeDevice()
    probes = iter(
        [
            {
                "has_anr": True,
                "risk_stop_reason": None,
                "page_kind": "unknown",
                "text": "小红书没有响应",
            },
            {
                "has_anr": False,
                "risk_stop_reason": None,
                "page_kind": "home_feed",
                "text": "首页",
            },
            {
                "has_anr": False,
                "risk_stop_reason": None,
                "page_kind": "product_detail",
                "text": "目前已售 19000\n普通人社会化成长指南I人社交技巧",
                "probe_dir": "android-recovered-product-probe",
            },
        ]
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.time.sleep",
        lambda _value: None,
    )

    def fail_if_bluestacks_is_discovered(_configured=None):
        raise AssertionError("android recovery must not discover BlueStacks Player")

    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.discover_bluestacks_player",
        fail_if_bluestacks_is_discovered,
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )

    result = DirectLinkDailySalesCollector(
        settings, device=device, wait_seconds=0
    )(
        product_id=product_id,
        verified_direct_url="xhsdiscover://page/goods/abc123",
    )

    assert result["kind"] == "exact"
    assert result["cumulative_sales_exact"] == 19000
    assert result["app_recovery"]["recovered"] is True
    assert device.recovery_calls == [
        ("force_stop", "com.xingin.xhs", 15),
        ("launch_android", "com.xingin.xhs"),
    ]
    assert device.opened == [
        "xhsdiscover://page/goods/abc123",
        "xhsdiscover://page/goods/abc123",
    ]
    assert device.back_count == 1


def test_daily_sales_each_current_anr_restarts_app_and_retries_same_product(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    product_id = _insert_product(settings)
    device = RecoveringFakeDevice()
    probes = iter(
        [
            {
                "has_anr": True,
                "risk_stop_reason": None,
                "page_kind": "unknown",
                "text": "小红书没有响应",
            },
            {
                "has_anr": False,
                "risk_stop_reason": None,
                "page_kind": "home_feed",
                "text": "首页",
            },
            {
                "has_anr": True,
                "risk_stop_reason": None,
                "page_kind": "unknown",
                "text": "小红书没有响应",
            },
            {
                "has_anr": False,
                "risk_stop_reason": None,
                "page_kind": "home_feed",
                "text": "首页",
            },
            {
                "has_anr": False,
                "risk_stop_reason": None,
                "page_kind": "product_detail",
                "text": "目前已售 19000\n普通人社会化成长指南I人社交技巧",
                "probe_dir": "recovered-after-second-anr",
            },
        ]
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.time.sleep",
        lambda _value: None,
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.discover_bluestacks_player",
        lambda _configured=None: __import__("pathlib").Path(
            "C:/BlueStacks/HD-Player.exe"
        ),
    )
    monkeypatch.setattr(
        "xhs_scout.daily_sales_collector.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )

    result = DirectLinkDailySalesCollector(
        settings, device=device, wait_seconds=0
    )(
        product_id=product_id,
        verified_direct_url="xhsdiscover://page/goods/abc123",
    )

    assert result["kind"] == "exact"
    assert result["cumulative_sales_exact"] == 19000
    assert [call[0] for call in device.recovery_calls] == [
        "force_stop",
        "launch",
        "force_stop",
        "launch",
    ]
    assert device.opened == [
        "xhsdiscover://page/goods/abc123",
        "xhsdiscover://page/goods/abc123",
        "xhsdiscover://page/goods/abc123",
    ]
