import base64
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from xhs_scout.config import Settings
from xhs_scout.db import connect, enqueue, get_monitor_state
from xhs_scout.device_preflight import CheckStatus, DeviceCheck, DeviceReadiness
from xhs_scout.emulator import AdbDevice
from xhs_scout.monitor import (
    MonitorBlocked,
    MonitorLimits,
    _android_unicode_input_preflight,
    _enter_keyword,
    _exact_top_query_matches,
    _open_search_results,
    monitor_once,
)
from xhs_scout.probe import (
    _classify_global_search_results_ui_tree,
    _classify_product_detail_ui_tree,
)
from xhs_scout.ui_automation import (
    find_product_cards,
    find_search_input_query_text,
    find_top_query_text,
)


SEARCH_INPUT_XML = """<hierarchy>
  <node text="搜索, " content-desc="" class="android.widget.EditText"
        clickable="true" focusable="true" focused="true"
        bounds="[166,89][704,210]" />
  <node text="搜索" content-desc="" class="android.widget.Button"
        clickable="true" focusable="true" bounds="[882,89][1036,210]" />
</hierarchy>"""


def query_xml(value: str) -> str:
    return f"""<hierarchy>
      <node text="{value}" content-desc="" class="android.widget.EditText"
            clickable="true" focusable="true" focused="true"
            bounds="[166,89][704,210]" />
      <node text="搜索" content-desc="" class="android.widget.Button"
            clickable="true" focusable="true" bounds="[882,89][1036,210]" />
    </hierarchy>"""


def query_probe(value: str, *, confidence: float = 0.99) -> dict:
    return {
        "page_kind": "search_input",
        "ocr": [
            {
                "text": value,
                "confidence": confidence,
                "box": [[166, 127], [440, 127], [440, 170], [166, 170]],
            }
        ],
    }


class UnicodeInputDevice:
    def __init__(self, *, readback: str = "奥数资料", fail_input: bool = False):
        self.current_ime = "com.sohu.inputmethod.sogou.xiaomi/.SogouIME"
        self.readback = readback
        self.fail_input = fail_input
        self.actions = []

    def tap(self, x, y):
        self.actions.append(("tap", x, y))

    def default_input_method(self):
        return self.current_ime

    def set_input_method(self, component):
        self.actions.append(("ime", component))
        self.current_ime = component

    def adb_keyboard_clear_text(self):
        self.actions.append(("clear",))

    def adb_keyboard_input_text(self, value):
        self.actions.append(("input", value))
        if self.fail_input:
            raise RuntimeError("broadcast failed")

    def ui_dump(self):
        return query_xml(self.readback)

    def adb_keyboard_submit_search(self):
        self.actions.append(("submit",))


def test_adb_device_encodes_unicode_as_utf8_base64(monkeypatch):
    device = AdbDevice(adb=Path("adb"), serial="phone")
    calls = []
    monkeypatch.setattr(
        device,
        "broadcast",
        lambda action, *, string_extra=None: calls.append((action, string_extra)) or "ok",
    )

    device.adb_keyboard_input_text("奥数资料")

    assert calls == [
        (
            "ADB_INPUT_B64",
            (
                "msg",
                base64.b64encode("奥数资料".encode("utf-8")).decode("ascii"),
            ),
        )
    ]


def test_unicode_entry_verifies_query_before_submit_and_restores_sogou(monkeypatch):
    device = UnicodeInputDevice()
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    result = _enter_keyword(
        device,
        SEARCH_INPUT_XML,
        "奥数资料",
        dry_run=False,
        android_unicode=True,
    )

    assert result["method"] == "adb_keyboard_base64"
    assert result["query_before_submit"] == "奥数资料"
    assert result["query_verified"] is True
    assert ("submit",) in device.actions
    assert device.current_ime == "com.sohu.inputmethod.sogou.xiaomi/.SogouIME"


