from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import fields
from pathlib import Path

from PIL import Image

from .config import Settings
from .db import connect, utcnow
from .emulator import AdbDevice
from .ocr import extract_text
from .signals import (
    GRAY_METRIC_FIELDS,
    ProductSignals,
    candidate_score,
    gray_metric_items,
    parse_product_text,
)
from .ui_automation import (
    product_detail_controls_present as _product_detail_controls_present,
)


METRIC_FIELDS = GRAY_METRIC_FIELDS

METRIC_TEXT_MARKERS = (
    "近30天",
    "近7天",
    "24小时",
    "一周内",
    "销量TOP",
    "购买",
    "加购",
    "好评",
    "收藏",
    "感兴趣",
    "正在看",
    "销量飙升",
)

POLLUTION_TEXT_MARKERS = (
    "加入购物车",
    "立即购买",
    "客服",
    "购物车",
    "商品评价",
    "店铺口碑",
    "开箱精选",
    "本店相关",
    "说点什么",
    "小红书号",
    "关注",
    "粉丝",
    "综合",
    "新品",
    "筛选",
    "首页",
    "消息",
)

DEFAULT_FOCUS_TAPS = 4
DEFAULT_SWIPE_PIXELS = 240
DEFAULT_SWIPE_MS = 900
DEFAULT_ROI = (16, 930, 1064, 1208)


def _roi_signature(path: Path) -> str:
    with Image.open(path) as image:
        small = image.convert("L").resize((48, 12))
        return hashlib.sha256(small.tobytes()).hexdigest()


def _crop_roi(image_path: Path, roi_path: Path, roi: tuple[int, int, int, int]) -> None:
    with Image.open(image_path) as image:
        image.crop(roi).save(roi_path)


