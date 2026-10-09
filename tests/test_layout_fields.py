from contextlib import nullcontext
import json
from pathlib import Path

from PIL import Image

from xhs_scout.config import Settings
from xhs_scout.db import connect
from xhs_scout.ingest import ingest_image, persist_ingest_result
from xhs_scout.layout_fields import (
    extract_layout_fields,
    extract_layout_fields_with_roi_ocr,
    layout_field_value,
)
from xhs_scout.probe import probe_current_page
from xhs_scout.seller_profile import parse_seller_profile_probe
from xhs_scout.signals import ProductSignals


ROOT = Path(__file__).resolve().parents[1]
PRODUCT63_SCREENSHOT = (
    ROOT / "data/captures/2026-08-15T23-22-48-07-00_emulator-current.png"
)
SHOP142_SCREENSHOT = (
    ROOT / "data/probes/monitor-2d23326c9024-seller-after-142/current.png"
)
PRODUCT68_SCREENSHOT = (
    ROOT / "data/captures/2026-08-17T02-29-26-07-00_emulator-current.png"
)
PRODUCT69_SCREENSHOT = (
    ROOT / "data/captures/2026-08-18T05-18-49-07-00_emulator-current.png"
)
PRODUCT70_SCREENSHOT = (
    ROOT / "data/captures/2026-08-19T01-46-44-07-00_emulator-current.png"
)


def _box(left, top, right, bottom, text, confidence=0.99):
    return {
        "box": [
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
        ],
        "text": text,
        "confidence": confidence,
    }


def _product63_ocr():
    return [
        _box(229, 1333, 729, 1382, "36页可编辑PPT+教案"),
        _box(35, 1644, 187, 1713, "￥129"),
        _box(228, 1646, 491, 1704, "到手价￥98.9"),
        _box(
            43,
            1970,
            1015,
            2013,
            "新初一七年级开学第一课PPT，初一上学期开学家长会",
        ),
        _box(40, 2030, 129, 2078, "课件"),
        _box(52, 2231, 114, 2267, "店铺"),
    ]


def _shop142_ocr():
    return [
        _box(275, 272, 522, 328, "七七资料铺"),
        _box(278, 350, 556, 389, "★★★★★4.8"),
        _box(582, 351, 723, 388, "已售2245"),
        _box(273, 415, 399, 452, "粉丝389"),
        _box(427, 416, 702, 453, "昨天更新3篇笔记"),
    ]


def _product68_ocr():
    return [
        _box(37, 1645, 186, 1716, "￥15.9"),
        _box(227, 1652, 481, 1707, "到手价￥12.9"),
        _box(
            45,
            1852,
            972,
            1891,
            "开学第一课/收心立规矩主题班会PPT+教案+逐字稿",
        ),
        _box(66, 1938, 355, 1973, "近期店铺销量TOP1"),
        _box(118, 2040, 360, 2076, "付款后自动发货"),
        _box(52, 2231, 115, 2267, "店铺"),
    ]


def _product69_whole_page_ocr_without_price():
    return [
        _box(899, 1498, 1039, 1534, "已售3760"),
        _box(44, 1584, 887, 1629, "直观的一年级新生开学第一课常规训练ppt课件"),
        _box(115, 1928, 680, 1971, "已选：一年级开学第一课常规训练ppt"),
        _box(52, 2232, 114, 2267, "店铺"),
    ]


def _product70_ocr():
    return [
        _box(36, 1481, 186, 1546, "￥12.9"),
        _box(229, 1486, 457, 1539, "到手价￥8.9"),
        _box(
            49,
            1807,
            996,
            1846,
            "原创新高一开学第一课PPT+教案+逐字稿|36页可编",
        ),
        _box(43, 1868, 85, 1908, "辑"),
        _box(66, 1957, 391, 1992, "近7天1000+人感兴趣"),
        _box(454, 1955, 748, 1994, "店铺新品销量TOP2"),
        _box(115, 2058, 361, 2097, "付款后自动发货"),
        _box(52, 2231, 114, 2267, "店铺"),
    ]


