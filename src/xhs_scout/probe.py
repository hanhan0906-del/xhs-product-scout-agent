from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import Settings
from .db import connect, record_run_event, utcnow
from .emulator import AdbDevice
from .layout_fields import extract_layout_fields_with_roi_ocr, json_safe_ocr_details
from .ocr import OcrTimeoutError, OcrWorkerError, extract_text
from .signals import classify_page_text, detect_risk_stop


def is_ocr_timeout_probe(value: object) -> bool:
    """Return whether *value* is a complete OCR-infrastructure-failure probe
    contract: either an OCR deadline timeout or a supervised worker crash.
    Both mean the page was never actually read, so both are handled through
    the same hard-stop/refund path."""

    if not isinstance(value, dict):
        return False
    exception = value.get("exception")
    return (
        value.get("page_kind") == "ocr_timeout"
        and value.get("ocr_timeout") is True
        and value.get("reason_code") == "ocr_timeout"
        and value.get("infrastructure_failure") is True
        and isinstance(exception, dict)
        and exception.get("type") in ("OcrTimeoutError", "OcrWorkerError")
    )


def _current_focus(window_dump: str) -> str | None:
    matches = re.findall(
        r"(?m)^\s*mCurrentFocus=Window\{[^}]*?\bu\d+\s+(.+?)\}\s*$",
        window_dump,
    )
    return matches[-1] if matches else None


def _focused_activity(window_dump: str) -> str | None:
    return _current_focus(window_dump)


def _has_current_anr(window_dump: str, visible_text: str) -> bool:
    """Detect only a currently visible ANR, not Android's historical record."""
    visible_markers = (
        "没有响应",
        "无响应",
        "application not responding",
        "appnotrespondingdialog",
    )
    combined = f"{_current_focus(window_dump) or ''}\n{visible_text}".casefold()
    return any(marker.casefold() in combined for marker in visible_markers)


def _classify_page_ui_tree(ui_tree: str) -> str | None:
    """Use a narrow UI-tree fallback when screenshot OCR misses the search header."""
    if not ui_tree.strip():
        return None
    try:
        root = ET.fromstring(ui_tree)
    except ET.ParseError:
        return None
    for node in root.iter():
        if not node.attrib.get("class", "").endswith("EditText"):
            continue
        bounds = re.fullmatch(
            r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
            node.attrib.get("bounds", ""),
        )
        if not bounds or int(bounds.group(2)) > 140:
            continue
        label = " ".join(
            value.strip()
            for value in (
                node.attrib.get("text", ""),
                node.attrib.get("content-desc", ""),
            )
            if value.strip()
        )
        if "搜索" in label and node.attrib.get("clickable") == "true":
            return "search_input"
    return None


def _classify_global_search_results_ui_tree(
    activity: str | None,
    ui_tree: str,
) -> str | None:
    """Recognize the real result-tab structure under a guide overlay.

    This fallback is intentionally narrower than OCR classification: it only
    applies to GlobalSearchActivity, requires a populated top query control,
    and requires the complete visible result-tab set.  It never dismisses or
    interacts with the overlay.
    """

    if "GlobalSearchActivity" not in (activity or "") or not ui_tree.strip():
        return None
    try:
        root = ET.fromstring(ui_tree)
    except ET.ParseError:
        return None

    expected_tabs = {"全部", "用户", "商品", "图片", "视频"}
    visible_tabs: set[str] = set()
    has_top_query = False
    for node in root.iter():
        bounds = re.fullmatch(
            r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
            node.attrib.get("bounds", ""),
        )
        if not bounds:
            continue
        y1 = int(bounds.group(2))
        y2 = int(bounds.group(4))
        label = " ".join(
            value.strip()
            for value in (
                node.attrib.get("text", ""),
                node.attrib.get("content-desc", ""),
            )
            if value.strip()
        )
        if (
            y1 <= 220
            and y2 <= 240
            and label not in {"", "搜索", "搜索商品"}
            and (
                node.attrib.get("clickable") == "true"
                or node.attrib.get("focusable") == "true"
            )
        ):
            has_top_query = True
        if 220 <= y1 <= 380 and label in expected_tabs:
            visible_tabs.add(label)
    if has_top_query and visible_tabs == expected_tabs:
        return "search_results"
    return None


