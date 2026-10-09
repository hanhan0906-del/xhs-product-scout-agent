from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xhs_scout.coupon_overlay import coupon_overlay_text_present
from xhs_scout.layout_fields import extract_layout_fields
from xhs_scout.seller_profile import (
    _layout_shop_entry_target,
    capture_seller_profile_from_product,
    parse_seller_profile_probe,
)
from xhs_scout.ui_automation import Bounds, UiTarget


def _shop_layout(shop_name: str, follower_count: int) -> dict:
    def box(left, top, right, bottom, text):
        return {
            "box": [[left, top], [right, top], [right, bottom], [left, bottom]],
            "text": text,
            "confidence": 0.99,
        }

    return extract_layout_fields(
        page_kind="shop_product_list",
        ocr_details=[
            box(275, 272, 522, 328, shop_name),
            box(273, 415, 399, 452, f"粉丝{follower_count}"),
        ],
        screenshot="shop-layout-fixture.png",
        image_size=(1080, 2340),
    )


def test_product58_real_shop_probe_uses_top_header_name_not_rating():
    probe_path = (
        Path(__file__).resolve().parents[1]
        / "data/probes/monitor-26845cb66dbe-seller-after-138/probe.json"
    )
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    probe["layout_fields"] = _shop_layout("爱做PPT的小熊猫", 2637)

    parsed = parse_seller_profile_probe(probe)

    assert parsed["author_name"] == "爱做PPT的小熊猫"
    assert parsed["author_name"] != "★★★★★4.8"
    assert parsed["follower_count"] == 2637


def test_claimed_coupon_overlay_text_is_specific():
    assert coupon_overlay_text_present("恭喜你领券成功 全店通用 立即使用")
    assert not coupon_overlay_text_present("商品详情 立即使用")
    assert not coupon_overlay_text_present("恭喜你购买成功 立即使用")


def test_product_shop_entry_can_fall_back_to_unique_fixed_roi():
    layout = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=[
            {
                "box": [[52, 2232], [114, 2232], [114, 2267], [52, 2267]],
                "text": "店铺",
                "confidence": 0.999,
            }
        ],
        screenshot="product-layout-fixture.png",
        image_size=(1080, 2340),
    )

    target = _layout_shop_entry_target(
        {"page_kind": "product_detail", "layout_fields": layout}
    )

    assert target is not None
    assert target.label == "店铺"
    assert target.reason == "fixed-layout-roi=shop_entry"
    assert (target.x, target.y) == (83, 2249)


def test_coupon_detail_is_backed_out_before_shop_target_is_tapped(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "product_detail",
                "activity": "XhsReactTranslucentActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "恭喜你领券成功 全店通用 立即使用",
                "probe_dir": "coupon-before",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-after-back",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "食谱店 粉丝4437 综合 销量 价格",
                "layout_fields": _shop_layout("食谱店", 4437),
                "screenshot": "shop.png",
                "probe_dir": "shop-probe",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-recovered",
            },
        ]
    )
    events = []

    class Device:
        def __init__(self):
            self.actions = []

        def back(self):
            self.actions.append(("back",))

        def tap(self, x, y):
            self.actions.append(("tap", x, y))

        def pidof(self, _package):
            return "691"

        def activity_dump(self):
            return ""

    target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_product_shop_entry",
        lambda _xml: target,
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.seller_profile.connect", lambda _path: nullcontext(object())
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_note_observation",
        lambda _conn, **_kwargs: 91,
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_run_event", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile._backfill_product_shop_name",
        lambda *_args, **_kwargs: None,
    )

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            db_path="unused.sqlite3",
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="coupon-before-tap",
        task_id=122,
        product_id=49,
        wait_seconds=0,
    )

    assert result["parsed"]["follower_count"] == 4437
    assert device.actions == [("back",), ("tap", 82, 2180), ("back",)]


