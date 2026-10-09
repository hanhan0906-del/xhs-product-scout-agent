from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Settings
from .db import connect, utcnow
from .layout_fields import (
    extract_layout_fields_with_roi_ocr,
    json_safe_ocr_details,
    layout_field_value,
)
from .ocr import OcrTimeoutError, extract_text
from .probe import _visible_ui_tree_text, classify_page_evidence
from .signals import (
    candidate_score,
    detect_risk_stop,
    fingerprint,
    has_product_evidence,
    ProductSignals,
    parse_product_text,
)
from .vision_fields import (
    VisionFieldsError,
    extract_product_fields_with_vision,
    vision_fields_enabled,
)


_SHANGHAI_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
_MIDNIGHT_DELAY_LIMIT = timedelta(minutes=15)


def _parse_shanghai_midnight_sample(value: str | None) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        local = parsed.astimezone(_SHANGHAI_TIMEZONE)
    except (TypeError, ValueError, OverflowError):
        return None

    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if local - midnight > _MIDNIGHT_DELAY_LIMIT:
        return None
    return local


def calculate_daily_sales_delta(
    *,
    previous_exact: int | None,
    previous_at: str | None,
    current_exact: int | None,
    current_at: str,
) -> int | None:
    if (
        type(previous_exact) is not int
        or type(current_exact) is not int
        or previous_exact < 0
        or current_exact < previous_exact
    ):
        return None

    previous_local = _parse_shanghai_midnight_sample(previous_at)
    current_local = _parse_shanghai_midnight_sample(current_at)
    if previous_local is None or current_local is None:
        return None
    if (current_local.date() - previous_local.date()).days != 1:
        return None
    return current_exact - previous_exact


def persist_ingest_result(
    settings: Settings,
    output: dict,
    *,
    conn=None,
) -> dict:
    """Persist a successfully analyzed image without running OCR a second time."""

    if output.get("product_id") and output.get("observation_id"):
        return output
    deferred = output.get("_deferred_ingest")
    if not isinstance(deferred, dict):
        raise ValueError("ingest output is not eligible for deferred persistence")

    observed_at = str(deferred["observed_at"])
    destination = str(output["stored"])
    raw_text = str(output.get("text") or "")
    ocr_details = list(deferred.get("ocr") or [])
    deferred_signals = deferred.get("signals")
    signals = (
        ProductSignals(**deferred_signals)
        if isinstance(deferred_signals, dict)
        else parse_product_text(raw_text)
    )
    layout_fields = deferred.get("layout_fields") or output.get("layout_fields")
    vision_fields = deferred.get("vision_fields") or output.get("vision_fields")
    fp = str(deferred["fingerprint"])
    score = float(output["score"])
    reasons = list(output["reasons"])
    grade = str(output["evidence_grade"])

    def _persist(db_conn) -> tuple[int, int]:
        db_conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, shop_name, price, is_virtual, virtual_confidence,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                title=COALESCE(excluded.title, products.title),
                shop_name=COALESCE(excluded.shop_name, products.shop_name),
                price=COALESCE(excluded.price, products.price),
                is_virtual=COALESCE(excluded.is_virtual, products.is_virtual),
                virtual_confidence=MAX(excluded.virtual_confidence, products.virtual_confidence),
                last_seen_at=excluded.last_seen_at
            """,
            (
                fp,
                signals.title,
                signals.shop_name,
                signals.price,
                int(signals.is_virtual) if signals.is_virtual is not None else None,
                signals.virtual_confidence,
                observed_at,
                observed_at,
            ),
        )
        product_id = db_conn.execute(
            "SELECT id FROM products WHERE fingerprint=?", (fp,)
        ).fetchone()[0]
        previous = db_conn.execute(
            """
            SELECT cumulative_sales_exact, observed_at
            FROM observations
            WHERE product_id=? AND cumulative_sales_exact IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (product_id,),
        ).fetchone()
        daily_sales_delta = calculate_daily_sales_delta(
            previous_exact=previous["cumulative_sales_exact"] if previous else None,
            previous_at=previous["observed_at"] if previous else None,
            current_exact=signals.cumulative_sales_exact,
            current_at=observed_at,
        )
        db_conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, screenshot_path, raw_text,
                cumulative_sales_display, cumulative_sales_exact,
                cumulative_sales_min, daily_sales_delta,
                sales_24h_min, sales_7d_min, cart_24h_min,
                sales_30d_min, new_30d_min, positive_reviews_30d_min, favorites_30d_min,
                interested_7d_min, interested_30d_min,
                viewers_now, sales_surging, raw_signals_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                observed_at,
                output.get("source") or "mobile_screenshot",
                destination,
                raw_text,
                signals.cumulative_sales_display,
                signals.cumulative_sales_exact,
                signals.cumulative_sales_min,
                daily_sales_delta,
                signals.sales_24h_min,
                signals.sales_7d_min,
                signals.cart_24h_min,
                signals.sales_30d_min,
                signals.new_30d_min,
                signals.positive_reviews_30d_min,
                signals.favorites_30d_min,
                signals.interested_7d_min,
                signals.interested_30d_min,
                signals.viewers_now,
                int(signals.sales_surging),
                json.dumps(
                    {
                        "signals": signals.as_dict(),
                        "ocr": ocr_details,
                        "layout_fields": layout_fields,
                        "vision_fields": vision_fields,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        observation_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score, reasons_json, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                observed_at,
                grade,
                score,
                json.dumps(reasons, ensure_ascii=False),
                "observed",
            ),
        )
        return int(product_id), int(observation_id)

    if conn is None:
        with connect(settings.db_path) as owned_conn:
            product_id, observation_id = _persist(owned_conn)
    else:
        product_id, observation_id = _persist(conn)

    output["product_id"] = product_id
    output["observation_id"] = observation_id
    output.pop("_deferred_ingest", None)
    return output


