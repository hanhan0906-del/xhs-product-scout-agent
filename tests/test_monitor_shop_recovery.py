from types import SimpleNamespace

import pytest

from xhs_scout.coupon_overlay import coupon_overlay_text_present
from xhs_scout.monitor import (
    CouponOverlayHardStop,
    _close_visual_coupon_overlay_once,
    _should_back_recover_from_shop_list,
)
from xhs_scout.ui_automation import Bounds, UiTarget


def test_real_shop_detail_page_uses_one_back_recovery():
    assert _should_back_recover_from_shop_list(
        {
            "page_kind": "shop_product_list",
            "activity": (
                "com.xingin.xhs/"
                "com.xingin.commercial.shoppage.ShopDetailActivity"
            ),
        }
    )


def test_search_results_misclassified_as_shop_list_does_not_go_back():
    assert not _should_back_recover_from_shop_list(
        {
            "page_kind": "shop_product_list",
            "activity": (
                "com.xingin.xhs/"
                "com.xingin.alioth.search.GlobalSearchActivity"
            ),
        }
    )


def test_unknown_shop_like_page_fails_closed_without_back():
    assert not _should_back_recover_from_shop_list(
        {"page_kind": "shop_product_list", "activity": None}
    )


def test_real_two_card_coupon_text_is_detected_before_shop_search_tap():
    text = """
    大麦美食 粉丝4439
    恭喜获得 双重福利
    满5可用 满20可用
    关注并领取
    """

    assert coupon_overlay_text_present(text)


def _settings():
    return SimpleNamespace(
        emulator_config=lambda: {"package": "com.xingin.xhs"}
    )


def _overlay_probe():
    return {
        "page_kind": "shop_product_list",
        "activity": "com.xingin.xhs/com.xingin.reactnative.ui.XhsReactTranslucentActivity",
        "has_anr": False,
        "risk_stop_reason": None,
        "screenshot": "coupon.png",
    }


class _Device:
    def __init__(self, pids=("691", "691")):
        self.pids = iter(pids)
        self.taps = []

    def pidof(self, _package):
        return next(self.pids)

    def tap(self, x, y):
        self.taps.append((x, y))


def test_translucent_coupon_uses_one_visual_tap_then_enters_shop_recovery(monkeypatch):
    target = UiTarget(539, 1720, Bounds(507, 1688, 571, 1752), "close", "visual X")
    after = {
        "page_kind": "shop_product_list",
        "activity": "com.xingin.xhs/com.xingin.commercial.shoppage.ShopDetailActivity",
        "has_anr": False,
        "risk_stop_reason": None,
    }
    monkeypatch.setattr("xhs_scout.monitor.find_coupon_close_button", lambda _path: target)
    monkeypatch.setattr("xhs_scout.monitor.probe_current_page", lambda *_a, **_k: after)
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    device = _Device()

    recovered, evidence = _close_visual_coupon_overlay_once(
        _settings(), device, probe=_overlay_probe(), run_id="replay-4460", task_id=1,
        dry_run=False, wait_seconds=0,
    )

    assert device.taps == [(539, 1720)]
    assert recovered is after
    assert evidence["target"]["reason"] == "visual X"
    assert _should_back_recover_from_shop_list(recovered)


@pytest.mark.parametrize("candidate_count", [0, 2])
def test_missing_or_ambiguous_visual_target_hard_stops_without_tap(monkeypatch, candidate_count):
    monkeypatch.setattr("xhs_scout.monitor.find_coupon_close_button", lambda _path: None)
    device = _Device(("691",))

    with pytest.raises(CouponOverlayHardStop) as stopped:
        _close_visual_coupon_overlay_once(
            _settings(), device, probe=_overlay_probe(), run_id=f"count-{candidate_count}",
            task_id=1, dry_run=False, wait_seconds=0,
        )

    assert stopped.value.reason == "coupon_close_unique_visual_target_missing"
    assert device.taps == []


@pytest.mark.parametrize(
    ("after", "pids", "reason"),
    [
        (_overlay_probe(), ("691", "691"), "coupon_close_overlay_still_present"),
        ({"page_kind": "unknown", "activity": "UnexpectedActivity", "has_anr": False, "risk_stop_reason": None}, ("691", "691"), "coupon_close_unknown_or_abnormal_destination"),
        ({"page_kind": "shop_product_list", "activity": "ShopDetailActivity", "has_anr": False, "risk_stop_reason": "risk"}, ("691", "691"), "coupon_close_post_risk_stop"),
        ({"page_kind": "shop_product_list", "activity": "ShopDetailActivity", "has_anr": True, "risk_stop_reason": None}, ("691", "691"), "coupon_close_post_anr"),
        ({"page_kind": "shop_product_list", "activity": "ShopDetailActivity", "has_anr": False, "risk_stop_reason": None}, ("691", "777"), "coupon_close_pid_changed"),
    ],
)
def test_post_tap_unsafe_state_hard_stops_without_retry(monkeypatch, after, pids, reason):
    target = UiTarget(539, 1720, Bounds(507, 1688, 571, 1752), "close", "visual X")
    monkeypatch.setattr("xhs_scout.monitor.find_coupon_close_button", lambda _path: target)
    monkeypatch.setattr("xhs_scout.monitor.probe_current_page", lambda *_a, **_k: after)
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    device = _Device(pids)

    with pytest.raises(CouponOverlayHardStop) as stopped:
        _close_visual_coupon_overlay_once(
            _settings(), device, probe=_overlay_probe(), run_id="unsafe", task_id=1,
            dry_run=False, wait_seconds=0,
        )

    assert stopped.value.reason == reason
    assert device.taps == [(539, 1720)]