def test_coupon_retry_still_on_detail_returns_soft_disposition(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "before",
            },
            {
                "page_kind": "product_detail",
                "activity": "XhsReactTranslucentActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "恭喜你领券成功 立即使用",
                "probe_dir": "coupon-after-first-tap",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-after-back",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-after-retry",
            },
        ]
    )

    class Device:
        def __init__(self):
            self.actions = []

        def back(self):
            self.actions.append(("back",))

        def tap(self, x, y):
            self.actions.append(("tap", x, y))

        def pidof(self, _package):
            return "691"

        def activity_dump(self):
            return ""

    targets = iter(
        [
            UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "first"),
            UiTarget(84, 2180, Bounds(24, 2142, 144, 2218), "店铺", "retry"),
        ]
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_product_shop_entry", lambda _xml: next(targets)
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="coupon-retry",
        task_id=122,
        product_id=49,
        wait_seconds=0,
    )

    assert result["skipped"] is True
    assert result["skip_reason"] == "shop_entry_not_opened"
    assert result["task_disposition"] == {
        "retryable": True,
        "reason": "shop_entry_not_opened",
    }
    assert device.actions == [
        ("tap", 82, 2180),
        ("back",),
        ("tap", 84, 2180),
    ]


def test_claimed_coupon_over_shop_is_backed_out_then_profile_is_recorded(
    monkeypatch,
):
    probes = iter(
        [
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-before",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "XhsReactTranslucentActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "K12的英语PPT 粉丝4437 恭喜你领券成功 可叠加使用 立即使用",
                "layout_fields": _shop_layout("K12的英语PPT", 4437),
                "screenshot": "shop-coupon.png",
                "probe_dir": "shop-coupon",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "K12的英语PPT 粉丝4437 综合 销量 新品 价格",
                "layout_fields": _shop_layout("K12的英语PPT", 4437),
                "screenshot": "shop.png",
                "probe_dir": "shop-after-coupon-back",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-recovered",
            },
        ]
    )
    recorded = {}
    order = []

    class Device:
        def __init__(self):
            self.actions = []

        def tap(self, x, y):
            self.actions.append(("tap", x, y))
            if (x, y) == (539, 1720):
                order.append("close")

        def back(self):
            self.actions.append(("back",))

        def pidof(self, _package):
            return "691"

        def activity_dump(self):
            return ""

    target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_product_shop_entry", lambda _xml: target
    )
    close_target = UiTarget(
        539, 1720, Bounds(507, 1688, 571, 1752), "关闭", "unique visual X"
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_coupon_close_button",
        lambda _path: close_target,
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.seller_profile.connect", lambda _path: nullcontext(object())
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_note_observation",
        lambda _conn, **kwargs: (
            recorded.update(kwargs), order.append("persist"), 92
        )[-1],
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_run_event", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile._backfill_product_shop_name",
        lambda *_args, **_kwargs: None,
    )

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            db_path="unused.sqlite3",
            data_dir=SimpleNamespace(__truediv__=lambda *_args: None),
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="shop-coupon",
        task_id=133,
        product_id=53,
        wait_seconds=0,
    )

    assert result["parsed"]["follower_count"] == 4437
    assert result["note_observation_id"] == 92
    assert device.actions == [("tap", 82, 2180), ("tap", 539, 1720), ("back",)]
    assert order == ["persist", "close"]
    assert recorded["raw"]["coupon_observed"] is True
    assert recorded["raw"]["coupon_close"] is None