def ingest_image(
    settings: Settings,
    image_path: Path,
    *,
    source: str = "mobile_screenshot",
    activity: str | None = None,
    ui_tree: str = "",
    required_page_kind: str | None = None,
    run_id: str | None = None,
    task_id: int | None = None,
    persist: bool = True,
) -> dict:
    image_path = image_path.resolve()
    observed_at = utcnow()
    destination = settings.capture_dir / f"{observed_at.replace(':', '-')}_{image_path.name}"
    if image_path != destination:
        shutil.copy2(image_path, destination)

    try:
        raw_text, ocr_details = extract_text(destination)
        ocr_details = json_safe_ocr_details(ocr_details)
    except OcrTimeoutError as exc:
        xml_path: Path | None = None
        xml_error: str | None = None
        if ui_tree:
            xml_path = destination.with_suffix(".xml")
            try:
                xml_path.write_text(ui_tree, encoding="utf-8")
            except OSError as xml_exc:
                xml_error = f"{type(xml_exc).__name__}: {xml_exc}"
                xml_path = None
        evidence = {
            "screenshot": str(destination),
            "xml": str(xml_path) if xml_path else None,
            "xml_error": xml_error,
            "activity": activity,
        }
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return {
            "image": str(image_path),
            "stored": str(destination),
            "text": "",
            "page_kind": "ocr_timeout",
            "required_page_kind": required_page_kind,
            "risk_stopped": True,
            "risk_stop_reason": str(exc),
            "reason_code": "ocr_timeout",
            "infrastructure_failure": True,
            "hard_stop": True,
            "ocr_timeout": {
                "reason_code": "ocr_timeout",
                "run_id": run_id,
                "task_id": task_id,
                "exception": error,
                "evidence": evidence,
            },
            "exception": error,
            "evidence": evidence,
            "run_id": run_id,
            "task_id": task_id,
        }
    visible_ui_text = _visible_ui_tree_text(ui_tree)
    combined_visible_text = (
        f"{raw_text}\n{visible_ui_text}" if visible_ui_text else raw_text
    )
    risk_stop_reason = detect_risk_stop(combined_visible_text)
    if risk_stop_reason:
        return {
            "image": str(image_path),
            "stored": str(destination),
            "text": raw_text,
            "risk_stopped": True,
            "risk_stop_reason": risk_stop_reason,
            "page_kind": "risk_stop",
            "page_kind_source": "ocr_ui_guard",
        }

    page_kind, page_kind_source = classify_page_evidence(
        raw_text,
        activity=activity,
        ui_tree=ui_tree,
    )
    if required_page_kind and page_kind != required_page_kind:
        return {
            "image": str(image_path),
            "stored": str(destination),
            "text": raw_text,
            "page_kind": page_kind,
            "page_kind_source": page_kind_source,
            "required_page_kind": required_page_kind,
            "page_kind_mismatch": True,
        }
    layout_fields = extract_layout_fields_with_roi_ocr(
        page_kind=page_kind,
        ocr_details=ocr_details,
        screenshot=destination,
        ocr_runner=lambda path: extract_text(path),
        crop_dir=destination.parent / ".layout-roi" / destination.stem,
    )
    signals = parse_product_text(raw_text)
    vision_fields = None
    if page_kind == "product_detail":
        try:
            vision_config = settings.vision_fields_config()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise VisionFieldsError(
                "vision_config_invalid",
                f"无法读取视觉字段配置：{exc}",
                evidence={
                    "config": str(settings.root / "config" / "vision_fields.json"),
                    "screenshot": str(destination),
                },
            ) from exc
        if vision_fields_enabled(vision_config):
            # 正式商品仅在这个入库前调用点推理一次。页面探测、店铺往返与
            # 其他OCR阶段不调用模型，避免同一商品重复消耗约130秒。
            vision_fields = extract_product_fields_with_vision(
                destination,
                vision_config,
            )
            signals.title = vision_fields["title"]
            signals.price = vision_fields["price"]
        else:
            # 未启用本地视觉模型的离线/测试根目录继续使用既有布局字段。
            signals.title = layout_field_value(layout_fields, "title")
            signals.price = layout_field_value(layout_fields, "price")
        signals.shop_name = None
    if not has_product_evidence(signals):
        return {
            "image": str(image_path),
            "stored": str(destination),
            "text": raw_text,
            "signals": signals.as_dict(),
            "layout_fields": layout_fields,
            "page_kind": page_kind,
            "page_kind_source": page_kind_source,
            "skipped": True,
            "skip_reason": "未识别到商品标题、店铺或销量等强商品信号",
        }

    # 标题或店铺存在时使用稳定的商品语义指纹，避免同一商品因截图压缩大小变化
    # 被重复创建。只有缺少这两项时才退回到截图身份。
    image_identity = None
    if not signals.title and not signals.shop_name:
        image_identity = f"image:{image_path.name}:{image_path.stat().st_size}"
    fp = fingerprint(signals.title, signals.shop_name, image_identity)
    score, reasons, grade = candidate_score(signals)

    output = {
        "image": str(image_path),
        "stored": str(destination),
        "source": source,
        "text": raw_text,
        "signals": signals.as_dict(),
        "layout_fields": layout_fields,
        "vision_fields": vision_fields,
        "page_kind": page_kind,
        "page_kind_source": page_kind_source,
        "score": score,
        "evidence_grade": grade,
        "reasons": reasons,
        "_deferred_ingest": {
            "observed_at": observed_at,
            "fingerprint": fp,
            "ocr": ocr_details,
            "signals": signals.as_dict(),
            "layout_fields": layout_fields,
            "vision_fields": vision_fields,
        },
    }
    if not persist:
        return output
    return persist_ingest_result(settings, output)
