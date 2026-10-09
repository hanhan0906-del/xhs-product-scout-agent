import inspect
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from xhs_scout.config import Settings
from xhs_scout.monitor import (
    AppUnresponsive,
    MonitorLimits,
    _fixed_search_query_from_probe,
    _is_home_feed_misclassified_as_search_results,
    _is_transient_open_probe,
    _keyword_matches_search_page,
    _locate_ranked_product_card,
    _normalize_expected_search_results,
    _open_search_results,
    _open_search_input_from_result_page,
    _probe_search_input_after_entry,
    _select_product_card,
)
from xhs_scout.ui_automation import Bounds, UiTarget


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ocr_detail(
    text: str,
    *,
    left: float = 166.4,
    top: float = 127.4,
    right: float = 440.0,
    bottom: float = 169.8,
    confidence: float = 0.995,
) -> dict:
    return {
        "text": text,
        "confidence": confidence,
        "box": [[left, top], [right, top], [right, bottom], [left, bottom]],
    }


def test_keyword_match_uses_fixed_search_box_ocr_not_result_body():
    probe = {
        "ocr": [
            _ocr_detail("仿写训练"),
            _ocr_detail(
                "高考英语阅读理解解题技巧",
                left=40,
                top=350,
                right=500,
                bottom=410,
            ),
        ]
    }
    assert _keyword_matches_search_page("仿写训练", probe, "<hierarchy />") is True
    assert _keyword_matches_search_page("阅读理解", probe, "<hierarchy />") is False


def test_keyword_match_is_conservative_without_query_evidence():
    probe = {"text": "商品\n高考英语阅读理解解题技巧"}
    assert _keyword_matches_search_page("阅读理解", probe, "<hierarchy />") is False


def test_fixed_search_query_fails_closed_when_roi_is_ambiguous_or_low_confidence():
    ambiguous = {"ocr": [_ocr_detail("开学第一课PPT"), _ocr_detail("商品标题")]}
    low_confidence = {"ocr": [_ocr_detail("开学第一课PPT", confidence=0.79)]}

    assert _fixed_search_query_from_probe(ambiguous) is None
    assert _fixed_search_query_from_probe(low_confidence) is None


def test_real_before_and_after_scroll_probes_keep_the_same_fixed_query():
    probe_dirs = [
        "monitor-1d7b46b56687-probe-start",
        "monitor-1d7b46b56687-probe-result-scroll-1",
    ]
    for directory in probe_dirs:
        root = PROJECT_ROOT / "data" / "probes" / directory
        probe = json.loads((root / "probe.json").read_text(encoding="utf-8"))
        xml = (root / "window.xml").read_text(encoding="utf-8")

        assert _fixed_search_query_from_probe(probe) == "开学第一课PPT"
        assert _keyword_matches_search_page("开学第一课PPT", probe, xml)
        assert not _keyword_matches_search_page("班级管理手册", probe, xml)


def test_splash_screen_is_treated_as_transient_open():
    assert _is_transient_open_probe(
        {
            "page_kind": "unknown",
            "activity": None,
            "ocr_count": 2,
            "text": "小红书\n你的生活兴趣社区",
        }
    )


def test_index_home_feed_is_not_treated_as_search_results():
    probe = {
        "page_kind": "search_results",
        "activity": "com.xingin.xhs/com.xingin.xhs.index.v2.IndexActivityV2",
    }
    xml = """<hierarchy>
      <node class="android.widget.TextView" text="搜索笔记，用户和商品" content-desc=""
            clickable="true" focusable="true" bounds="[756,42][1056,87]" />
      <node text="首页" content-desc="首页" clickable="true"
            selected="true" bounds="[0,1852][216,1920]" />
    </hierarchy>"""

    assert _is_home_feed_misclassified_as_search_results(probe, xml) is True
    assert (
        _is_home_feed_misclassified_as_search_results(
            {**probe, "activity": "com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity"},
            xml,
        )
        is False
    )


def test_search_result_rank_does_not_wrap_to_an_earlier_visible_card():
    cards = [
        UiTarget(50, 50, Bounds(0, 0, 100, 100), "商品一", "test"),
        UiTarget(50, 150, Bounds(0, 100, 100, 200), "商品二", "test"),
        UiTarget(50, 250, Bounds(0, 200, 100, 300), "商品三", "test"),
    ]

    selected, rank = _select_product_card(cards, 2)
    missing, missing_rank = _select_product_card(cards, 5)

    assert selected.label == "商品二"
    assert rank == 2
    assert missing is None
    assert missing_rank is None
    assert not _is_transient_open_probe(
        {
            "page_kind": "product_detail",
            "activity": "GoodsDetailActivityV2",
            "ocr_count": 20,
            "text": "立即购买",
        }
    )