@pytest.mark.parametrize(
    ("recovery_probe", "pids", "expected_reason"),
    [
        (
            {
                "page_kind": "unknown",
                "activity": "UnexpectedActivity",
                "has_anr": False,
                "risk_stop_reason": None,
            },
            ["691", "691", "691", "691"],
            "seller_coupon_close_unknown_or_abnormal_destination",
        ),
        (
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": True,
                "risk_stop_reason": None,
            },
            ["691", "691", "691", "691"],
            "seller_coupon_close_post_anr",
        ),
        (
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": False,
                "risk_stop_reason": None,
            },
            ["691", "691", "691", "777"],
            "seller_coupon_close_pid_changed",
        ),
    ],
)
def test_claimed_shop_coupon_recovery_keeps_hard_safety_gates(
    monkeypatch, recovery_probe, pids, expected_reason
):
    probes = iter(
        [
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-before",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "XhsReactTranslucentActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "青禾科技 粉丝2014 恭喜你领券成功 立即使用",
                "probe_dir": "shop-coupon",
            },
            recovery_probe,
        ]
    )
    pid_values = iter(pids)

    class Device:
        def __init__(self):
            self.actions = []

        def tap(self, x, y):
            self.actions.append(("tap", x, y))

        def back(self):
            self.actions.append(("back",))

        def pidof(self, _package):
            return next(pid_values)

        def activity_dump(self):
            return ""

    target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_product_shop_entry", lambda _xml: target
    )
    close_target = UiTarget(
        539, 1720, Bounds(507, 1688, 571, 1752), "关闭", "unique visual X"
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_coupon_close_button",
        lambda _path: close_target,
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.seller_profile.connect", lambda _path: nullcontext(object())
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_note_observation",
        lambda _conn, **_kwargs: 152,
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_run_event", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile._backfill_product_shop_name",
        lambda *_args, **_kwargs: None,
    )

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            db_path="unused.sqlite3",
            data_dir=SimpleNamespace(__truediv__=lambda *_args: None),
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="shop-coupon-hard-stop",
        task_id=133,
        product_id=53,
        wait_seconds=0,
    )

    assert result["blocked"] is True
    assert result["reason"] == expected_reason
    assert device.actions == [("tap", 82, 2180), ("tap", 539, 1720)]


@pytest.mark.parametrize(
    ("after_probe", "expected_reason"),
    [
        (
            {
                "page_kind": "unknown",
                "activity": "UnexpectedActivity",
                "has_anr": False,
                "risk_stop_reason": None,
            },
            "店铺入口打开了未知页面：unknown",
        ),
        (
            {
                "page_kind": "risk_stop",
                "activity": "RiskActivity",
                "has_anr": False,
                "risk_stop_reason": "验证码",
            },
            "seller_after_shop_tap_risk_stop",
        ),
        (
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": True,
                "risk_stop_reason": None,
            },
            "seller_after_shop_tap_anr",
        ),
        (
            {
                "page_kind": "product_detail",
                "activity": "XhsReactTranslucentActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "未识别透明层",
            },
            "unrecognized_translucent_activity_after_shop_tap",
        ),
    ],
)
def test_unexpected_risk_and_anr_after_shop_tap_still_block(
    monkeypatch, after_probe, expected_reason
):
    before = {
        "page_kind": "product_detail",
        "activity": "GoodsDetailActivityV2",
        "has_anr": False,
        "risk_stop_reason": None,
        "text": "商品详情",
        "probe_dir": "before",
    }
    probes = iter([before, after_probe])

    class Device:
        def __init__(self):
            self.taps = []

        def tap(self, x, y):
            self.taps.append((x, y))

        def pidof(self, _package):
            return "691"

        def activity_dump(self):
            return ""

    target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_product_shop_entry", lambda _xml: target
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="seller-hard-stop",
        task_id=122,
        product_id=49,
        wait_seconds=0,
    )

    assert result["blocked"] is True
    assert result["reason"] == expected_reason
    assert device.taps == [(82, 2180)]


