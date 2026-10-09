from __future__ import annotations

from dataclasses import dataclass
import math
import re
from pathlib import Path
from typing import Any, Callable

from PIL import Image


MIN_OCR_CONFIDENCE = 0.80
MIN_BOX_COVERAGE = 0.80
COMPACT_TITLE_MIN_WIDTH_RATIO = 0.75


@dataclass(frozen=True)
class NormalizedRoi:
    left: float
    top: float
    right: float
    bottom: float

    def pixels(self, width: int, height: int) -> tuple[float, float, float, float]:
        return (
            self.left * width,
            self.top * height,
            self.right * width,
            self.bottom * height,
        )

    def as_list(self) -> list[float]:
        return [self.left, self.top, self.right, self.bottom]


@dataclass(frozen=True)
class FieldSpec:
    roi: NormalizedRoi
    parser: Callable[[str], Any]
    multiline: bool = False


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _price(value: str) -> float:
    matches = re.findall(r"\d+(?:\.\d+)?", value.replace(",", ""))
    if len(matches) != 1:
        raise ValueError("price_roi_must_contain_exactly_one_number")
    return float(matches[0])


def _count(value: str) -> int:
    matches = re.findall(r"(\d+(?:\.\d+)?)(万)?", value.replace(",", ""))
    if len(matches) != 1:
        raise ValueError("count_roi_must_contain_exactly_one_number")
    number, unit = matches[0]
    result = float(number) * (10_000 if unit == "万" else 1)
    return int(result)


# These bands are calibrated against saved 1080x2340 Redmi product-detail
# layouts. Variant selection is geometry-only and never reads OCR text.
PLAIN_TITLE_ROI = NormalizedRoi(0.02, 0.665, 0.98, 0.710)
COMPACT_TITLE_ROI = NormalizedRoi(0.02, 0.765, 0.98, 0.825)
EXTENDED_TITLE_ROI = NormalizedRoi(0.02, 0.825, 0.98, 0.900)
PLAIN_PRICE_ROI = NormalizedRoi(0.00, 0.625, 0.22, 0.675)
COMPACT_PRICE_ROI = NormalizedRoi(0.18, 0.625, 0.55, 0.675)
PROMOTION_PRICE_ROI = NormalizedRoi(0.18, 0.685, 0.55, 0.750)


PAGE_FIELD_SPECS: dict[str, dict[str, FieldSpec]] = {
    "product_detail": {
        "title": FieldSpec(
            EXTENDED_TITLE_ROI,
            _plain_text,
            multiline=True,
        ),
        "price": FieldSpec(
            PROMOTION_PRICE_ROI,
            _price,
        ),
        "shop_entry": FieldSpec(
            NormalizedRoi(0.00, 0.930, 0.15, 0.980),
            _plain_text,
        ),
    },
    "shop_product_list": {
        "shop_name": FieldSpec(
            NormalizedRoi(0.20, 0.100, 0.56, 0.150),
            _plain_text,
        ),
        "follower_count": FieldSpec(
            NormalizedRoi(0.20, 0.160, 0.40, 0.205),
            _count,
        ),
    },
}