def test_product63_real_coordinate_replay_is_cold_field_mapping():
    result = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=_product63_ocr(),
        screenshot=PRODUCT63_SCREENSHOT,
    )

    assert result["image_size"] == {"width": 1080, "height": 2340}
    assert result["layout_variant"] == "extended"
    assert result["layout_signature"]["wide_box_count"] == 0
    assert layout_field_value(result, "title") == (
        "新初一七年级开学第一课PPT，初一上学期开学家长会课件"
    )
    assert layout_field_value(result, "price") == 98.9
    assert layout_field_value(result, "shop_entry") == "店铺"
    matched_text = {
        match["text"]
        for field in result["fields"].values()
        for match in field["matches"]
    }
    assert "36页可编辑PPT+教案" not in matched_text
    assert "￥129" not in matched_text
    json.dumps(result, ensure_ascii=False)


def test_product68_real_coordinate_replay_selects_compact_title_only():
    result = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=_product68_ocr(),
        screenshot=PRODUCT68_SCREENSHOT,
    )

    title = result["fields"]["title"]
    assert result["layout_variant"] == "compact"
    assert result["layout_signature"]["wide_box_count"] == 1
    assert result["layout_signature"]["minimum_width_ratio"] == 0.75
    assert title["layout_variant"] == "compact"
    assert title["selected_roi"]["normalized"] == [0.02, 0.765, 0.98, 0.825]
    assert layout_field_value(result, "title") == (
        "开学第一课/收心立规矩主题班会PPT+教案+逐字稿"
    )
    assert layout_field_value(result, "price") == 12.9
    assert layout_field_value(result, "shop_entry") == "店铺"
    matched = {item["text"] for item in title["matches"]}
    assert "近期店铺销量TOP1" not in matched
    assert "付款后自动发货" not in matched


def test_product70_wrapped_compact_title_and_to_hand_price_are_isolated():
    result = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=_product70_ocr(),
        screenshot=PRODUCT70_SCREENSHOT,
    )

    title = result["fields"]["title"]
    assert result["layout_variant"] == "compact"
    assert result["layout_signature"]["wide_box_count"] == 1
    assert layout_field_value(result, "title") == (
        "原创新高一开学第一课PPT+教案+逐字稿|36页可编辑"
    )
    assert layout_field_value(result, "price") == 8.9
    assert layout_field_value(result, "shop_entry") == "店铺"
    assert title["selected_roi"]["normalized"] == [
        0.02,
        0.765,
        0.98,
        0.825,
    ]
    assert result["fields"]["price"]["roi"]["normalized"] == [
        0.18,
        0.625,
        0.55,
        0.675,
    ]
    matched = {item["text"] for item in title["matches"]}
    assert "店铺新品销量TOP2" not in matched
    assert "付款后自动发货" not in matched


def test_product69_plain_layout_uses_field_crops_for_title_price_and_shop(tmp_path):
    calls = []

    def roi_ocr(path):
        calls.append(path.name)
        if path.name == "title.png":
            return (
                "直观的一年级新生开学第一课常规训练ppt课件",
                [_box(23, 28, 866, 73, "直观的一年级新生开学第一课常规训练ppt课件")],
            )
        if path.name == "price.png":
            return "￥9.9", [_box(36, 20, 137, 83, "￥9.9")]
        if path.name == "shop_entry.png":
            return "店铺", [_box(52, 55, 114, 91, "店铺")]
        raise AssertionError(path)

    result = extract_layout_fields_with_roi_ocr(
        page_kind="product_detail",
        ocr_details=_product69_whole_page_ocr_without_price(),
        screenshot=PRODUCT69_SCREENSHOT,
        ocr_runner=roi_ocr,
        crop_dir=tmp_path / "roi",
    )

    assert result["layout_variant"] == "plain"
    assert result["layout_signature"]["plain_wide_box_count"] == 1
    assert result["layout_signature"]["wide_box_count"] == 0
    assert layout_field_value(result, "title") == (
        "直观的一年级新生开学第一课常规训练ppt课件"
    )
    assert layout_field_value(result, "price") == 9.9
    assert layout_field_value(result, "shop_entry") == "店铺"
    assert result["fields"]["title"]["selected_roi"]["normalized"] == [
        0.02,
        0.665,
        0.98,
        0.71,
    ]
    assert result["fields"]["price"]["roi"]["normalized"] == [
        0.0,
        0.625,
        0.22,
        0.675,
    ]
    assert set(calls) == {"title.png", "price.png", "shop_entry.png"}
    assert all(
        field["ocr_source"] == "fixed_roi_crop"
        for field in result["fields"].values()
    )