def test_visible_follower_on_unenumerated_shop_overlay_is_persisted(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-before",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "XhsReactTranslucentActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": (
                    "青禾科技 粉丝2014 341篇笔记 "
                    "送你一张优惠券 关注领取 综合 销量 新品"
                ),
                "layout_fields": _shop_layout("青禾科技", 2014),
                "screenshot": "seller-after-25.png",
                "probe_dir": "monitor-ebf25783933a-seller-after-25",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "青禾科技 粉丝2014 341篇笔记",
                "layout_fields": _shop_layout("青禾科技", 2014),
                "probe_dir": "shop-after-overlay-back",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "probe_dir": "detail-recovered",
            },
        ]
    )
    recorded = {}

    class Device:
        def __init__(self):
            self.actions = []

        def tap(self, x, y):
            self.actions.append(("tap", x, y))

        def back(self):
            self.actions.append(("back",))

        def pidof(self, _package):
            return "691"

        def activity_dump(self):
            return ""

    target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    close_target = UiTarget(
        539,
        1720,
        Bounds(509, 1690, 569, 1750),
        "优惠券关闭",
        "unique centered circular coupon close button",
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_product_shop_entry", lambda _xml: target
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_coupon_close_button",
        lambda _screenshot: close_target,
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.seller_profile.connect", lambda _path: nullcontext(object())
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_note_observation",
        lambda _conn, **kwargs: recorded.update(kwargs) or 153,
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_run_event", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile._backfill_product_shop_name",
        lambda *_args, **_kwargs: None,
    )

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            db_path="unused.sqlite3",
            data_dir=SimpleNamespace(__truediv__=lambda *_args: None),
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="monitor-ebf25783933a",
        task_id=25,
        product_id=53,
        wait_seconds=0,
    )

    assert "blocked" not in result
    assert result["parsed"]["follower_count"] == 2014
    assert result["follower_display_status"] == "visible"
    assert result["low_follower_qualified"] is False
    assert recorded["follower_count"] == 2014
    assert recorded["raw"]["follower_display_status"] == "visible"
    assert recorded["raw"]["low_follower_qualified"] is False
    assert recorded["raw"]["coupon_observed"] is False
    assert recorded["raw"]["coupon_close"] is None
    assert device.actions == [("tap", 82, 2180), ("tap", 539, 1720), ("back",)]


def test_existing_shop_product_list_is_used_without_tapping(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "shop_product_list",
                "activity": "com.xingin.xhs/com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "橙子资料库\n粉丝8524\n已售2857",
                "layout_fields": _shop_layout("橙子资料库", 8524),
                "screenshot": "shop.png",
                "probe_dir": "shop-probe",
            },
            {
                "page_kind": "product_detail",
                "activity": "com.xingin.xhs/com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "房屋租赁合同",
                "screenshot": "detail.png",
                "probe_dir": "detail-probe",
            },
        ]
    )
    recorded = {}

    class Device:
        def __init__(self):
            self.taps = []
            self.back_calls = 0

        def tap(self, x, y):
            self.taps.append((x, y))

        def back(self):
            self.back_calls += 1

    device = Device()
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.seller_profile.connect",
        lambda _path: nullcontext(object()),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_note_observation",
        lambda _conn, **kwargs: recorded.update(kwargs) or 77,
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_run_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile._backfill_product_shop_name",
        lambda *_args, **_kwargs: None,
    )

    result = capture_seller_profile_from_product(
        SimpleNamespace(db_path="unused.sqlite3"),
        device,
        run_id="seller-already-open",
        task_id=98,
        product_id=34,
        wait_seconds=0,
    )

    assert result["parsed"]["follower_count"] == 8524
    assert result["note_observation_id"] == 77
    assert device.taps == []
    assert device.back_calls == 1
    assert recorded["raw"]["entry"] == "already_open_shop_product_list"