def test_locate_fifth_product_scrolls_and_deduplicates_overlap(tmp_path, monkeypatch):
    def result_xml(names):
        rows = []
        for index, name in enumerate(names):
            y1 = 360 + index * 420
            y2 = y1 + 360
            rows.append(
                f'''<node text="" content-desc="" clickable="true"
                    bounds="[20,{y1}][520,{y2}]">
                    <node text="{name}开学资料完整商品标题" clickable="false"
                          bounds="[40,{y1 + 20}][500,{y1 + 100}]" />
                    <node text="￥12.9" clickable="false"
                          bounds="[40,{y1 + 120}][180,{y1 + 180}]" />
                </node>'''
            )
        return "<hierarchy>" + "".join(rows) + "</hierarchy>"

    initial_xml = result_xml(["商品一", "商品二", "商品三"])
    scrolled_xml = result_xml(["商品三", "商品四", "商品五"])
    swipes = []

    class Device:
        def swipe(self, *args):
            swipes.append(args)

    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_a, **_k: {"page_kind": "search_results", "text": "开学第一课PPT\n搜索"},
    )
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", lambda *_a, **_k: None)
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda *_a, **_k: scrolled_xml)
    monkeypatch.setattr(
        "xhs_scout.monitor._keyword_matches_search_page", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.connect", lambda *_a, **_k: nullcontext(SimpleNamespace())
    )
    monkeypatch.setattr("xhs_scout.monitor.record_run_event", lambda *_a, **_k: None)

    cards, selected, rank, _page = _locate_ranked_product_card(
        Settings.load(tmp_path),
        Device(),
        run_id="test-run",
        task_id=1,
        keyword="开学第一课PPT",
        result_page={"xml": initial_xml, "probe": {"page_kind": "search_results"}},
        limits=MonitorLimits(
            search_result_rank=5,
            search_card_scan_limit=5,
            wait_seconds=0,
        ),
    )

    assert len(cards) == 5
    assert rank == 5
    assert selected is not None and "商品五" in selected.label
    assert len(swipes) == 1


def test_locate_fifth_product_calls_probe_current_page_with_real_signature(
    tmp_path, monkeypatch
):
    """Regression test for a scroll-branch call that used a non-existent
    ``label=`` kwarg instead of the real ``probe_current_page(settings,
    device, *, run_id=...)`` signature; a lenient ``lambda *a, **k`` mock
    never caught it."""

    def result_xml(names):
        rows = []
        for index, name in enumerate(names):
            y1 = 360 + index * 420
            y2 = y1 + 360
            rows.append(
                f'''<node text="" content-desc="" clickable="true"
                    bounds="[20,{y1}][520,{y2}]">
                    <node text="{name}开学资料完整商品标题" clickable="false"
                          bounds="[40,{y1 + 20}][500,{y1 + 100}]" />
                    <node text="￥12.9" clickable="false"
                          bounds="[40,{y1 + 120}][180,{y1 + 180}]" />
                </node>'''
            )
        return "<hierarchy>" + "".join(rows) + "</hierarchy>"

    initial_xml = result_xml(["商品一", "商品二", "商品三"])
    scrolled_xml = result_xml(["商品三", "商品四", "商品五"])

    class Device:
        def swipe(self, *args):
            pass

    device = Device()
    calls = []

    import xhs_scout.monitor as monitor_module
    import xhs_scout.probe as probe_module

    probe_signature = inspect.signature(probe_module.probe_current_page)
    guard_signature = inspect.signature(monitor_module._guard_probe)
    guard_calls = []

    def strict_probe_current_page(*args, **kwargs):
        bound = probe_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        assert bound.arguments["device"] is device
        assert "run_id" in kwargs
        assert "label" not in kwargs
        calls.append(kwargs["run_id"])
        return {"page_kind": "search_results", "text": "开学第一课PPT\n搜索"}

    def strict_guard_probe(*args, **kwargs):
        bound = guard_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        assert bound.arguments["device"] is device
        assert "expected" not in kwargs
        guard_calls.append(bound.arguments["run_id"])

    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page", strict_probe_current_page
    )
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", strict_guard_probe)
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda *_a, **_k: scrolled_xml)
    monkeypatch.setattr(
        "xhs_scout.monitor._keyword_matches_search_page", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.connect", lambda *_a, **_k: nullcontext(SimpleNamespace())
    )
    monkeypatch.setattr("xhs_scout.monitor.record_run_event", lambda *_a, **_k: None)

    cards, selected, rank, _page = _locate_ranked_product_card(
        Settings.load(tmp_path),
        device,
        run_id="test-run",
        task_id=1,
        keyword="开学第一课PPT",
        result_page={"xml": initial_xml, "probe": {"page_kind": "search_results"}},
        limits=MonitorLimits(
            search_result_rank=5,
            search_card_scan_limit=5,
            wait_seconds=0,
        ),
    )

    assert len(cards) == 5
    assert rank == 5
    assert selected is not None and "商品五" in selected.label
    assert calls == ["test-run-probe-result-scroll-1"]
    assert guard_calls == ["test-run"]