def _gray_strip_score(image: Image.Image, roi: tuple[int, int, int, int]) -> float:
    crop = image.crop(roi).convert("RGB")
    data = crop.tobytes()
    if not data:
        return 0.0
    grayish = 0
    for offset in range(0, len(data), 3):
        red, green, blue = data[offset], data[offset + 1], data[offset + 2]
        channel_spread = max(red, green, blue) - min(red, green, blue)
        if 178 <= red <= 250 and 178 <= green <= 250 and 178 <= blue <= 250 and channel_spread <= 18:
            grayish += 1
    return grayish / (len(data) // 3)


def _find_gray_strip_candidates(image_path: Path, *, limit: int = 8) -> list[dict]:
    with Image.open(image_path) as image:
        width, height = image.size
        x1 = max(12, int(width * 0.015))
        x2 = min(width - 12, int(width * 0.985))
        strip_height = max(48, min(72, int(height * 0.032)))
        y_min = int(height * 0.42)
        y_max = int(height * 0.68)
        candidates = []
        for y1 in range(y_min, max(y_min + 1, y_max - strip_height), 12):
            roi = (x1, y1, x2, y1 + strip_height)
            gray_score = _gray_strip_score(image, roi)
            if gray_score >= 0.045:
                center_bias = abs(((y1 + y1 + strip_height) / 2) - (height * 0.55)) / height
                candidates.append(
                    {
                        "roi": roi,
                        "gray_score": round(gray_score, 4),
                        "layout_score": round(gray_score - center_bias, 4),
                    }
                )
    candidates.sort(key=lambda item: (item["layout_score"], item["gray_score"]), reverse=True)
    # Adjacent scan rows often describe the same visual band. Keep vertically
    # diverse candidates so a thumbnail rail cannot crowd the real metric strip
    # out of the OCR stage.
    selected: list[dict] = []
    min_center_gap = max(24, strip_height // 2)
    for candidate in candidates:
        _, y1, _, y2 = candidate["roi"]
        center = (y1 + y2) // 2
        if any(
            abs(center - ((kept["roi"][1] + kept["roi"][3]) // 2)) < min_center_gap
            for kept in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _metric_field_count(signals: ProductSignals) -> int:
    return sum(1 for field in METRIC_FIELDS if getattr(signals, field) is not None) + int(
        signals.sales_surging
    )


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _metric_text_quality(text: str, signals: ProductSignals) -> dict:
    compact = _compact_text(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    marker_hits = sum(1 for marker in METRIC_TEXT_MARKERS if marker in compact)
    metric_fields = _metric_field_count(signals)
    pollution_hits = sum(1 for marker in POLLUTION_TEXT_MARKERS if marker in compact)
    non_metric_lines = sum(
        1
        for line in lines
        if not any(marker in line for marker in METRIC_TEXT_MARKERS)
        and not parse_product_text(line).sales_surging
    )
    incomplete_lines = 0
    for line in lines:
        if not any(marker in line for marker in METRIC_TEXT_MARKERS):
            continue
        line_signals = parse_product_text(line)
        if _metric_field_count(line_signals) == 0 and not line_signals.sales_surging:
            incomplete_lines += 1
    too_sparse = metric_fields == 0 and marker_hits < 2
    polluted = pollution_hits >= 2 and metric_fields <= 1
    half_ocr = incomplete_lines > 0 and metric_fields == 0
    valid = _looks_like_metric_strip(text, signals) and not too_sparse and not polluted and not half_ocr
    reason = None
    if too_sparse:
        reason = "too_sparse"
    elif polluted:
        reason = "polluted"
    elif half_ocr:
        reason = "half_ocr"
    quality_score = (
        metric_fields * 20
        + marker_hits * 4
        - pollution_hits * 8
        - non_metric_lines * 3
        - incomplete_lines * 12
    )
    return {
        "valid": valid,
        "reason": reason,
        "metric_fields": metric_fields,
        "marker_hits": marker_hits,
        "pollution_hits": pollution_hits,
        "non_metric_lines": non_metric_lines,
        "incomplete_lines": incomplete_lines,
        "quality_score": round(quality_score, 4),
    }


def _signals_signature(signals: ProductSignals) -> str:
    values = {
        field: getattr(signals, field)
        for field in METRIC_FIELDS
        if getattr(signals, field) is not None
    }
    values["sales_surging"] = signals.sales_surging
    return json.dumps(values, sort_keys=True, ensure_ascii=False)


def _metric_text_signature(text: str, signals: ProductSignals) -> str:
    normalized = _compact_text(text)
    source = f"{normalized}|{_signals_signature(signals)}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _values_conflict(values: list[int]) -> bool:
    if len(set(values)) <= 1:
        return False
    low = min(values)
    high = max(values)
    return high - low >= 100 or high >= max(2, low * 2)


def _merge_metric_frames(frames: list[dict]) -> tuple[ProductSignals, dict]:
    observations: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    sales_surging = False
    for frame in frames:
        if frame.get("ignored") or frame.get("repeated"):
            continue
        signals = frame.get("_signals_obj")
        if signals is None:
            signals = ProductSignals(**{
                field.name: frame.get("signals", {}).get(field.name)
                for field in fields(ProductSignals)
                if field.name in frame.get("signals", {})
            })
        quality = frame.get("quality") or {}
        quality_score = int(quality.get("quality_score") or 0)
        frame_no = int(frame.get("frame") or 0)
        for field in METRIC_FIELDS:
            value = getattr(signals, field)
            if value is not None:
                observations[field].append((int(value), quality_score, frame_no))
        sales_surging = sales_surging or bool(signals.sales_surging)

    merged = ProductSignals(sales_surging=sales_surging)
    rules: dict[str, dict] = {}
    for field, items in observations.items():
        values = [value for value, _, _ in items]
        counts = Counter(values)
        most_common = counts.most_common()
        if len(most_common) == 1:
            chosen = most_common[0][0]
            rule = "single_value"
        elif most_common[0][1] >= 2:
            consensus_count = most_common[0][1]
            tied = [value for value, count in most_common if count == consensus_count]
            chosen = max(tied)
            rule = "consensus"
        elif _values_conflict(values):
            chosen = min(values)
            rule = "conflict_conservative_min"
        else:
            chosen = max(values)
            rule = "minor_variation_max"
        setattr(merged, field, chosen)
        rules[field] = {
            "values": values,
            "chosen": chosen,
            "rule": rule,
        }
    return merged, rules


def _rank_metric_roi_candidate(candidate: dict, text: str, signals: ProductSignals) -> dict:
    quality = _metric_text_quality(text, signals)
    rank_score = (
        quality["quality_score"]
        + candidate["gray_score"] * 5
        + candidate["layout_score"]
    )
    return {
        "marker_hits": quality["marker_hits"],
        "metric_fields": quality["metric_fields"],
        "non_metric_lines": quality["non_metric_lines"],
        "pollution_hits": quality["pollution_hits"],
        "incomplete_lines": quality["incomplete_lines"],
        "metric_like": quality["valid"],
        "quality": quality,
        "rank_score": round(rank_score, 4),
    }


def locate_metric_strip_roi(
    image_path: Path,
    capture_dir: Path,
) -> dict:
    candidates = _find_gray_strip_candidates(image_path)
    ranked: list[dict] = []
    for index, candidate in enumerate(candidates, start=1):
        roi_path = capture_dir / f"roi-candidate-{index:02d}.png"
        _crop_roi(image_path, roi_path, candidate["roi"])
        text, _ = extract_text(roi_path)
        signals = parse_product_text(text)
        rank = _rank_metric_roi_candidate(candidate, text, signals)
        ranked.append(
            {
                **candidate,
                "roi": list(candidate["roi"]),
                "roi_preview": str(roi_path),
                "text": text,
                **rank,
            }
        )
    ranked.sort(key=lambda item: item["rank_score"], reverse=True)
    chosen = next((item for item in ranked if item["metric_like"]), None)
    return {"chosen": chosen, "candidates": ranked}


def _merge_signals(current: ProductSignals, incoming: ProductSignals) -> bool:
    changed = False
    for field in METRIC_FIELDS:
        old = getattr(current, field)
        new = getattr(incoming, field)
        if new is not None and (old is None or new > old):
            setattr(current, field, new)
            changed = True
    if incoming.sales_surging and not current.sales_surging:
        current.sales_surging = True
        changed = True
    return changed


def has_metrics(signals: ProductSignals | dict) -> bool:
    if isinstance(signals, dict):
        return any(signals.get(field) is not None for field in METRIC_FIELDS) or bool(
            signals.get("sales_surging")
        )
    return any(getattr(signals, field) is not None for field in METRIC_FIELDS) or signals.sales_surging


def _looks_like_metric_strip(text: str, signals: ProductSignals) -> bool:
    compact = "".join(text.split())
    return has_metrics(signals) or any(marker in compact for marker in METRIC_TEXT_MARKERS)


def capture_metrics_strip(
    settings: Settings,
    device: AdbDevice,
    *,
    roi: tuple[int, int, int, int] | None = None,
    max_frames: int = 5,
    allow_swipe: bool = False,
    focus_taps: int = DEFAULT_FOCUS_TAPS,
    swipe_pixels: int | None = DEFAULT_SWIPE_PIXELS,
    swipe_ms: int = DEFAULT_SWIPE_MS,
    pause_seconds: float = 0.8,
) -> dict:
    capture_dir = settings.data_dir / "metric_strips" / utcnow().replace(":", "-")
    capture_dir.mkdir(parents=True, exist_ok=True)
    merged = ProductSignals()
    frames: list[dict] = []
    roi_detection: dict | None = None
    previous_signature: str | None = None
    seen_signatures: set[str] = set()
    seen_text_signatures: set[str] = set()
    no_progress = 0
    first_full_path: Path | None = None
    navigation_guard: dict | None = None
    swipe_guard: dict | None = None

    if roi is None:
        first_full_path = capture_dir / "frame-01.png"
        device.screenshot(first_full_path)
        roi_detection = locate_metric_strip_roi(first_full_path, capture_dir)
        chosen = roi_detection.get("chosen")
        if not chosen:
            return {
                "roi": None,
                "roi_detection": roi_detection,
                "frames": [],
                "signals": merged.as_dict(),
                "text": "",
                "capture_dir": str(capture_dir),
                "skip_reason": "未能在当前截图中自动定位灰色指标条；请手动传入 --roi 后预览。",
            }
        roi = tuple(chosen["roi"])
        weak_visual_candidate = (
            float(chosen.get("gray_score") or 0) < 0.25
            or float(chosen.get("layout_score") or 0) < 0.15
        )
        weak_metric_evidence = (
            int(chosen.get("marker_hits") or 0) == 0
            and int(chosen.get("metric_fields") or 0) <= 1
        )
        if allow_swipe and weak_visual_candidate and weak_metric_evidence:
            allow_swipe = False
            swipe_guard = {
                "stopped": True,
                "reason": (
                    "auto-detected ROI lacks multi-metric strip evidence; "
                    "skipped focus taps and swipe"
                ),
                "gray_score": chosen.get("gray_score"),
                "layout_score": chosen.get("layout_score"),
                "marker_hits": chosen.get("marker_hits"),
                "metric_fields": chosen.get("metric_fields"),
            }

    for index in range(max_frames):
        full_path = capture_dir / f"frame-{index + 1:02d}.png"
        roi_path = capture_dir / f"frame-{index + 1:02d}-roi.png"
        if index == 0 and first_full_path:
            full_path = first_full_path
        else:
            device.screenshot(full_path)
        _crop_roi(full_path, roi_path, roi)
        text, ocr_details = extract_text(roi_path)
        signals = parse_product_text(text)
        signature = _roi_signature(roi_path)
        text_signature = _metric_text_signature(text, signals)
        quality = _metric_text_quality(text, signals)
        metric_like = bool(quality["valid"])
        repeated = signature in seen_signatures or text_signature in seen_text_signatures
        changed = _merge_signals(merged, signals) if metric_like and not repeated else False
        frames.append(
            {
                "frame": index + 1,
                "screenshot": str(full_path),
                "roi": str(roi_path),
                "text": text,
                "signals": signals.as_dict(),
                "ocr": ocr_details,
                "metric_like": metric_like,
                "ignored": not metric_like or repeated,
                "ignore_reason": "repeated" if repeated else quality.get("reason"),
                "quality": quality,
                "changed": changed,
                "repeated": repeated,
                "_signals_obj": signals,
            }
        )

        if index > 0:
            if repeated or not metric_like:
                break
            no_progress = no_progress + 1 if (not changed or repeated) else 0
            if no_progress >= 2:
                break
        previous_signature = signature
        seen_signatures.add(signature)
        seen_text_signatures.add(text_signature)
        if not allow_swipe:
            break
        if index < max_frames - 1:
            x1, y1, x2, y2 = roi
            y = (y1 + y2) // 2
            x = (x1 + x2) // 2
            for tap_index in range(focus_taps):
                device.tap(x, y)
                time.sleep(0.12)
                try:
                    xml_text = device.ui_dump()
                except Exception as exc:
                    navigation_guard = {
                        "stopped": True,
                        "detected": False,
                        "after_focus_tap": tap_index + 1,
                        "reason": f"ui dump failed after focus tap: {exc}",
                    }
                    break
                if not _product_detail_controls_present(xml_text):
                    guard_path = capture_dir / "navigation-guard.png"
                    device.screenshot(guard_path)
                    navigation_guard = {
                        "stopped": True,
                        "detected": True,
                        "after_focus_tap": tap_index + 1,
                        "screenshot": str(guard_path),
                        "reason": "focus tap left product detail; stopped metric swipe and backed out",
                    }
                    device.back()
                    time.sleep(pause_seconds)
                    break
            if navigation_guard:
                break
            if swipe_pixels:
                start_x = min(x2 - 48, x + swipe_pixels // 2)
                end_x = max(x1 + 48, start_x - swipe_pixels)
            else:
                start_x = x2 - 48
                end_x = x1 + 48
            device.swipe(start_x, y, end_x, y, swipe_ms)
            time.sleep(pause_seconds)

    merged, merge_rules = _merge_metric_frames(frames)
    public_frames = []
    for frame in frames:
        public_frame = dict(frame)
        public_frame.pop("_signals_obj", None)
        public_frames.append(public_frame)

    return {
        "roi": roi,
        "roi_detection": roi_detection,
        "frames": public_frames,
        "signals": merged.as_dict(),
        "text": "\n".join(
            frame["text"] for frame in public_frames if frame["text"] and not frame.get("ignored")
        ),
        "capture_dir": str(capture_dir),
        "navigation_guard": navigation_guard,
        "swipe_guard": swipe_guard,
        "merge_rules": merge_rules,
    }


def update_observation_with_metrics(
    settings: Settings,
    observation_id: int,
    metrics: dict,
) -> dict:
    incoming = ProductSignals(**{
        field.name: metrics["signals"].get(field.name)
        for field in fields(ProductSignals)
        if field.name in metrics["signals"]
    })
    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT o.*, p.title, p.shop_name, p.price, p.is_virtual, p.virtual_confidence
            FROM observations o
            JOIN products p ON p.id=o.product_id
            WHERE o.id=?
            """,
            (observation_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"观察记录不存在：{observation_id}")

        merged = ProductSignals(
            title=row["title"],
            shop_name=row["shop_name"],
            price=row["price"],
            cumulative_sales_display=row["cumulative_sales_display"],
            cumulative_sales_exact=row["cumulative_sales_exact"],
            cumulative_sales_min=row["cumulative_sales_min"],
            sales_24h_min=row["sales_24h_min"],
            sales_7d_min=row["sales_7d_min"],
            sales_30d_min=row["sales_30d_min"],
            cart_24h_min=row["cart_24h_min"],
            new_30d_min=row["new_30d_min"],
            positive_reviews_30d_min=row["positive_reviews_30d_min"],
            favorites_30d_min=row["favorites_30d_min"],
            interested_7d_min=row["interested_7d_min"],
            interested_30d_min=row["interested_30d_min"],
            viewers_now=row["viewers_now"],
            sales_surging=bool(row["sales_surging"]),
            is_virtual=bool(row["is_virtual"]) if row["is_virtual"] is not None else None,
            virtual_confidence=row["virtual_confidence"] or 0.0,
        )
        _merge_signals(merged, incoming)

        raw = json.loads(row["raw_signals_json"] or "{}")
        raw["metrics_strip"] = {
            "roi": metrics["roi"],
            "roi_detection": metrics.get("roi_detection"),
            "merge_rules": metrics.get("merge_rules", {}),
            "navigation_guard": metrics.get("navigation_guard"),
            "frames": [
                {
                    "frame": frame["frame"],
                    "screenshot": frame["screenshot"],
                    "roi": frame["roi"],
                    "text": frame["text"],
                    "signals": frame["signals"],
                    "metric_like": frame.get("metric_like"),
                    "ignored": frame.get("ignored"),
                    "changed": frame["changed"],
                    "repeated": frame["repeated"],
                }
                for frame in metrics["frames"]
            ],
        }
        conn.execute(
            """
            UPDATE observations
            SET cumulative_sales_display=?, cumulative_sales_exact=?,
                cumulative_sales_min=?, sales_24h_min=?, sales_7d_min=?,
                sales_30d_min=?, cart_24h_min=?, new_30d_min=?, positive_reviews_30d_min=?,
                favorites_30d_min=?, interested_7d_min=?, viewers_now=?,
                interested_30d_min=?, sales_surging=?, raw_signals_json=?
            WHERE id=?
            """,
            (
                merged.cumulative_sales_display,
                merged.cumulative_sales_exact,
                merged.cumulative_sales_min,
                merged.sales_24h_min,
                merged.sales_7d_min,
                merged.sales_30d_min,
                merged.cart_24h_min,
                merged.new_30d_min,
                merged.positive_reviews_30d_min,
                merged.favorites_30d_min,
                merged.interested_7d_min,
                merged.viewers_now,
                merged.interested_30d_min,
                int(merged.sales_surging),
                json.dumps(raw, ensure_ascii=False),
                observation_id,
            ),
        )
        score, reasons, grade = candidate_score(merged)
        gray_items = gray_metric_items(metrics)
        reasons.append(f"有效灰色指标条{len(gray_items)}个")
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score, reasons_json, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["product_id"],
                utcnow(),
                grade,
                score,
                json.dumps(reasons, ensure_ascii=False),
                "candidate" if len(gray_items) >= 3 else "observed",
            ),
        )
    return {
        "observation_id": observation_id,
        "signals": merged.as_dict(),
        "gray_metric_count": len(gray_items),
        "gray_metric_items": list(gray_items),
        "score": score,
        "grade": grade,
        "reasons": reasons,
    }