def _classify_product_detail_ui_tree(
    activity: str | None,
    ui_tree: str,
) -> str | None:
    """Recognize a real goods-detail Activity when OCR omits one score marker.

    This is deliberately stricter than text scoring.  It requires the exact
    Xiaohongshu goods-detail Activity, the complete navigation/control shell,
    and both price and sold-count evidence.  It only classifies the page and
    never interacts with any transaction control.
    """

    if "GoodsDetailActivityV2" not in (activity or "") or not ui_tree.strip():
        return None
    try:
        root = ET.fromstring(ui_tree)
    except ET.ParseError:
        return None

    labels: set[str] = set()
    descriptions: set[str] = set()
    has_price = False
    has_sold = False
    for node in root.iter():
        text = node.attrib.get("text", "").strip()
        description = node.attrib.get("content-desc", "").strip()
        if text:
            labels.add(text)
            has_price = has_price or bool(re.fullmatch(r"[¥￥]\s*\d+(?:\.\d+)?", text))
            has_sold = has_sold or bool(re.fullmatch(r"已售\s*\d+(?:\.\d+)?万?\+?", text))
        if description:
            descriptions.add(description)
            has_price = has_price or description.startswith("商品价格，")
            has_sold = has_sold or "已售" in description

    header_controls = {"返回", "搜索商品", "分享商品"}
    bottom_controls = {"店铺", "客服", "购物车", "加入购物车"}
    purchase_controls = {"立即购买", "领券购买"}
    if (
        header_controls.issubset(descriptions)
        and bottom_controls.issubset(labels)
        and bool(purchase_controls.intersection(labels))
        and has_price
        and has_sold
    ):
        return "product_detail"
    return None


def _visible_ui_tree_text(ui_tree: str) -> str:
    """Return visible labels used only for fail-closed page guards."""

    if not ui_tree.strip():
        return ""
    try:
        root = ET.fromstring(ui_tree)
    except ET.ParseError:
        return ""
    values: list[str] = []
    for node in root.iter():
        for key in ("text", "content-desc"):
            value = node.attrib.get(key, "").strip()
            if value:
                values.append(value)
    return "\n".join(values)


def classify_page_evidence(
    text: str,
    *,
    activity: str | None = None,
    ui_tree: str = "",
) -> tuple[str, str]:
    """Classify one page from OCR plus contemporaneous Android evidence.

    Text risk/forbidden signals always win.  Positive UI fallbacks are only
    used when OCR is unknown, and the goods-detail fallback retains the exact
    Activity and complete control-shell requirements above.
    """

    text_kind = classify_page_text(text)
    ui_text = _visible_ui_tree_text(ui_tree)
    combined = f"{text}\n{ui_text}" if ui_text else text
    guarded_kind = classify_page_text(combined)
    if guarded_kind in {"risk_stop", "forbidden_interaction_area", "open_error"}:
        return guarded_kind, "ocr_ui_guard"
    if text_kind != "unknown":
        return text_kind, "ocr"
    if not ui_tree:
        return "unknown", "ocr"

    if _classify_product_detail_ui_tree(activity, ui_tree) == "product_detail":
        return "product_detail", "strict_product_detail_ui"
    if _classify_global_search_results_ui_tree(activity, ui_tree) == "search_results":
        return "search_results", "strict_search_results_ui"
    ui_kind = _classify_page_ui_tree(ui_tree)
    if ui_kind:
        return ui_kind, "strict_search_input_ui"
    return "unknown", "ocr_ui_unclassified"