def _image_size(
    screenshot: str | Path | None,
    image_size: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if image_size is not None:
        width, height = image_size
        return (int(width), int(height)) if width > 0 and height > 0 else None
    if not screenshot:
        return None
    try:
        with Image.open(screenshot) as image:
            return int(image.width), int(image.height)
    except (OSError, ValueError):
        return None


def _normalized_box(detail: object) -> dict[str, Any] | None:
    if not isinstance(detail, dict):
        return None
    raw_box = detail.get("box")
    if not isinstance(raw_box, (list, tuple)) or len(raw_box) < 4:
        return None
    try:
        points = [[float(point[0]), float(point[1])] for point in raw_box]
        confidence = float(detail.get("confidence"))
    except (TypeError, ValueError, IndexError):
        return None
    text = str(detail.get("text") or "").strip()
    if not text:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
    if right <= left or bottom <= top:
        return None
    return {
        "box": points,
        "text": text,
        "confidence": confidence,
        "bounds": [left, top, right, bottom],
    }


def json_safe_ocr_details(ocr_details: object) -> list[dict[str, Any]]:
    """Convert OCR engine values (including numpy scalars) to JSON-safe data."""

    if not isinstance(ocr_details, (list, tuple)):
        return []
    safe: list[dict[str, Any]] = []
    for detail in ocr_details:
        item = _normalized_box(detail)
        if item is None:
            safe.append(
                {
                    "box": None,
                    "text": str(detail.get("text") or "")
                    if isinstance(detail, dict)
                    else "",
                    "confidence": None,
                    "invalid": True,
                }
            )
            continue
        safe.append(
            {
                "box": item["box"],
                "text": item["text"],
                "confidence": item["confidence"],
            }
        )
    return safe


def _overlap_ratio(
    bounds: list[float],
    roi: tuple[float, float, float, float],
) -> float:
    left, top, right, bottom = bounds
    roi_left, roi_top, roi_right, roi_bottom = roi
    overlap_width = max(0.0, min(right, roi_right) - max(left, roi_left))
    overlap_height = max(0.0, min(bottom, roi_bottom) - max(top, roi_top))
    return (overlap_width * overlap_height) / ((right - left) * (bottom - top))


def _belongs(
    bounds: list[float],
    roi: tuple[float, float, float, float],
) -> bool:
    left, top, right, bottom = bounds
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    roi_left, roi_top, roi_right, roi_bottom = roi
    return (
        roi_left <= center_x <= roi_right
        and roi_top <= center_y <= roi_bottom
        and _overlap_ratio(bounds, roi) >= MIN_BOX_COVERAGE
    )


def _product_title_variant(
    boxes: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> tuple[str | None, dict[str, Any]]:
    def candidates_in(roi: NormalizedRoi) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        pixels = roi.pixels(width, height)
        candidates = []
        for item in boxes:
            if item["confidence"] < MIN_OCR_CONFIDENCE:
                continue
            if not _belongs(item["bounds"], pixels):
                continue
            left, _top, right, _bottom = item["bounds"]
            candidates.append(
                {
                    "box": item["box"],
                    "confidence": item["confidence"],
                    "width_ratio": round((right - left) / width, 6),
                }
            )
        wide = [
            item
            for item in candidates
            if item["width_ratio"] >= COMPACT_TITLE_MIN_WIDTH_RATIO
        ]
        return candidates, wide

    plain_candidates, plain_wide = candidates_in(PLAIN_TITLE_ROI)
    compact_candidates, compact_wide = candidates_in(COMPACT_TITLE_ROI)
    if len(plain_wide) == 1 and not compact_wide:
        variant = "plain"
        reason = "exactly_one_wide_box_in_plain_candidate_band"
    elif len(compact_wide) == 1 and not plain_wide:
        variant = "compact"
        reason = "exactly_one_wide_box_in_compact_candidate_band"
    elif not plain_wide and not compact_wide:
        variant = "extended"
        reason = "no_wide_box_in_plain_or_compact_candidate_band"
    else:
        variant = None
        reason = "ambiguous_wide_boxes_across_product_title_bands"
    compact_pixels = COMPACT_TITLE_ROI.pixels(width, height)
    plain_pixels = PLAIN_TITLE_ROI.pixels(width, height)
    return variant, {
        "method": "product_title_candidate_box_width",
        "plain_candidate_roi": {
            "normalized": PLAIN_TITLE_ROI.as_list(),
            "pixels": [round(value, 3) for value in plain_pixels],
        },
        "candidate_roi": {
            "normalized": COMPACT_TITLE_ROI.as_list(),
            "pixels": [round(value, 3) for value in compact_pixels],
        },
        "minimum_width_ratio": COMPACT_TITLE_MIN_WIDTH_RATIO,
        "plain_candidate_boxes": plain_candidates,
        "candidate_boxes": compact_candidates,
        "plain_wide_box_count": len(plain_wide),
        "wide_box_count": len(compact_wide),
        "decision_reason": reason,
    }


def _field_result(
    *,
    field_name: str,
    page_kind: str,
    screenshot: str | None,
    spec: FieldSpec,
    width: int,
    height: int,
    boxes: list[dict[str, Any]],
) -> dict[str, Any]:
    roi_pixels = spec.roi.pixels(width, height)
    geometric = [item for item in boxes if _belongs(item["bounds"], roi_pixels)]
    evidence = {
        "field_name": field_name,
        "field_value": None,
        "page_kind": page_kind,
        "screenshot": screenshot,
        "roi": {
            "normalized": spec.roi.as_list(),
            "pixels": [round(value, 3) for value in roi_pixels],
        },
        "matches": [
            {
                "box": item["box"],
                "text": item["text"],
                "confidence": item["confidence"],
            }
            for item in geometric
        ],
        "status": "missing",
        "reason": "no_ocr_box_assigned_to_roi",
    }
    if not geometric:
        return evidence
    if any(item["confidence"] < MIN_OCR_CONFIDENCE for item in geometric):
        evidence.update(
            status="low_confidence",
            reason=f"assigned_box_below_{MIN_OCR_CONFIDENCE:.2f}",
        )
        return evidence
    if not spec.multiline and len(geometric) != 1:
        evidence.update(
            status="conflict",
            reason="scalar_field_has_multiple_assigned_boxes",
        )
        return evidence

    ordered = sorted(
        geometric,
        key=lambda item: (
            round((item["bounds"][1] + item["bounds"][3]) / 2 / 12),
            item["bounds"][0],
        ),
    )
    raw_value = "".join(item["text"] for item in ordered)
    try:
        field_value = spec.parser(raw_value)
    except (TypeError, ValueError) as exc:
        evidence.update(status="invalid_value", reason=str(exc))
        return evidence
    if field_value in (None, ""):
        evidence.update(status="invalid_value", reason="empty_value_after_parsing")
        return evidence
    evidence.update(field_value=field_value, status="ok", reason=None)
    return evidence


def extract_layout_fields(
    *,
    page_kind: str,
    ocr_details: list[dict] | tuple[dict, ...] | None,
    screenshot: str | Path | None,
    image_size: tuple[int, int] | None = None,
    field_ocr_details: dict[str, list[dict] | tuple[dict, ...]] | None = None,
    field_ocr_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Assign OCR boxes to predeclared fields without whole-page inference."""

    screenshot_text = str(screenshot) if screenshot is not None else None
    specs = PAGE_FIELD_SPECS.get(page_kind)
    if specs is None:
        return {
            "page_kind": page_kind,
            "screenshot": screenshot_text,
            "status": "unsupported_page",
            "image_size": None,
            "fields": {},
            "invalid_ocr_boxes": [],
        }
    size = _image_size(screenshot, image_size)
    if size is None:
        return {
            "page_kind": page_kind,
            "screenshot": screenshot_text,
            "status": "invalid_image_size",
            "image_size": None,
            "fields": {
                name: {
                    "field_name": name,
                    "field_value": None,
                    "page_kind": page_kind,
                    "screenshot": screenshot_text,
                    "roi": {"normalized": spec.roi.as_list(), "pixels": None},
                    "matches": [],
                    "status": "invalid_image_size",
                    "reason": "screenshot_dimensions_unavailable",
                }
                for name, spec in specs.items()
            },
            "invalid_ocr_boxes": [],
        }

    width, height = size
    boxes: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, detail in enumerate(ocr_details or []):
        item = _normalized_box(detail)
        if item is None:
            invalid.append({"index": index, "reason": "malformed_ocr_box"})
            continue
        left, top, right, bottom = item["bounds"]
        if left < 0 or top < 0 or right > width or bottom > height:
            invalid.append(
                {
                    "index": index,
                    "reason": "ocr_box_out_of_image_bounds",
                    "box": item["box"],
                    "text": item["text"],
                    "confidence": item["confidence"],
                }
            )
            continue
        boxes.append(item)

    layout_variant = None
    layout_signature = None
    if page_kind == "product_detail":
        layout_variant, layout_signature = _product_title_variant(
            boxes,
            width=width,
            height=height,
        )
        title_roi = {
            "plain": PLAIN_TITLE_ROI,
            "compact": COMPACT_TITLE_ROI,
            "extended": EXTENDED_TITLE_ROI,
        }.get(layout_variant, EXTENDED_TITLE_ROI)
        selected_title_spec = FieldSpec(
            title_roi,
            _plain_text,
            multiline=True,
        )
        compact_high_price_boxes: list[dict[str, Any]] = []
        if layout_variant == "compact":
            compact_price_pixels = COMPACT_PRICE_ROI.pixels(width, height)
            compact_high_price_boxes = [
                item
                for item in boxes
                if item["confidence"] >= MIN_OCR_CONFIDENCE
                and _belongs(item["bounds"], compact_price_pixels)
            ]
        price_roi = {
            "plain": PLAIN_PRICE_ROI,
            "compact": (
                COMPACT_PRICE_ROI
                if compact_high_price_boxes
                else PROMOTION_PRICE_ROI
            ),
            "extended": PROMOTION_PRICE_ROI,
        }.get(layout_variant, PROMOTION_PRICE_ROI)
        if layout_variant == "compact" and layout_signature is not None:
            layout_signature["compact_price_band"] = (
                "high" if compact_high_price_boxes else "low"
            )
            layout_signature["compact_high_price_box_count"] = len(
                compact_high_price_boxes
            )
        selected_price_spec = FieldSpec(
            price_roi,
            _price,
        )
        specs = {
            **specs,
            "title": selected_title_spec,
            "price": selected_price_spec,
        }

    targeted_boxes: dict[str, list[dict[str, Any]]] = {}
    for field_name, details in (field_ocr_details or {}).items():
        prepared: list[dict[str, Any]] = []
        for detail in details or []:
            item = _normalized_box(detail)
            if item is None:
                continue
            left, top, right, bottom = item["bounds"]
            if left < 0 or top < 0 or right > width or bottom > height:
                continue
            prepared.append(item)
        targeted_boxes[field_name] = prepared

    fields = {
        name: _field_result(
            field_name=name,
            page_kind=page_kind,
            screenshot=screenshot_text,
            spec=spec,
            width=width,
            height=height,
            boxes=targeted_boxes[name] if name in targeted_boxes else boxes,
        )
        for name, spec in specs.items()
    }
    for name, source in (field_ocr_sources or {}).items():
        if name in fields:
            fields[name]["ocr_source"] = "fixed_roi_crop"
            fields[name]["roi_crop"] = source
    if page_kind == "product_detail":
        title = fields["title"]
        title["layout_variant"] = layout_variant
        title["signature"] = layout_signature
        title["selected_roi"] = title["roi"] if layout_variant else None
        if layout_variant is None:
            title.update(
                field_value=None,
                status="ambiguous_layout_variant",
                reason=layout_signature["decision_reason"],
                matches=[],
            )
    for invalid_item in invalid:
        raw_box = invalid_item.get("box")
        if not raw_box:
            continue
        xs = [point[0] for point in raw_box]
        ys = [point[1] for point in raw_box]
        bounds = [min(xs), min(ys), max(xs), max(ys)]
        for name, spec in specs.items():
            if _belongs(bounds, spec.roi.pixels(width, height)):
                fields[name].update(
                    field_value=None,
                    status="out_of_bounds",
                    reason="assigned_ocr_box_exceeds_image_bounds",
                    matches=[
                        {
                            "box": raw_box,
                            "text": invalid_item.get("text"),
                            "confidence": invalid_item.get("confidence"),
                        }
                    ],
                )
    statuses = {field["status"] for field in fields.values()}
    status = "ok" if statuses == {"ok"} and not invalid else "partial"
    return {
        "page_kind": page_kind,
        "screenshot": screenshot_text,
        "status": status,
        "image_size": {"width": width, "height": height},
        "layout_variant": layout_variant,
        "layout_signature": layout_signature,
        "fields": fields,
        "invalid_ocr_boxes": invalid,
    }


def extract_layout_fields_with_roi_ocr(
    *,
    page_kind: str,
    ocr_details: list[dict] | tuple[dict, ...] | None,
    screenshot: str | Path | None,
    ocr_runner: Callable[[Path], tuple[str, list[dict]]],
    crop_dir: str | Path,
) -> dict[str, Any]:
    """先按几何分型，再对每个固定坐标框单独OCR。

    整页OCR只用于页面分型和其他非字段信号。标题、价格、店铺入口、店铺名和
    粉丝数的最终值只来自各自的固定ROI裁剪，避免小字号价格在整页OCR中漏掉。
    """

    initial = extract_layout_fields(
        page_kind=page_kind,
        ocr_details=ocr_details,
        screenshot=screenshot,
    )
    if initial.get("status") in {"unsupported_page", "invalid_image_size"}:
        return initial
    fields = initial.get("fields")
    if not isinstance(fields, dict) or not screenshot:
        return initial

    destination = Path(crop_dir)
    destination.mkdir(parents=True, exist_ok=True)
    translated: dict[str, list[dict]] = {}
    sources: dict[str, str] = {}
    with Image.open(screenshot) as image:
        for field_name, field in fields.items():
            if not isinstance(field, dict):
                continue
            if field_name == "title" and initial.get("layout_variant") is None:
                continue
            roi = field.get("roi")
            pixels = roi.get("pixels") if isinstance(roi, dict) else None
            if not isinstance(pixels, list) or len(pixels) != 4:
                continue
            left = max(0, math.floor(float(pixels[0])))
            top = max(0, math.floor(float(pixels[1])))
            right = min(image.width, math.ceil(float(pixels[2])))
            bottom = min(image.height, math.ceil(float(pixels[3])))
            if right <= left or bottom <= top:
                continue
            crop_path = destination / f"{field_name}.png"
            image.crop((left, top, right, bottom)).save(crop_path)
            _text, local_details = ocr_runner(crop_path)
            global_details: list[dict] = []
            for detail in json_safe_ocr_details(local_details):
                box = detail.get("box")
                if not box:
                    continue
                global_details.append(
                    {
                        "box": [
                            [float(point[0]) + left, float(point[1]) + top]
                            for point in box
                        ],
                        "text": detail.get("text"),
                        "confidence": detail.get("confidence"),
                    }
                )
            translated[field_name] = global_details
            sources[field_name] = str(crop_path)

    return extract_layout_fields(
        page_kind=page_kind,
        ocr_details=ocr_details,
        screenshot=screenshot,
        field_ocr_details=translated,
        field_ocr_sources=sources,
    )


def layout_field_value(layout: object, field_name: str) -> Any:
    if not isinstance(layout, dict):
        return None
    fields = layout.get("fields")
    if not isinstance(fields, dict):
        return None
    field = fields.get(field_name)
    if not isinstance(field, dict) or field.get("status") != "ok":
        return None
    return field.get("field_value")