def test_coupon_overlay_is_not_clicked_when_follower_is_visible(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "probe_dir": "missing-before",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "恭喜获得双重福利 关注并领取 粉丝4437",
                "layout_fields": _shop_layout("大麦美食", 4437),
                "screenshot": "coupon.png",
                "probe_dir": "coupon-probe",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "大麦美食 粉丝4437 238篇笔记 综合 销量 价格",
                "layout_fields": _shop_layout("大麦美食", 4437),
                "screenshot": "shop.png",
                "probe_dir": "shop-probe",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "screenshot": "detail.png",
                "probe_dir": "detail-probe",
            },
        ]
    )
    recorded = {}

    class Device:
        def __init__(self):
            self.taps = []
            self.back_calls = 0

        def tap(self, x, y):
            self.taps.append((x, y))

        def back(self):
            self.back_calls += 1

        def pidof(self, _package):
            return "691"

        def activity_dump(self):
            return ""

    shop_target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    monkeypatch.setattr("xhs_scout.seller_profile.probe_current_page", lambda *_a, **_k: next(probes))
    monkeypatch.setattr("xhs_scout.seller_profile.find_product_shop_entry", lambda _xml: shop_target)
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("xhs_scout.seller_profile.connect", lambda _path: nullcontext(object()))
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_note_observation",
        lambda _conn, **kwargs: recorded.update(kwargs) or 88,
    )
    monkeypatch.setattr("xhs_scout.seller_profile.record_run_event", lambda *_a, **_k: None)
    backfilled = {}
    monkeypatch.setattr(
        "xhs_scout.seller_profile._backfill_product_shop_name",
        lambda _conn, product_id, shop_name: backfilled.update(
            {"product_id": product_id, "shop_name": shop_name}
        ),
    )

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            db_path="unused.sqlite3",
            data_dir=SimpleNamespace(__truediv__=lambda *_args: None),
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="coupon-close",
        task_id=99,
        product_id=39,
        wait_seconds=0,
    )

    assert result["parsed"]["follower_count"] == 4437
    assert device.taps == [(82, 2180)]
    assert device.back_calls == 2
    assert recorded["raw"]["coupon_close"] is None
    assert recorded["raw"]["coupon_observed"] is True
    assert backfilled == {"product_id": 39, "shop_name": "大麦美食"}


def test_coupon_activity_that_disappears_before_screenshot_does_not_trigger_tap(
    monkeypatch, tmp_path
):
    probes = iter(
        [
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "probe_dir": "missing-before",
            },
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "大麦美食 粉丝4439 238篇笔记 综合 销量 价格",
                "layout_fields": _shop_layout("大麦美食", 4439),
                "screenshot": "shop.png",
                "probe_dir": "shop-probe",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": "商品详情",
                "screenshot": "detail.png",
                "probe_dir": "detail-probe",
            },
        ]
    )
    activities = iter(["XhsReactTranslucentActivity"])
    recorded = {}

    class Device:
        def __init__(self):
            self.taps = []
            self.back_calls = 0

        def tap(self, x, y):
            self.taps.append((x, y))

        def back(self):
            self.back_calls += 1

        def pidof(self, _package):
            return "691"

        def activity_dump(self):
            return next(activities)

        def screenshot(self, destination):
            destination.write_bytes(b"shop-without-overlay")
            return destination

    shop_target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_product_shop_entry",
        lambda _xml: shop_target,
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.seller_profile.connect",
        lambda _path: nullcontext(object()),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_note_observation",
        lambda _conn, **kwargs: recorded.update(kwargs) or 89,
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_run_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile._backfill_product_shop_name",
        lambda *_args, **_kwargs: None,
    )

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            db_path="unused.sqlite3",
            data_dir=tmp_path,
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="coupon-disappeared",
        task_id=99,
        product_id=41,
        wait_seconds=1,
    )

    assert result["parsed"]["follower_count"] == 4439
    assert device.taps == [(82, 2180)]
    assert device.back_calls == 1
    assert recorded["raw"]["coupon_close"] is None
    assert recorded["raw"]["coupon_observed"] is True


