from xhs_scout.monitor import _resolve_search_entry
from xhs_scout.ui_automation import Bounds, UiTarget


def _visual_target():
    return UiTarget(
        x=1000,
        y=136,
        bounds=Bounds(983, 119, 1017, 153),
        label="首页搜索",
        reason="home-search-visual-icon",
    )


def test_visual_home_search_fallback_requires_verified_home_activity(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "xhs_scout.monitor.find_home_search_icon",
        lambda screenshot: calls.append(screenshot) or _visual_target(),
    )
    probe = {
        "page_kind": "home_feed",
        "activity": "com.xingin.xhs.index.v2.IndexActivityV2",
        "screenshot": "home.png",
    }

    target, event = _resolve_search_entry(probe, "<hierarchy />")

    assert target == _visual_target()
    assert event == "tap_home_search_visual_icon"
    assert calls == ["home.png"]


def test_visual_home_search_fallback_is_not_used_on_unknown_activity(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "xhs_scout.monitor.find_home_search_icon",
        lambda screenshot: calls.append(screenshot) or _visual_target(),
    )
    probe = {
        "page_kind": "home_feed",
        "activity": "com.example.UnknownActivity",
        "screenshot": "home.png",
    }

    target, event = _resolve_search_entry(probe, "<hierarchy />")

    assert target is None
    assert event == "tap_home_search_entry"
    assert calls == []


def test_xml_semantic_home_search_remains_preferred(monkeypatch):
    monkeypatch.setattr(
        "xhs_scout.monitor.find_home_search_icon",
        lambda _screenshot: (_ for _ in ()).throw(AssertionError("visual fallback used")),
    )
    probe = {
        "page_kind": "home_feed",
        "activity": "com.xingin.xhs.index.v2.IndexActivityV2",
        "screenshot": "home.png",
    }
    xml = (
        '<hierarchy><node text="" content-desc="搜索" clickable="true" '
        'bounds="[900,42][970,92]" /></hierarchy>'
    )

    target, event = _resolve_search_entry(probe, xml)

    assert target is not None
    assert event == "tap_home_search_button"
    assert target.reason == "home-search-button"