def probe_current_page(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str | None = None,
    include_ui_tree: bool = True,
) -> dict:
    run_id = run_id or f"probe-{utcnow().replace(':', '-')}"
    probe_dir = settings.data_dir / "probes" / run_id
    probe_dir.mkdir(parents=True, exist_ok=True)

    window_dump = device.window_focus()
    activity = _focused_activity(window_dump)
    (probe_dir / "window.txt").write_text(window_dump, encoding="utf-8")
    screenshot = device.screenshot(probe_dir / "current.png")
    try:
        text, ocr = extract_text(screenshot)
        ocr = json_safe_ocr_details(ocr)
    except (OcrTimeoutError, OcrWorkerError) as exc:
        # Both exceptions mean the OCR subsystem itself failed to produce a
        # result (deadline exceeded, or the supervised worker crashed/exited
        # -- e.g. a truncated screenshot it could not decode). Either way the
        # page was never actually read, so both route through the same
        # OCR-infrastructure hard-stop/refund contract (see
        # is_ocr_timeout_probe); the real exception type and message are
        # preserved below for diagnosis.
        event = "ocr_timeout" if isinstance(exc, OcrTimeoutError) else "ocr_worker_error"
        result = {
            "run_id": run_id,
            "probe_dir": str(probe_dir),
            "activity": activity,
            "has_anr": _has_current_anr(window_dump, ""),
            "risk_stop_reason": str(exc),
            "page_kind": "ocr_timeout",
            "screenshot": str(screenshot),
            "text": "",
            "ocr_count": 0,
            "ocr_timeout": True,
            "ocr_error": str(exc),
            "reason_code": "ocr_timeout",
            "infrastructure_failure": True,
            "exception": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
            "ui_dump_ok": False,
            "ui_error": None,
        }
        (probe_dir / "probe.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="probe",
                event=event,
                level="warning",
                message=str(exc),
                data={
                    "activity": activity,
                    "has_anr": result["has_anr"],
                    "page_kind": result["page_kind"],
                    "probe_dir": str(probe_dir),
                },
            )
        return result
    ui_tree = ""
    ui_error = None
    if include_ui_tree:
        try:
            ui_tree = device.ui_dump()
            (probe_dir / "window.xml").write_text(ui_tree, encoding="utf-8")
        except Exception as exc:
            ui_error = str(exc)
    visible_ui_text = _visible_ui_tree_text(ui_tree)
    combined_visible_text = f"{text}\n{visible_ui_text}" if visible_ui_text else text
    has_anr = _has_current_anr(window_dump, combined_visible_text)
    risk_stop_reason = detect_risk_stop(combined_visible_text)
    page_kind, page_kind_source = classify_page_evidence(
        text,
        activity=activity,
        ui_tree=ui_tree,
    )
    layout_fields = extract_layout_fields_with_roi_ocr(
        page_kind=page_kind,
        ocr_details=ocr,
        screenshot=screenshot,
        ocr_runner=lambda path: extract_text(path),
        crop_dir=probe_dir / "layout-roi",
    )

    result = {
        "run_id": run_id,
        "probe_dir": str(probe_dir),
        "activity": activity,
        "has_anr": has_anr,
        "risk_stop_reason": risk_stop_reason,
        "page_kind": page_kind,
        "page_kind_source": page_kind_source,
        "screenshot": str(screenshot),
        "text": text,
        "ocr_count": len(ocr),
        "ocr": ocr,
        "layout_fields": layout_fields,
        "ui_dump_ok": bool(ui_tree),
        "ui_error": ui_error,
    }
    (probe_dir / "probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with connect(settings.db_path) as conn:
        record_run_event(
            conn,
            run_id=run_id,
            phase="probe",
            event="current_page_probed",
            level="warning" if result["has_anr"] or risk_stop_reason else "info",
            message=risk_stop_reason or activity,
            data={
                "activity": activity,
                "has_anr": result["has_anr"],
                "risk_stop_reason": risk_stop_reason,
                "page_kind": page_kind,
                "probe_dir": str(probe_dir),
            },
        )
    return result
