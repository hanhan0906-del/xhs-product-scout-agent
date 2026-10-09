from contextlib import nullcontext
import json

from xhs_scout.config import Settings
from xhs_scout.ocr import OcrTimeoutError
from xhs_scout.probe import (
    _classify_page_ui_tree,
    _focused_activity,
    _has_current_anr,
    probe_current_page,
)


def test_current_anr_is_detected_from_visible_dialog_text():
    assert _has_current_anr(
        "mCurrentFocus=Window{123 u0 Application Not Responding: com.xingin.xhs}",
        "小红书没有响应\n关闭应用\n等待",
    )


def test_historical_anr_does_not_block_a_recovered_current_page():
    assert not _has_current_anr(
        (
            "mCurrentFocus=Window{123 u0 "
            "com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity}"
        ),
        "关注\n发现\n视频\n首页\n市集\n消息\n我",
    )


def test_stale_anr_window_is_ignored_when_last_current_focus_is_home():
    window_dump = """
      Window #2 Window{old u0 Application Not Responding: com.xingin.xhs}:
      mCurrentFocus=Window{old u0 Application Not Responding: com.xingin.xhs}
      mCurrentFocus=Window{new u0 com.xingin.xhs/com.xingin.xhs.index.v2.IndexActivityV2}
    """

    assert not _has_current_anr(window_dump, "首页\n市集\n消息\n我")
    assert _focused_activity(window_dump) == (
        "com.xingin.xhs/com.xingin.xhs.index.v2.IndexActivityV2"
    )


class _ProbeDevice:
    def window_focus(self):
        return "mCurrentFocus=Window{abc u0 com.xingin.xhs/.GoodsDetail}"

    def screenshot(self, destination):
        destination.write_bytes(b"screenshot")
        return destination

    def ui_dump(self):
        raise AssertionError("ui_dump must not run")


class _SearchInputProbeDevice(_ProbeDevice):
    def ui_dump(self):
        return """
        <hierarchy>
          <node
            text="搜索, "
            content-desc=""
            class="android.widget.EditText"
            clickable="true"
            bounds="[90,42][913,108]"
          />
        </hierarchy>
        """


def test_probe_can_skip_ui_tree_for_time_bounded_sales_check(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    monkeypatch.setattr(
        "xhs_scout.probe.extract_text",
        lambda _path: ("目前已售 19000\n普通人社会化成长指南", []),
    )
    monkeypatch.setattr(
        "xhs_scout.probe.connect",
        lambda _path: nullcontext(object()),
    )
    monkeypatch.setattr("xhs_scout.probe.record_run_event", lambda *_args, **_kwargs: None)

    result = probe_current_page(
        settings,
        _ProbeDevice(),
        run_id="bounded-sales-probe",
        include_ui_tree=False,
    )

    assert result["ui_dump_ok"] is False
    assert result["ui_error"] is None


def test_ui_tree_recovers_search_input_when_screenshot_ocr_only_sees_bottom_nav():
    ui_tree = """
    <hierarchy>
      <node
        text="搜索, "
        content-desc=""
        class="android.widget.EditText"
        clickable="true"
        bounds="[90,42][913,108]"
      />
    </hierarchy>
    """

    assert _classify_page_ui_tree(ui_tree) == "search_input"


def test_ui_tree_does_not_treat_plain_search_label_as_search_input():
    ui_tree = """
    <hierarchy>
      <node
        text="搜索"
        content-desc=""
        class="android.widget.TextView"
        clickable="true"
        bounds="[90,42][913,108]"
      />
    </hierarchy>
    """

    assert _classify_page_ui_tree(ui_tree) is None


def test_probe_uses_ui_tree_search_input_fallback_when_ocr_misses_header(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    monkeypatch.setattr(
        "xhs_scout.probe.extract_text",
        lambda _path: ("首页\n市集\n+\n消息\n我", []),
    )
    monkeypatch.setattr(
        "xhs_scout.probe.connect",
        lambda _path: nullcontext(object()),
    )
    monkeypatch.setattr("xhs_scout.probe.record_run_event", lambda *_args, **_kwargs: None)

    result = probe_current_page(
        settings,
        _SearchInputProbeDevice(),
        run_id="search-input-ui-fallback",
    )

    assert result["page_kind"] == "search_input"
    assert result["ui_dump_ok"] is True


def test_probe_preserves_timeout_evidence_without_waiting_for_ui_tree(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    monkeypatch.setattr(
        "xhs_scout.probe.extract_text",
        lambda _path: (_ for _ in ()).throw(
            OcrTimeoutError("RapidOCR timed out after 60 seconds")
        ),
    )
    monkeypatch.setattr(
        "xhs_scout.probe.connect",
        lambda _path: nullcontext(object()),
    )
    monkeypatch.setattr(
        "xhs_scout.probe.record_run_event",
        lambda *_args, **_kwargs: None,
    )

    result = probe_current_page(
        settings,
        _ProbeDevice(),
        run_id="ocr-timeout-probe",
    )

    probe_dir = settings.data_dir / "probes" / "ocr-timeout-probe"
    recorded = json.loads((probe_dir / "probe.json").read_text(encoding="utf-8"))
    assert result["page_kind"] == "ocr_timeout"
    assert result["ocr_timeout"] is True
    assert result["risk_stop_reason"] == "RapidOCR timed out after 60 seconds"
    assert recorded["ocr_error"] == result["ocr_error"]
    assert (probe_dir / "current.png").exists()
    assert (probe_dir / "window.txt").exists()