def test_locate_product_retries_a_transient_empty_ui_dump(
    tmp_path, monkeypatch
):
    """真实故障回归：商品分类页 OCR 正常，但首次 uiautomator dump 为空。

    空的 ``window.xml`` 不能直接交给 ElementTree 造成 HTTP 500；应在当前
    页面做一次轻量 UI dump 重抓，再继续定位商品卡。
    """

    recovered_xml = """<hierarchy>
        <node text="" content-desc="" clickable="true"
              bounds="[20,360][520,720]">
            <node text="开学第一课PPT完整商品标题" clickable="false"
                  bounds="[40,380][500,460]" />
            <node text="￥12.9" clickable="false"
                  bounds="[40,500][180,560]" />
        </node>
    </hierarchy>"""
    probe_dir = tmp_path / "empty-product-tab-probe"
    probe_dir.mkdir()
    (probe_dir / "window.xml").write_text("", encoding="utf-8")

    class Device:
        def __init__(self):
            self.ui_dump_calls = 0

        def ui_dump(self):
            self.ui_dump_calls += 1
            return recovered_xml

    device = Device()
    events = []
    monkeypatch.setattr(
        "xhs_scout.monitor.connect", lambda *_a, **_k: nullcontext(SimpleNamespace())
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.record_run_event",
        lambda *_a, **kwargs: events.append(kwargs),
    )

    cards, selected, rank, page = _locate_ranked_product_card(
        Settings.load(tmp_path),
        device,
        run_id="empty-ui-run",
        task_id=1,
        keyword="开学第一课PPT",
        result_page={
            "xml": "",
            "probe": {
                "probe_dir": str(probe_dir),
                "page_kind": "search_results",
                "activity": "com.xingin.xhs.activity.GlobalSearchActivity",
            },
        },
        limits=MonitorLimits(search_result_rank=1, search_card_scan_limit=5),
    )

    assert device.ui_dump_calls == 1
    assert len(cards) == 1
    assert rank == 1
    assert selected is not None and "开学第一课PPT" in selected.label
    assert page["xml"] == recovered_xml
    assert (probe_dir / "window.xml").read_text(encoding="utf-8") == recovered_xml
    assert events[-1]["event"] == "ui_tree_retry_recovered"