def test_multiple_compact_wide_boxes_make_layout_variant_ambiguous():
    result = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=[
            _box(40, 1840, 1000, 1870, "候选一"),
            _box(45, 1880, 990, 1910, "候选二"),
        ],
        screenshot="unused.png",
        image_size=(1080, 2340),
    )

    assert result["layout_variant"] is None
    assert result["layout_signature"]["wide_box_count"] == 2
    assert result["fields"]["title"]["status"] == "ambiguous_layout_variant"
    assert layout_field_value(result, "title") is None


def test_shop142_real_coordinate_replay_rejects_neighbor_metrics():
    result = extract_layout_fields(
        page_kind="shop_product_list",
        ocr_details=_shop142_ocr(),
        screenshot=SHOP142_SCREENSHOT,
    )

    assert result["image_size"] == {"width": 1080, "height": 2340}
    assert layout_field_value(result, "shop_name") == "七七资料铺"
    assert layout_field_value(result, "follower_count") == 389
    matched_text = {
        match["text"]
        for field in result["fields"].values()
        for match in field["matches"]
    }
    assert "★★★★★4.8" not in matched_text
    assert "已售2245" not in matched_text
    assert "昨天更新3篇笔记" not in matched_text


def test_shop_follower_roi_rejects_split_first_character_of_update_column():
    result = extract_layout_fields(
        page_kind="shop_product_list",
        ocr_details=[
            _box(264, 266, 532, 336, "七七资料铺"),
            _box(270, 412, 398, 453, "粉丝423"),
            _box(431, 418, 453, 448, "昨"),
        ],
        screenshot="unused.png",
        image_size=(1080, 2340),
    )

    assert layout_field_value(result, "shop_name") == "七七资料铺"
    assert layout_field_value(result, "follower_count") == 423
    assert result["fields"]["follower_count"]["roi"]["normalized"] == [
        0.2,
        0.16,
        0.4,
        0.205,
    ]


def test_missing_low_conflict_and_out_of_bounds_fail_closed():
    missing = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=[],
        screenshot="unused.png",
        image_size=(1080, 2340),
    )
    assert missing["fields"]["price"]["status"] == "missing"
    assert layout_field_value(missing, "price") is None

    low = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=[_box(228, 1646, 491, 1704, "到手价￥98.9", 0.79)],
        screenshot="unused.png",
        image_size=(1080, 2340),
    )
    assert low["fields"]["price"]["status"] == "low_confidence"
    assert layout_field_value(low, "price") is None

    conflict = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=[
            _box(228, 1646, 360, 1704, "￥98.9"),
            _box(365, 1646, 491, 1704, "￥88.9"),
        ],
        screenshot="unused.png",
        image_size=(1080, 2340),
    )
    assert conflict["fields"]["price"]["status"] == "conflict"
    assert layout_field_value(conflict, "price") is None

    outside = extract_layout_fields(
        page_kind="product_detail",
        ocr_details=[_box(43, 1970, 1090, 2013, "越界标题")],
        screenshot="unused.png",
        image_size=(1080, 2340),
    )
    assert outside["fields"]["title"]["status"] == "out_of_bounds"
    assert outside["invalid_ocr_boxes"][0]["reason"] == (
        "ocr_box_out_of_image_bounds"
    )
    assert layout_field_value(outside, "title") is None


def test_shop_profile_uses_only_layout_fields_not_conflicting_text():
    layout = extract_layout_fields(
        page_kind="shop_product_list",
        ocr_details=_shop142_ocr(),
        screenshot=SHOP142_SCREENSHOT,
    )
    parsed = parse_seller_profile_probe(
        {
            "page_kind": "shop_product_list",
            "text": "错误店铺名\n粉丝99999",
            "layout_fields": layout,
        }
    )

    assert parsed["author_name"] == "七七资料铺"
    assert parsed["follower_count"] == 389
    assert set(parsed) == {
        "author_name",
        "follower_count",
        "likes",
        "collects",
        "comments",
        "published_days_ago",
    }


