from pathlib import Path

from PIL import Image, ImageDraw

from xhs_scout.config import Settings
from xhs_scout.db import connect
import xhs_scout.detail_metrics as detail_metrics
from xhs_scout.detail_metrics import (
    DEFAULT_ROI,
    capture_metrics_strip,
    _find_gray_strip_candidates,
    _merge_metric_frames,
    _metric_text_quality,
    _product_detail_controls_present,
    _rank_metric_roi_candidate,
    update_observation_with_metrics,
)
from xhs_scout.signals import ProductSignals, parse_product_text


def test_three_gray_metrics_are_required_for_candidate_status(tmp_path: Path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        product_id = conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, first_seen_at, last_seen_at
            ) VALUES ('metric-gate', '虚拟资料商品', '2026-07-30T00:00:00+08:00',
                      '2026-07-30T00:00:00+08:00')
            """
        ).lastrowid
        observation_id = conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, raw_signals_json
            ) VALUES (?, '2026-07-30T00:00:00+08:00', 'test', '{}')
            """,
            (product_id,),
        ).lastrowid

    metrics = {
        "roi": list(DEFAULT_ROI),
        "roi_detection": {},
        "merge_rules": {},
        "navigation_guard": {},
        "signals": {
            "cart_24h_min": 20,
            "positive_reviews_30d_min": 30,
            "interested_7d_min": 100,
        },
        "frames": [
            {
                "frame": 1,
                "screenshot": "screen.png",
                "roi": "roi.png",
                "text": "24小时加购 20 近期好评 30 感兴趣 100",
                "signals": {
                    "cart_24h_min": 20,
                    "positive_reviews_30d_min": 30,
                    "interested_7d_min": 100,
                },
                "metric_like": True,
                "ignored": False,
                "changed": True,
                "repeated": False,
            }
        ],
    }
    result = update_observation_with_metrics(settings, observation_id, metrics)

    with connect(settings.db_path) as conn:
        status = conn.execute(
            "SELECT status FROM candidate_assessments ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert result["gray_metric_count"] == 3
    assert status == "candidate"

    metrics["signals"].pop("interested_7d_min")
    metrics["frames"][0]["signals"].pop("interested_7d_min")
    result = update_observation_with_metrics(settings, observation_id, metrics)
    with connect(settings.db_path) as conn:
        status = conn.execute(
            "SELECT status FROM candidate_assessments ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert result["gray_metric_count"] == 2
    assert status == "observed"


def test_gray_strip_candidate_locator_prefers_metric_band(tmp_path: Path):
    image_path = tmp_path / "screen.png"
    image = Image.new("RGB", (1080, 1920), "white")
    draw = ImageDraw.Draw(image)
    for x1 in (18, 330, 642):
        draw.rounded_rectangle((x1, 918, x1 + 280, 972), radius=18, fill=(234, 234, 234))
    image.save(image_path)

    candidates = _find_gray_strip_candidates(image_path, limit=3)

    assert candidates
    x1, y1, x2, y2 = candidates[0]["roi"]
    assert x1 <= DEFAULT_ROI[0] + 8
    assert x2 >= 1060
    assert y1 <= 918 <= y2


def test_gray_strip_candidates_keep_near_white_metric_band_and_vertical_diversity(tmp_path: Path):
    image_path = tmp_path / "screen.png"
    image = Image.new("RGB", (1080, 1920), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 880, 1063, 950), fill=(234, 234, 234))
    for x1, x2 in ((24, 220), (232, 440), (452, 655), (667, 1045)):
        draw.rounded_rectangle((x1, 1128, x2, 1172), radius=12, fill=(248, 248, 248))
    image.save(image_path)

    candidates = _find_gray_strip_candidates(image_path, limit=8)
    centers = [(item["roi"][1] + item["roi"][3]) // 2 for item in candidates]

    assert any(abs(center - 1150) <= 35 for center in centers)
    assert len(centers) == len(set(centers))
    assert all(abs(left - right) >= 24 for index, left in enumerate(centers) for right in centers[index + 1 :])


def test_product_detail_control_guard_rejects_shop_page():
    detail_immediate = (
        '<node text="客服"/><node text="购物车"/>'
        '<node text="加入购物车"/><node text="立即购买"/>'
    )
    detail_coupon = (
        '<node text="客服"/><node text="购物车"/>'
        '<node text="加入购物车"/><node text="领券购买"/>'
    )
    shop = '<node text="综合"/><node text="销量"/><node text="新品"/>'
    assert _product_detail_controls_present(detail_immediate) is True
    assert _product_detail_controls_present(detail_coupon) is True
    assert _product_detail_controls_present(shop) is False


def test_product_detail_control_guard_requires_all_three_stable_controls():
    assert _product_detail_controls_present(
        '<node text="客服"/><node text="购物车"/><node text="领券购买"/>'
    ) is False
    assert _product_detail_controls_present(
        '<node text="客服"/><node text="加入购物车"/><node text="领券购买"/>'
    ) is False
    assert _product_detail_controls_present(
        '<node text="购物车"/><node text="加入购物车"/><node text="领券购买"/>'
    ) is False


def test_metric_text_quality_rejects_half_ocr_and_polluted_frames():
    half = "近30天\n人购买"
    half_quality = _metric_text_quality(half, parse_product_text(half))
    assert half_quality["valid"] is False
    assert half_quality["reason"] == "half_ocr"

    polluted = "近30天 100+ 人购买\n加入购物车\n立即购买\n客服"
    polluted_quality = _metric_text_quality(polluted, parse_product_text(polluted))
    assert polluted_quality["valid"] is False
    assert polluted_quality["reason"] == "polluted"


def test_dynamic_roi_ranking_penalizes_pollution_even_with_better_layout():
    polluted_candidate = {"roi": (16, 930, 1064, 990), "gray_score": 0.2, "layout_score": 0.2}
    metric_candidate = {"roi": (16, 1090, 1064, 1150), "gray_score": 0.08, "layout_score": 0.02}
    polluted_text = "近30天 100+ 人购买\n加入购物车\n立即购买\n客服"
    metric_text = "近30天 1000+ 人购买\n近30天新增 300+ 条好评\n2000人正在看"

    polluted_rank = _rank_metric_roi_candidate(
        polluted_candidate,
        polluted_text,
        parse_product_text(polluted_text),
    )
    metric_rank = _rank_metric_roi_candidate(
        metric_candidate,
        metric_text,
        parse_product_text(metric_text),
    )

    assert polluted_rank["metric_like"] is False
    assert metric_rank["metric_like"] is True
    assert metric_rank["rank_score"] > polluted_rank["rank_score"]


def test_merge_metric_frames_deduplicates_and_resolves_conflicts_conservatively():
    frame_one = ProductSignals(sales_30d_min=1000, positive_reviews_30d_min=300)
    frame_two = ProductSignals(sales_30d_min=100, positive_reviews_30d_min=300)
    frame_three = ProductSignals(sales_30d_min=1000, positive_reviews_30d_min=999)

    merged, rules = _merge_metric_frames(
        [
            {
                "frame": 1,
                "_signals_obj": frame_one,
                "quality": {"quality_score": 50},
                "ignored": False,
                "repeated": False,
            },
            {
                "frame": 2,
                "_signals_obj": frame_two,
                "quality": {"quality_score": 50},
                "ignored": False,
                "repeated": False,
            },
            {
                "frame": 3,
                "_signals_obj": frame_three,
                "quality": {"quality_score": 50},
                "ignored": True,
                "repeated": True,
            },
        ]
    )

    assert merged.sales_30d_min == 100
    assert rules["sales_30d_min"]["rule"] == "conflict_conservative_min"
    assert merged.positive_reviews_30d_min == 300


class FakeDevice:
    def __init__(self):
        self.screenshots = 0
        self.swipes = []
        self.taps = []

    def screenshot(self, path: Path) -> None:
        self.screenshots += 1
        image = Image.new("RGB", (1080, 1920), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle(DEFAULT_ROI, fill=(234, 234, 234))
        image.save(path)

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def ui_dump(self) -> str:
        return (
            '<node text="客服"/><node text="购物车"/>'
            '<node text="加入购物车"/><node text="领券购买"/>'
        )

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int) -> None:
        self.swipes.append((x1, y1, x2, y2, ms))


def test_capture_metrics_strip_ignores_repeated_frames_offline(tmp_path: Path, monkeypatch):
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "xhs_scout.sqlite3",
        capture_dir=tmp_path / "data" / "captures",
        reports_dir=tmp_path / "data" / "reports",
        emulator_config_path=tmp_path / "config" / "emulator.json",
    )

    def fake_extract_text(path: Path):
        return "近30天 1000+ 人购买\n近30天新增 300+ 条好评", {"engine": "fake"}

    monkeypatch.setattr(detail_metrics, "extract_text", fake_extract_text)
    output = capture_metrics_strip(
        settings,
        FakeDevice(),
        roi=DEFAULT_ROI,
        max_frames=3,
        allow_swipe=True,
    )

    assert output["signals"]["sales_30d_min"] == 1000
    assert output["frames"][1]["ignored"] is True
    assert output["frames"][1]["ignore_reason"] == "repeated"
    assert output["merge_rules"]["sales_30d_min"]["values"] == [1000]


def test_auto_detected_weak_single_sales_roi_never_taps_or_swipes(tmp_path: Path, monkeypatch):
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "xhs_scout.sqlite3",
        capture_dir=tmp_path / "data" / "captures",
        reports_dir=tmp_path / "data" / "reports",
        emulator_config_path=tmp_path / "config" / "emulator.json",
    )
    device = FakeDevice()
    monkeypatch.setattr(
        detail_metrics,
        "locate_metric_strip_roi",
        lambda *_args, **_kwargs: {
            "chosen": {
                "roi": list(DEFAULT_ROI),
                "gray_score": 0.1368,
                "layout_score": 0.0788,
                "marker_hits": 0,
                "metric_fields": 1,
            },
            "candidates": [],
        },
    )
    monkeypatch.setattr(
        detail_metrics,
        "extract_text",
        lambda _path: ("已售6730", {"engine": "fake"}),
    )

    output = capture_metrics_strip(
        settings,
        device,
        max_frames=3,
        allow_swipe=True,
    )

    assert output["signals"]["cumulative_sales_min"] == 6730
    assert output["swipe_guard"]["stopped"] is True
    assert device.taps == []
    assert device.swipes == []