def test_real_rank4_scroll_accepts_fixed_query_when_page_classifier_is_unknown(
    tmp_path, monkeypatch
):
    initial_root = (
        PROJECT_ROOT
        / "data"
        / "probes"
        / "monitor-d2550d932da1-probe-product-tab"
    )
    scrolled_root = (
        PROJECT_ROOT
        / "data"
        / "probes"
        / "monitor-d2550d932da1-probe-result-scroll-1"
    )
    initial_probe = json.loads(
        (initial_root / "probe.json").read_text(encoding="utf-8")
    )
    scrolled_probe = json.loads(
        (scrolled_root / "probe.json").read_text(encoding="utf-8")
    )
    initial_xml = (initial_root / "window.xml").read_text(encoding="utf-8")
    scrolled_xml = (scrolled_root / "window.xml").read_text(encoding="utf-8")
    assert scrolled_probe["page_kind"] == "unknown"

    class Device:
        def swipe(self, *_args):
            pass

    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page", lambda *_a, **_k: scrolled_probe
    )
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", lambda *_a, **_k: None)
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda *_a, **_k: scrolled_xml)
    monkeypatch.setattr(
        "xhs_scout.monitor.connect", lambda *_a, **_k: nullcontext(SimpleNamespace())
    )
    monkeypatch.setattr("xhs_scout.monitor.record_run_event", lambda *_a, **_k: None)

    cards, selected, rank, page = _locate_ranked_product_card(
        Settings.load(tmp_path),
        Device(),
        run_id="real-rank4-replay",
        task_id=185,
        keyword="开学第一课PPT",
        result_page={"xml": initial_xml, "probe": initial_probe},
        limits=MonitorLimits(
            search_result_rank=4,
            search_card_scan_limit=5,
            wait_seconds=0,
        ),
    )

    assert len(cards) >= 4
    assert rank == 4
    assert selected is not None
    assert "2026秋开学第一课" in selected.label
    assert page["probe"]["page_kind"] == "search_results"
    assert page["probe"]["page_kind_source"] == "fixed_search_query"


def test_real_next_round_reuses_matching_search_results_when_classifier_is_unknown(
    tmp_path, monkeypatch
):
    root = (
        PROJECT_ROOT
        / "data"
        / "probes"
        / "monitor-07239fc78493-probe-start"
    )
    probe = json.loads((root / "probe.json").read_text(encoding="utf-8"))
    xml = (root / "window.xml").read_text(encoding="utf-8")
    assert probe["page_kind"] == "unknown"

    events = []
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page", lambda *_a, **_k: probe
    )
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", lambda *_a, **_k: None)
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda *_a, **_k: xml)
    monkeypatch.setattr("xhs_scout.monitor.find_product_tab", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "xhs_scout.monitor._resolve_search_entry",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("正确搜索结果页不应再寻找首页搜索按钮")
        ),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.connect", lambda *_a, **_k: nullcontext(SimpleNamespace())
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.record_run_event",
        lambda *_a, **kwargs: events.append(kwargs.get("event")),
    )

    result = _open_search_results(
        Settings.load(tmp_path),
        SimpleNamespace(),
        run_id="real-next-round-replay",
        task={"id": 186, "keyword": "开学第一课PPT"},
        limits=MonitorLimits(wait_seconds=0, dry_run=True),
    )

    assert result["probe"]["page_kind"] == "search_results"
    assert result["probe"]["page_kind_source"] == "fixed_search_query"
    assert "round_start_search_context_reused" in events


def test_real_next_keyword_normalizes_old_query_results_before_reset():
    """真实自动换词故障：旧词结果页必须先认成结果页，再走改词分支。

    旧实现只有搜索框恰好等于新任务词时才归一页面；当task154要从
    “开学第一课PPT”切到“收心主题班会”时，页面保持unknown并错误寻找
    首页搜索按钮。
    """

    root = (
        PROJECT_ROOT
        / "data"
        / "probes"
        / "monitor-eaf3cdfd9d3c-probe-start"
    )
    probe = json.loads((root / "probe.json").read_text(encoding="utf-8"))
    xml = (root / "window.xml").read_text(encoding="utf-8")
    assert probe["page_kind"] == "unknown"
    assert _fixed_search_query_from_probe(probe) == "开学第一课PPT"

    normalized, reused = _normalize_expected_search_results(
        "收心主题班会", probe, xml
    )

    assert normalized["page_kind"] == "search_results"
    assert normalized["page_kind_source"] == "fixed_search_query"
    assert reused is False