def test_probe_keeps_json_safe_ocr_details_and_layout(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    screenshot = tmp_path / "source.png"
    Image.new("RGB", (1080, 2340), "white").save(screenshot)

    class Device:
        def window_focus(self):
            return "mCurrentFocus=Window{abc u0 ShopDetailActivity}"

        def screenshot(self, destination):
            Image.open(screenshot).save(destination)
            return destination

    def fake_probe_ocr(path):
        if path.name == "shop_name.png":
            return "七七资料铺", [_box(59, 38, 306, 94, "七七资料铺")]
        if path.name == "follower_count.png":
            return "粉丝389", [_box(62, 41, 188, 78, "粉丝389")]
        return "七七资料铺\n粉丝389\n综合\n销量\n新品\n价格", _shop142_ocr()

    monkeypatch.setattr("xhs_scout.probe.extract_text", fake_probe_ocr)
    monkeypatch.setattr(
        "xhs_scout.probe.classify_page_evidence",
        lambda *_args, **_kwargs: ("shop_product_list", "test"),
    )
    monkeypatch.setattr(
        "xhs_scout.probe.connect", lambda _path: nullcontext(object())
    )
    monkeypatch.setattr(
        "xhs_scout.probe.record_run_event", lambda *_args, **_kwargs: None
    )

    result = probe_current_page(
        settings,
        Device(),
        run_id="layout-probe",
        include_ui_tree=False,
    )

    assert result["ocr"] == _shop142_ocr()
    assert result["ocr_count"] == len(_shop142_ocr())
    assert layout_field_value(result["layout_fields"], "follower_count") == 389
    saved = json.loads(
        (tmp_path / "data/probes/layout-probe/probe.json").read_text(encoding="utf-8")
    )
    assert saved["ocr"] == _shop142_ocr()
    assert saved["layout_fields"]["fields"]["shop_name"]["field_value"] == (
        "七七资料铺"
    )


def test_ingest_persistence_reuses_layout_owned_signals(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    image = tmp_path / "source.png"
    Image.new("RGB", (1080, 2340), "white").save(image)
    parser_calls = []

    def fake_ingest_ocr(path):
        if path.name == "title.png":
            return (
                "新初一七年级开学第一课PPT，初一上学期开学家长会课件",
                [
                    _box(
                        22,
                        40,
                        994,
                        83,
                        "新初一七年级开学第一课PPT，初一上学期开学家长会",
                    ),
                    _box(19, 100, 108, 148, "课件"),
                ],
            )
        if path.name == "price.png":
            return "到手价￥98.9", [_box(34, 44, 297, 102, "到手价￥98.9")]
        if path.name == "shop_entry.png":
            return "店铺", [_box(52, 55, 114, 91, "店铺")]
        return (
            "36页可编辑PPT+教案\n到手价￥98.9\n已售111\n"
            "新初一七年级开学第一课PPT，初一上学期开学家长会课件",
            _product63_ocr(),
        )

    monkeypatch.setattr("xhs_scout.ingest.extract_text", fake_ingest_ocr)
    monkeypatch.setattr(
        "xhs_scout.ingest.classify_page_evidence",
        lambda *_args, **_kwargs: ("product_detail", "test"),
    )

    def fake_parse(_text):
        parser_calls.append(_text)
        return ProductSignals(
            title="错误促销标题",
            price=129.0,
            cumulative_sales_exact=111,
            is_virtual=True,
            virtual_confidence=1.0,
        )

    monkeypatch.setattr("xhs_scout.ingest.parse_product_text", fake_parse)

    output = ingest_image(settings, image, source="test", persist=False)
    assert output["signals"]["title"] == (
        "新初一七年级开学第一课PPT，初一上学期开学家长会课件"
    )
    assert output["signals"]["price"] == 98.9
    assert len(parser_calls) == 1

    persisted = persist_ingest_result(settings, output)
    assert persisted["product_id"] > 0
    assert len(parser_calls) == 1
    with connect(settings.db_path) as conn:
        product = conn.execute("SELECT title, price FROM products").fetchone()
        raw = json.loads(
            conn.execute("SELECT raw_signals_json FROM observations").fetchone()[0]
        )
    assert product["title"] == (
        "新初一七年级开学第一课PPT，初一上学期开学家长会课件"
    )
    assert product["price"] == 98.9
    assert raw["layout_fields"]["fields"]["price"]["field_value"] == 98.9