def test_unicode_entry_uses_fixed_tap_and_screenshot_roi_before_submit(monkeypatch):
    device = UnicodeInputDevice(readback="")
    device.ui_dump = lambda: (_ for _ in ()).throw(
        AssertionError("生产路径不应再依赖输入框XML回读")
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    result = _enter_keyword(
        device,
        SEARCH_INPUT_XML,
        "奥数资料",
        dry_run=False,
        android_unicode=True,
        query_probe=lambda _attempt: query_probe("奥数资料"),
    )

    assert ("tap", 430, 150) in device.actions
    assert result["query_before_submit"] == "奥数资料"
    assert result["query_verification_source"] == "screenshot_fixed_roi"
    assert ("submit",) in device.actions


def test_unicode_entry_fixed_roi_mismatch_stops_before_submit(monkeypatch):
    device = UnicodeInputDevice(readback="")
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    with pytest.raises(MonitorBlocked, match="fixed-ROI query mismatch"):
        _enter_keyword(
            device,
            SEARCH_INPUT_XML,
            "奥数资料",
            dry_run=False,
            android_unicode=True,
            query_probe=lambda _attempt: query_probe("小程序页面设计"),
        )

    assert ("submit",) not in device.actions
    assert device.current_ime == "com.sohu.inputmethod.sogou.xiaomi/.SogouIME"


def test_unicode_entry_polls_real_miui_prefixed_query_until_exact(monkeypatch):
    device = UnicodeInputDevice()
    dumps = iter(
        [
            SEARCH_INPUT_XML,
            query_xml("搜索, 奥数资料"),
        ]
    )
    device.ui_dump = lambda: next(dumps)
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    result = _enter_keyword(
        device,
        SEARCH_INPUT_XML,
        "奥数资料",
        dry_run=False,
        android_unicode=True,
    )

    assert result["query_before_submit"] == "奥数资料"
    assert result["query_read_attempts"] == 2
    assert ("submit",) in device.actions
    assert device.current_ime == "com.sohu.inputmethod.sogou.xiaomi/.SogouIME"


def test_unicode_query_mismatch_stops_before_submit_and_restores_sogou(monkeypatch):
    device = UnicodeInputDevice(readback="手机旧剪贴板内容")
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    with pytest.raises(MonitorBlocked, match="query mismatch before submit"):
        _enter_keyword(
            device,
            SEARCH_INPUT_XML,
            "奥数资料",
            dry_run=False,
            android_unicode=True,
        )

    assert ("submit",) not in device.actions
    assert device.current_ime == "com.sohu.inputmethod.sogou.xiaomi/.SogouIME"


def test_unicode_input_exception_still_restores_sogou(monkeypatch):
    device = UnicodeInputDevice(fail_input=True)
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="broadcast failed"):
        _enter_keyword(
            device,
            SEARCH_INPUT_XML,
            "奥数资料",
            dry_run=False,
            android_unicode=True,
        )

    assert device.current_ime == "com.sohu.inputmethod.sogou.xiaomi/.SogouIME"


def test_unicode_helper_preflight_switches_and_restores_before_reservation(tmp_path):
    settings = Settings.load(tmp_path)
    settings.emulator_config_path.write_text(
        '{"backend":"android","unicode_input_package":"com.android.adbkeyboard",'
        '"unicode_input_ime":"com.android.adbkeyboard/.AdbIME",'
        '"restore_input_ime":"com.sohu.inputmethod.sogou.xiaomi/.SogouIME"}',
        encoding="utf-8",
    )
    device = UnicodeInputDevice()
    device.package_path = lambda _package: "package:/data/app/base.apk"
    device.enabled_input_methods = lambda: (
        "com.sohu.inputmethod.sogou.xiaomi/.SogouIME",
        "com.android.adbkeyboard/.AdbIME",
    )

    result = _android_unicode_input_preflight(settings, device)

    assert result["ready"] is True
    assert result["switch_verified"] is True
    assert result["restore_verified"] is True
    assert device.current_ime == "com.sohu.inputmethod.sogou.xiaomi/.SogouIME"


def test_missing_unicode_helper_fails_before_task_reservation(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as connection:
        enqueue(connection, ["助手缺失任务"], source="test")
    monkeypatch.setattr(Settings, "emulator_config", lambda _self: {"backend": "android"})
    device = SimpleNamespace(serial="phone")
    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor.check_device_readiness",
        lambda _settings, _device: DeviceReadiness(
            serial="phone",
            checks=(DeviceCheck("adb_online", CheckStatus.PASS, "online"),),
        ),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._android_unicode_input_preflight",
        lambda _settings, _device: {
            "ready": False,
            "error": "unicode input helper package is not installed",
        },
    )

    output = monitor_once(settings, limits=MonitorLimits(), ignore_paused=True)

    assert output["blocked"].startswith("unicode input helper preflight failed")
    with connect(settings.db_path) as connection:
        task = connection.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE keyword=?",
            ("助手缺失任务",),
        ).fetchone()
        state = get_monitor_state(connection)
    assert tuple(task) == ("pending", 0, None)
    assert state["desired_state"] == "paused"