def test_real_unknown_note_activity_backs_to_matching_search_results(
    tmp_path, monkeypatch
):
    note_root = (
        PROJECT_ROOT
        / "data"
        / "probes"
        / "monitor-d2acc101c016-probe-start"
    )
    search_root = (
        PROJECT_ROOT
        / "data"
        / "probes"
        / "monitor-07239fc78493-probe-start"
    )
    note_probe = json.loads((note_root / "probe.json").read_text(encoding="utf-8"))
    search_probe = json.loads(
        (search_root / "probe.json").read_text(encoding="utf-8")
    )
    note_xml = (note_root / "window.xml").read_text(encoding="utf-8")
    search_xml = (search_root / "window.xml").read_text(encoding="utf-8")
    assert note_probe["page_kind"] == "unknown"
    assert "NoteDetailActivity" in note_probe["activity"]

    probes = iter([note_probe, search_probe])
    back_calls = []

    class Device:
        def back(self):
            back_calls.append(True)

    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page", lambda *_a, **_k: next(probes)
    )
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "xhs_scout.monitor._read_ui",
        lambda probe: note_xml if probe is note_probe else search_xml,
    )
    monkeypatch.setattr("xhs_scout.monitor.find_product_tab", lambda *_a, **_k: None)
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "xhs_scout.monitor._resolve_search_entry",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("笔记页应先返回搜索结果，不应寻找首页搜索按钮")
        ),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.connect", lambda *_a, **_k: nullcontext(SimpleNamespace())
    )
    monkeypatch.setattr("xhs_scout.monitor.record_run_event", lambda *_a, **_k: None)

    result = _open_search_results(
        Settings.load(tmp_path),
        Device(),
        run_id="real-note-recovery-replay",
        task={"id": 186, "keyword": "开学第一课PPT"},
        limits=MonitorLimits(wait_seconds=0, dry_run=False),
    )

    assert len(back_calls) == 1
    assert result["probe"]["page_kind"] == "search_results"


def test_marketplace_result_reset_taps_top_query_without_back(monkeypatch):
    actions = []

    class Device:
        def tap(self, x, y):
            actions.append(("tap", x, y))

        def back(self):
            actions.append(("back",))

    xml = """<hierarchy>
      <node text="旧搜索词" content-desc="" clickable="true" focusable="true"
            bounds="[36,42][1038,108]" />
      <node text="" content-desc="全部删除" clickable="true"
            bounds="[924,60][954,90]" />
    </hierarchy>"""
    monkeypatch.setattr("xhs_scout.monitor.connect", lambda _path: nullcontext(object()))
    monkeypatch.setattr("xhs_scout.monitor.record_run_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "page_kind": "search_input",
            "activity": "com.xingin.xhs/.index.v2.IndexActivityV2",
        },
    )
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda _probe: "<hierarchy />")
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    probe, returned_xml = _open_search_input_from_result_page(
        settings=SimpleNamespace(db_path="unused.sqlite3"),
        device=Device(),
        run_id="marketplace-reset",
        task_id=89,
        xml_text=xml,
        limits=MonitorLimits(wait_seconds=0),
        try_back_first=False,
    )

    assert probe["page_kind"] == "search_input"
    assert returned_xml == "<hierarchy />"
    assert actions == [("tap", 537, 75)]


def test_search_entry_waits_for_transient_empty_page(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "unknown",
                "activity": None,
                "ocr_count": 0,
                "text": "",
                "has_anr": False,
            },
            {
                "page_kind": "search_input",
                "activity": "com.xingin.xhs/.search.GlobalSearchActivity",
                "ocr_count": 8,
                "text": "搜索",
                "has_anr": False,
            },
        ]
    )
    events = []
    monkeypatch.setattr("xhs_scout.monitor.connect", lambda _path: nullcontext(object()))
    monkeypatch.setattr(
        "xhs_scout.monitor.record_run_event",
        lambda *_args, **kwargs: events.append(kwargs["event"]),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    probe = _probe_search_input_after_entry(
        settings=SimpleNamespace(db_path="unused.sqlite3"),
        device=object(),
        run_id="search-entry-transient",
        task_id=96,
        limits=MonitorLimits(wait_seconds=0),
    )

    assert probe["page_kind"] == "search_input"
    assert events == ["wait_transient_search_entry"]


def test_search_entry_stops_when_anr_appears_during_transient_wait(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "unknown",
                "activity": None,
                "ocr_count": 0,
                "text": "",
                "has_anr": False,
            },
            {
                "page_kind": "unknown",
                "activity": None,
                "ocr_count": 0,
                "text": "小红书没有响应",
                "has_anr": True,
            },
        ]
    )
    monkeypatch.setattr("xhs_scout.monitor.connect", lambda _path: nullcontext(object()))
    monkeypatch.setattr("xhs_scout.monitor.record_run_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    try:
        _probe_search_input_after_entry(
            settings=SimpleNamespace(db_path="unused.sqlite3"),
            device=object(),
            run_id="search-entry-anr",
            task_id=96,
            limits=MonitorLimits(wait_seconds=0),
        )
    except AppUnresponsive:
        pass
    else:
        raise AssertionError("ANR must stop the search-entry flow")