def test_shop_open_pid_change_is_reported_as_process_crash(monkeypatch):
    probes = iter(
        [
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "probe_dir": "missing-before",
            },
            {
                "page_kind": "product_detail",
                "activity": "GoodsDetailActivityV2",
                "has_anr": False,
                "risk_stop_reason": None,
                "probe_dir": "after-crash",
            },
        ]
    )
    pids = iter(["100", "200"])

    class Device:
        def tap(self, _x, _y):
            return None

        def pidof(self, _package):
            return next(pids)

    target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    monkeypatch.setattr("xhs_scout.seller_profile.probe_current_page", lambda *_a, **_k: next(probes))
    monkeypatch.setattr("xhs_scout.seller_profile.find_product_shop_entry", lambda _xml: target)

    result = capture_seller_profile_from_product(
        SimpleNamespace(
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        Device(),
        run_id="shop-crash",
        task_id=99,
        product_id=39,
        wait_seconds=0,
    )

    assert result["blocked"] is True
    assert result["reason"] == "shop_open_process_crash"
    assert result["process_change"] == {"before": "100", "after": "200"}


@pytest.mark.parametrize(
    ("page_kind", "activity", "shop_text"),
    [
        (
            "shop_product_list",
            "XhsReactTranslucentActivity",
            "店铺商品 送你一张优惠券 关注领取 综合 销量 价格",
        ),
        ("account_profile", "ShopDetailActivity", "店铺商品 综合 销量 价格"),
    ],
)
def test_known_shop_without_visible_follower_records_successful_evidence(
    monkeypatch, page_kind, activity, shop_text
):
    recorded = {}
    backfilled = []
    probe_items = [
        {
            "page_kind": "product_detail",
            "activity": "GoodsDetailActivityV2",
            "has_anr": False,
            "risk_stop_reason": None,
            "text": "商品详情",
            "probe_dir": "detail-before",
        },
        {
            "page_kind": page_kind,
            "activity": activity,
            "has_anr": False,
            "risk_stop_reason": None,
            "text": shop_text,
            "screenshot": "shop-without-follower.png",
            "probe_dir": "shop-without-follower",
        },
    ]
    if activity == "XhsReactTranslucentActivity":
        probe_items.append(
            {
                "page_kind": "shop_product_list",
                "activity": "ShopDetailActivity",
                "has_anr": False,
                "risk_stop_reason": None,
                "text": shop_text,
                "probe_dir": "shop-after-coupon-close",
            }
        )
    probe_items.append(
        {
            "page_kind": "product_detail",
            "activity": "GoodsDetailActivityV2",
            "has_anr": False,
            "risk_stop_reason": None,
            "text": "商品详情",
            "probe_dir": "detail-recovered",
        }
    )
    probes = iter(probe_items)

    class Device:
        def __init__(self):
            self.actions = []

        def tap(self, x, y):
            self.actions.append(("tap", x, y))

        def back(self):
            self.actions.append(("back",))

        def pidof(self, _package):
            return "691"

        def activity_dump(self):
            return "ShopDetailActivity"

    target = UiTarget(82, 2180, Bounds(22, 2142, 143, 2218), "店铺", "shop")
    close_target = UiTarget(
        539,
        1720,
        Bounds(509, 1690, 569, 1750),
        "优惠券关闭",
        "unique centered circular coupon close button",
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_product_shop_entry", lambda _xml: target
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.find_coupon_close_button",
        lambda _screenshot: (
            close_target if activity == "XhsReactTranslucentActivity" else None
        ),
    )
    monkeypatch.setattr("xhs_scout.seller_profile.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.seller_profile.connect", lambda _path: nullcontext(object())
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_note_observation",
        lambda _conn, **kwargs: recorded.update(kwargs) or 151,
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile.record_run_event", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "xhs_scout.seller_profile._backfill_product_shop_name",
        lambda *_args, **_kwargs: backfilled.append((_args, _kwargs)),
    )

    device = Device()
    result = capture_seller_profile_from_product(
        SimpleNamespace(
            db_path="unused.sqlite3",
            emulator_config=lambda: {"package": "com.xingin.xhs"},
        ),
        device,
        run_id="seller-follower-missing",
        task_id=140,
        product_id=60,
        wait_seconds=0,
    )

    assert "skipped" not in result
    assert "blocked" not in result
    assert result["note_observation_id"] == 151
    assert result["parsed"]["follower_count"] is None
    assert result["follower_display_status"] == "not_displayed"
    assert result["low_follower_qualified"] is False
    assert result["after_probe"]["page_kind"] == page_kind
    assert result["recovery_probe"]["page_kind"] == "product_detail"
    assert recorded["source"] == "seller_profile_from_product"
    assert recorded["product_id"] == 60
    assert recorded["follower_count"] is None
    assert recorded["raw"]["follower_display_status"] == "not_displayed"
    assert recorded["raw"]["low_follower_qualified"] is False
    assert backfilled == []
    expected_actions = [("tap", 82, 2180)]
    if activity == "XhsReactTranslucentActivity":
        expected_actions.append(("tap", 539, 1720))
    expected_actions.append(("back",))
    assert device.actions == expected_actions