def test_post_submit_query_mismatch_stops_before_result_interaction(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "search_input",
                "activity": "com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity",
                "xml": SEARCH_INPUT_XML,
            },
            {
                "page_kind": "search_results",
                "activity": "com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity",
                "xml": query_xml("错误关键词"),
            },
        ]
    )
    monkeypatch.setattr("xhs_scout.monitor.probe_current_page", lambda *_a, **_k: next(probes))
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda probe: probe["xml"])
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "xhs_scout.monitor._enter_keyword",
        lambda *_a, **_k: {"method": "adb_keyboard_base64"},
    )
    monkeypatch.setattr("xhs_scout.monitor.connect", lambda _path: nullcontext(object()))
    monkeypatch.setattr("xhs_scout.monitor.record_run_event", lambda *_a, **_k: None)
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    settings = SimpleNamespace(
        db_path="unused.sqlite3",
        emulator_config=lambda: {"backend": "android"},
    )

    with pytest.raises(MonitorBlocked, match="query mismatch after Unicode submit"):
        _open_search_results(
            settings,
            object(),
            run_id="post-submit-mismatch",
            task={"id": 22, "keyword": "奥数资料"},
            limits=MonitorLimits(wait_seconds=0),
        )


def test_real_global_search_results_xml_with_guide_overlay_replays_safely():
    fixture = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "probes"
        / "monitor-e21561165b70-probe-search-results"
        / "window.xml"
    )
    xml_text = fixture.read_text(encoding="utf-8")
    activity = "com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity"

    assert _classify_global_search_results_ui_tree(activity, xml_text) == "search_results"
    assert _classify_global_search_results_ui_tree("com.xingin.xhs/.IndexActivityV2", xml_text) is None
    assert (
        _classify_global_search_results_ui_tree(
            activity,
            xml_text.replace('text="视频"', 'text="其他"', 1),
        )
        is None
    )


def test_real_post_failure_search_input_xml_reads_exact_prefixed_query():
    fixture = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "probes"
        / "probe-2026-08-09T21-16-13-07-00"
        / "window.xml"
    )

    assert find_search_input_query_text(fixture.read_text(encoding="utf-8")) == "奥数资料"


def test_real_post_submit_search_results_xml_reads_exact_top_query():
    fixture = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "probes"
        / "monitor-f5c35cea68d8-probe-search-results"
        / "window.xml"
    )
    xml_text = fixture.read_text(encoding="utf-8")

    assert find_top_query_text(xml_text) == "奥数资料"
    assert _exact_top_query_matches("奥数资料", xml_text) is True


def test_real_product_tab_xml_finds_visible_card_despite_social_proof_copy():
    fixture = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "probes"
        / "monitor-a8be7b1e2e51-probe-product-tab"
        / "window.xml"
    )

    cards = find_product_cards(fixture.read_text(encoding="utf-8"), limit=3)

    assert len(cards) >= 2
    assert cards[0].bounds.x1 == 13
    assert "已售4313" in cards[0].label
    assert all("加入购物车" not in card.label for card in cards)


def test_real_goods_detail_xml_uses_strict_activity_and_control_shell_fallback():
    fixture = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "probes"
        / "monitor-8b0134de4b35-probe-detail-23"
        / "window.xml"
    )
    xml_text = fixture.read_text(encoding="utf-8")
    activity = (
        "com.xingin.xhs/"
        "com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2"
    )

    assert _classify_product_detail_ui_tree(activity, xml_text) == "product_detail"
    assert _classify_product_detail_ui_tree(
        "com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity",
        xml_text,
    ) is None
    assert _classify_product_detail_ui_tree(
        activity,
        xml_text.replace('text="立即购买"', 'text="查看详情"', 1),
    ) is None
