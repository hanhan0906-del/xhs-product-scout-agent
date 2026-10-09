from __future__ import annotations

import time
from pathlib import Path

from .config import Settings
from .coupon_overlay import (
    COUPON_ACTIVITY,
    coupon_overlay_text_present,
    find_coupon_close_button,
)
from .db import connect, record_note_observation, record_run_event
from .emulator import AdbDevice
from .layout_fields import layout_field_value
from .note_observation import parse_account_profile_text
from .probe import probe_current_page
from .ui_automation import Bounds, UiTarget, find_product_shop_entry


def _backfill_product_shop_name(conn, product_id: int, shop_name: str | None) -> None:
    value = (shop_name or "").strip()
    if not value:
        return
    conn.execute(
        """
        UPDATE products
        SET shop_name=CASE
            WHEN shop_name IS NULL OR TRIM(shop_name)='' THEN ?
            ELSE shop_name
        END
        WHERE id=?
        """,
        (value, product_id),
    )


def _read_ui(probe: dict) -> str:
    xml_path = Path(probe["probe_dir"]) / "window.xml"
    if not xml_path.exists():
        return ""
    return xml_path.read_text(encoding="utf-8", errors="replace")


def _layout_shop_entry_target(probe: dict) -> UiTarget | None:
    """当UI树被瞬时底层覆盖污染时，只信固定ROI里的唯一“店铺”证据。"""

    if probe.get("page_kind") != "product_detail":
        return None
    layout = probe.get("layout_fields")
    fields = layout.get("fields") if isinstance(layout, dict) else None
    field = fields.get("shop_entry") if isinstance(fields, dict) else None
    if (
        not isinstance(field, dict)
        or field.get("status") != "ok"
        or str(field.get("field_value") or "").strip() != "店铺"
    ):
        return None
    matches = field.get("matches")
    image_size = layout.get("image_size") if isinstance(layout, dict) else None
    if not isinstance(matches, list) or len(matches) != 1 or not isinstance(image_size, dict):
        return None
    box = matches[0].get("box") if isinstance(matches[0], dict) else None
    try:
        xs = [int(round(float(point[0]))) for point in box]
        ys = [int(round(float(point[1]))) for point in box]
        width = int(image_size["width"])
        height = int(image_size["height"])
    except (TypeError, ValueError, KeyError):
        return None
    bounds = Bounds(min(xs), min(ys), max(xs), max(ys))
    if (
        bounds.area <= 0
        or bounds.y1 < int(height * 0.85)
        or bounds.x2 > int(width * 0.25)
    ):
        return None
    x, y = bounds.center
    return UiTarget(
        x=x,
        y=y,
        bounds=bounds,
        label="店铺",
        reason="fixed-layout-roi=shop_entry",
    )


def _pidof(device: AdbDevice, package: str) -> str | None:
    method = getattr(device, "pidof", None)
    return method(package) if callable(method) else None


def _activity_dump(device: AdbDevice) -> str:
    method = getattr(device, "activity_dump", None)
    return method() if callable(method) else ""


def _process_changed(before: str | None, after: str | None) -> bool:
    return before is not None and before != after


def _explicit_coupon_detail(probe: dict) -> bool:
    return (
        probe.get("page_kind") == "product_detail"
        and COUPON_ACTIVITY in (probe.get("activity") or "")
        and coupon_overlay_text_present(probe.get("text") or "")
    )


def _probe_stop_reason(probe: dict, stage: str) -> str | None:
    if probe.get("has_anr"):
        return f"{stage}_anr"
    if probe.get("risk_stop_reason"):
        return f"{stage}_risk_stop"
    return None


def parse_seller_profile_probe(probe: dict) -> dict:
    if probe.get("page_kind") == "shop_product_list":
        layout = probe.get("layout_fields")
        return {
            "author_name": layout_field_value(layout, "shop_name"),
            "follower_count": layout_field_value(layout, "follower_count"),
            "likes": None,
            "collects": None,
            "comments": None,
            "published_days_ago": None,
        }
    return parse_account_profile_text(probe.get("text") or "")


def capture_seller_profile_from_product(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    product_id: int,
    wait_seconds: float = 5.0,
) -> dict:
    before = probe_current_page(
        settings,
        device,
        run_id=f"{run_id}-seller-before-{task_id}",
    )
    if stop_reason := _probe_stop_reason(before, "seller_before"):
        return {
            "blocked": True,
            "reason": stop_reason,
            "before_probe": before,
        }
    already_in_shop = (
        before.get("page_kind") == "shop_product_list"
        and any(
            marker in (before.get("activity") or "")
            for marker in (
                "GoodsDetailActivity",
                "ShopDetailActivity",
                COUPON_ACTIVITY,
            )
        )
    )
    if before.get("page_kind") != "product_detail" and not already_in_shop:
        return {
            "blocked": True,
            "reason": f"seller capture requires product_detail, got {before.get('page_kind')}",
            "before_probe": before,
        }

    target = None
    retry_target = None
    coupon_observed = coupon_overlay_text_present(before.get("text") or "")
    coupon_fast_screenshot: str | None = None
    coupon_recovery_probe = None
    if already_in_shop:
        after = before
    else:
        package = str(
            settings.emulator_config().get("package") or "com.xingin.xhs"
        )
        process_before = _pidof(device, package)
        detail_probe = before
        if _explicit_coupon_detail(before):
            # The translucent coupon Activity exposes the product-detail XML
            # underneath it, so tapping the apparent shop target is unsafe and
            # ineffective. Back is the only allowed dismissal action here: do
            # not click the coupon close glyph, "立即使用", or purchase controls.
            device.back()
            time.sleep(wait_seconds)
            coupon_recovery_probe = probe_current_page(
                settings,
                device,
                run_id=f"{run_id}-seller-after-coupon-back-{task_id}",
            )
            process_after_coupon_back = _pidof(device, package)
            if process_before is None or process_after_coupon_back is None:
                return {
                    "blocked": True,
                    "reason": "coupon_dismiss_process_identity_unknown",
                    "process_change": {
                        "before": process_before,
                        "after": process_after_coupon_back,
                    },
                    "before_probe": before,
                    "coupon_recovery_probe": coupon_recovery_probe,
                }
            if _process_changed(process_before, process_after_coupon_back):
                return {
                    "blocked": True,
                    "reason": "coupon_dismiss_process_crash",
                    "process_change": {
                        "before": process_before,
                        "after": process_after_coupon_back,
                    },
                    "before_probe": before,
                    "coupon_recovery_probe": coupon_recovery_probe,
                }
            if stop_reason := _probe_stop_reason(
                coupon_recovery_probe,
                "seller_after_coupon_back",
            ):
                return {
                    "blocked": True,
                    "reason": stop_reason,
                    "before_probe": before,
                    "coupon_recovery_probe": coupon_recovery_probe,
                }
            if coupon_recovery_probe.get("page_kind") != "product_detail":
                return {
                    "blocked": True,
                    "reason": (
                        "coupon dismissal left product detail: "
                        f"{coupon_recovery_probe.get('page_kind')}"
                    ),
                    "before_probe": before,
                    "coupon_recovery_probe": coupon_recovery_probe,
                }
            detail_probe = coupon_recovery_probe

        target = find_product_shop_entry(_read_ui(detail_probe)) or _layout_shop_entry_target(
            detail_probe
        )
        if not target:
            return {
                "skipped": True,
                "skip_reason": "商品详情页未找到店铺入口",
                "before_probe": before,
                "coupon_recovery_probe": coupon_recovery_probe,
                "task_disposition": {
                    "retryable": True,
                    "reason": "shop_entry_not_found",
                },
            }

        device.tap(target.x, target.y)
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while time.monotonic() < deadline:
            process_now = _pidof(device, package)
            if _process_changed(process_before, process_now):
                return {
                    "blocked": True,
                    "reason": "shop_open_process_crash",
                    "process_change": {"before": process_before, "after": process_now},
                    "before_probe": before,
                }
            if COUPON_ACTIVITY in _activity_dump(device):
                coupon_dir = settings.data_dir / "probes" / f"{run_id}-seller-coupon-{task_id}"
                coupon_dir.mkdir(parents=True, exist_ok=True)
                coupon_path = device.screenshot(coupon_dir / "current.png")
                coupon_fast_screenshot = str(coupon_path)
                coupon_observed = True
                break
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        after = probe_current_page(
            settings,
            device,
            run_id=f"{run_id}-seller-after-{task_id}",
        )
        process_after = _pidof(device, package)
        if _process_changed(process_before, process_after):
            return {
                "blocked": True,
                "reason": "shop_open_process_crash",
                "process_change": {"before": process_before, "after": process_after},
                "before_probe": before,
                "after_probe": after,
            }
        if stop_reason := _probe_stop_reason(after, "seller_after_shop_tap"):
            return {
                "blocked": True,
                "reason": stop_reason,
                "before_probe": before,
                "after_probe": after,
            }
        coupon_observed = coupon_observed or coupon_overlay_text_present(
            after.get("text") or ""
        )

        # A coupon can appear only after the ordinary shop tap. Recover it at
        # most once, prove that Back returned to the same safe detail context,
        # then resolve a fresh strict shop target and retry that target once.
        if _explicit_coupon_detail(after):
            device.back()
            time.sleep(wait_seconds)
            coupon_recovery_probe = probe_current_page(
                settings,
                device,
                run_id=f"{run_id}-seller-after-coupon-back-{task_id}",
            )
            process_after_coupon_back = _pidof(device, package)
            if process_before is None or process_after_coupon_back is None:
                return {
                    "blocked": True,
                    "reason": "coupon_dismiss_process_identity_unknown",
                    "process_change": {
                        "before": process_before,
                        "after": process_after_coupon_back,
                    },
                    "before_probe": before,
                    "after_probe": after,
                    "coupon_recovery_probe": coupon_recovery_probe,
                }
            if _process_changed(process_before, process_after_coupon_back):
                return {
                    "blocked": True,
                    "reason": "coupon_dismiss_process_crash",
                    "process_change": {
                        "before": process_before,
                        "after": process_after_coupon_back,
                    },
                    "before_probe": before,
                    "after_probe": after,
                    "coupon_recovery_probe": coupon_recovery_probe,
                }
            if stop_reason := _probe_stop_reason(
                coupon_recovery_probe,
                "seller_after_coupon_back",
            ):
                return {
                    "blocked": True,
                    "reason": stop_reason,
                    "before_probe": before,
                    "after_probe": after,
                    "coupon_recovery_probe": coupon_recovery_probe,
                }
            if coupon_recovery_probe.get("page_kind") != "product_detail":
                return {
                    "blocked": True,
                    "reason": (
                        "coupon dismissal left product detail: "
                        f"{coupon_recovery_probe.get('page_kind')}"
                    ),
                    "before_probe": before,
                    "after_probe": after,
                    "coupon_recovery_probe": coupon_recovery_probe,
                }
            retry_target = find_product_shop_entry(
                _read_ui(coupon_recovery_probe)
            ) or _layout_shop_entry_target(coupon_recovery_probe)
            if retry_target is None:
                return {
                    "skipped": True,
                    "skip_reason": "shop_entry_not_opened",
                    "before_probe": before,
                    "after_probe": after,
                    "coupon_recovery_probe": coupon_recovery_probe,
                    "target": {
                        "x": target.x,
                        "y": target.y,
                        "label": target.label,
                    },
                    "task_disposition": {
                        "retryable": True,
                        "reason": "shop_entry_not_opened",
                    },
                }
            device.tap(retry_target.x, retry_target.y)
            time.sleep(wait_seconds)
            after = probe_current_page(
                settings,
                device,
                run_id=f"{run_id}-seller-after-retry-{task_id}",
            )
            process_after_retry = _pidof(device, package)
            if _process_changed(process_before, process_after_retry):
                return {
                    "blocked": True,
                    "reason": "shop_open_process_crash",
                    "process_change": {
                        "before": process_before,
                        "after": process_after_retry,
                    },
                    "before_probe": before,
                    "coupon_recovery_probe": coupon_recovery_probe,
                    "after_probe": after,
                }
            if stop_reason := _probe_stop_reason(after, "seller_after_shop_retry"):
                return {
                    "blocked": True,
                    "reason": stop_reason,
                    "before_probe": before,
                    "coupon_recovery_probe": coupon_recovery_probe,
                    "after_probe": after,
                }

        if (
            COUPON_ACTIVITY in (after.get("activity") or "")
            and after.get("page_kind")
            not in {"shop_product_list", "account_profile"}
        ):
            return {
                "blocked": True,
                "reason": "unrecognized_translucent_activity_after_shop_tap",
                "before_probe": before,
                "after_probe": after,
                "target": {
                    "x": target.x,
                    "y": target.y,
                    "label": target.label,
                },
            }
        if after.get("page_kind") == "product_detail":
            return {
                "skipped": True,
                "skip_reason": "shop_entry_not_opened",
                "before_probe": before,
                "coupon_recovery_probe": coupon_recovery_probe,
                "after_probe": after,
                "target": {
                    "x": target.x,
                    "y": target.y,
                    "label": target.label,
                },
                "retry_target": (
                    {
                        "x": retry_target.x,
                        "y": retry_target.y,
                        "label": retry_target.label,
                    }
                    if retry_target is not None
                    else None
                ),
                "task_disposition": {
                    "retryable": True,
                    "reason": "shop_entry_not_opened",
                },
            }
        if after.get("page_kind") not in {"shop_product_list", "account_profile"}:
            return {
                "blocked": True,
                "reason": f"店铺入口打开了未知页面：{after.get('page_kind')}",
                "before_probe": before,
                "after_probe": after,
            }

    # Once the probe has strictly identified a shop page and the safety gates
    # above have passed, its OCR is evidence in its own right. Persist it before
    # attempting navigation recovery: a translucent coupon/follow layer must
    # not hide an already-visible follower count merely because its copy is new.
    shop_translucent_observed = (
        after.get("page_kind") in {"shop_product_list", "account_profile"}
        and COUPON_ACTIVITY in (after.get("activity") or "")
    )
    parsed = parse_seller_profile_probe(after)
    follower_count = parsed.get("follower_count")
    follower_display_status = (
        "visible" if follower_count is not None else "not_displayed"
    )
    low_follower_qualified = bool(
        follower_count is not None and 1 <= int(follower_count) <= 2_000
    )
    with connect(settings.db_path) as conn:
        # Without a visible follower count, nearby shop-page OCR is not a
        # sufficiently precise identity anchor. Preserve it as raw evidence,
        # but never let a noisy author-name guess overwrite the product shop.
        if follower_count is not None:
            _backfill_product_shop_name(conn, product_id, parsed.get("author_name"))
        observation_id = record_note_observation(
            conn,
            product_id=product_id,
            source="seller_profile_from_product",
            screenshot_path=after.get("screenshot"),
            probe_dir=after.get("probe_dir"),
            page_kind=after.get("page_kind"),
            raw_text=after.get("text"),
            raw={
                "entry": "already_open_shop_product_list" if already_in_shop else "店铺",
                "target": (
                    {"x": target.x, "y": target.y, "label": target.label}
                    if target is not None
                    else None
                ),
                "retry_target": (
                    {
                        "x": retry_target.x,
                        "y": retry_target.y,
                        "label": retry_target.label,
                    }
                    if retry_target is not None
                    else None
                ),
                "coupon_close": None,
                "coupon_observed": coupon_observed,
                "coupon_fast_screenshot": coupon_fast_screenshot,
                "follower_display_status": follower_display_status,
                "low_follower_qualified": low_follower_qualified,
                "layout_fields": after.get("layout_fields"),
            },
            **parsed,
        )
        record_run_event(
            conn,
            run_id=run_id,
            phase="seller_profile",
            event="seller_profile_observation_recorded",
            task_id=task_id,
            product_id=product_id,
            message=f"note_observation_id={observation_id}",
            data={
                "parsed": parsed,
                "page_kind": after.get("page_kind"),
                "follower_display_status": follower_display_status,
                "low_follower_qualified": low_follower_qualified,
            },
        )

    coupon_close = None
    if shop_translucent_observed:
        close_failure = None
        if after.get("risk_stop_reason"):
            close_failure = "seller_coupon_close_risk_stop"
        elif after.get("has_anr"):
            close_failure = "seller_coupon_close_anr"
        current_pid = str(_pidof(device, package) or "").strip()
        close_target = find_coupon_close_button(after.get("screenshot") or "")
        if close_failure is None and not current_pid:
            close_failure = "seller_coupon_close_pid_unknown"
        if close_failure is None and close_target is None:
            close_failure = "seller_coupon_close_unique_visual_target_missing"
        if close_failure is not None:
            return {
                "blocked": True,
                "reason": close_failure,
                "before_probe": before,
                "after_probe": after,
                "parsed": parsed,
                "note_observation_id": observation_id,
                "follower_display_status": follower_display_status,
                "low_follower_qualified": low_follower_qualified,
            }

        coupon_close = {
            "target": {
                "x": close_target.x,
                "y": close_target.y,
                "bounds": {
                    "x1": close_target.bounds.x1,
                    "y1": close_target.bounds.y1,
                    "x2": close_target.bounds.x2,
                    "y2": close_target.bounds.y2,
                },
                "reason": close_target.reason,
            },
            "pid_before": current_pid,
        }
        device.tap(close_target.x, close_target.y)
        time.sleep(wait_seconds)
        closed_shop = probe_current_page(
            settings,
            device,
            run_id=f"{run_id}-seller-coupon-closed-{task_id}",
        )
        pid_after_close = str(_pidof(device, package) or "").strip()
        coupon_close["pid_after"] = pid_after_close or None
        coupon_close["after_probe"] = closed_shop
        if not pid_after_close or pid_after_close != current_pid:
            return {
                "blocked": True,
                "reason": "seller_coupon_close_pid_changed",
                "before_probe": before,
                "after_probe": after,
                "coupon_close": coupon_close,
                "parsed": parsed,
                "note_observation_id": observation_id,
                "follower_display_status": follower_display_status,
                "low_follower_qualified": low_follower_qualified,
            }
        if closed_shop.get("risk_stop_reason") or closed_shop.get("has_anr"):
            return {
                "blocked": True,
                "reason": (
                    "seller_coupon_close_post_risk_stop"
                    if closed_shop.get("risk_stop_reason")
                    else "seller_coupon_close_post_anr"
                ),
                "before_probe": before,
                "after_probe": after,
                "coupon_close": coupon_close,
                "parsed": parsed,
                "note_observation_id": observation_id,
                "follower_display_status": follower_display_status,
                "low_follower_qualified": low_follower_qualified,
            }
        closed_activity = str(closed_shop.get("activity") or "")
        if (
            COUPON_ACTIVITY in closed_activity
            or closed_shop.get("page_kind")
            not in {"shop_product_list", "account_profile"}
            or "ShopDetailActivity" not in closed_activity
        ):
            return {
                "blocked": True,
                "reason": "seller_coupon_close_unknown_or_abnormal_destination",
                "before_probe": before,
                "after_probe": after,
                "coupon_close": coupon_close,
                "parsed": parsed,
                "note_observation_id": observation_id,
                "follower_display_status": follower_display_status,
                "low_follower_qualified": low_follower_qualified,
            }
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="seller_profile",
                event="seller_coupon_closed_by_unique_visual_x",
                task_id=task_id,
                product_id=product_id,
                data=coupon_close,
            )

    device.back()
    time.sleep(wait_seconds)
    recovered = probe_current_page(
        settings,
        device,
        run_id=f"{run_id}-seller-recovered-{task_id}",
    )
    process_after_recovery = (
        _pidof(device, package) if not already_in_shop else None
    )
    if not already_in_shop and _process_changed(
        process_before,
        process_after_recovery,
    ):
        return {
            "blocked": True,
            "reason": "seller_recovery_process_crash",
            "process_change": {
                "before": process_before,
                "after": process_after_recovery,
            },
            "before_probe": before,
            "after_probe": after,
            "recovery_probe": recovered,
            "parsed": parsed,
            "note_observation_id": observation_id,
            "follower_display_status": follower_display_status,
            "low_follower_qualified": low_follower_qualified,
        }
    if stop_reason := _probe_stop_reason(recovered, "seller_recovery"):
        return {
            "blocked": True,
            "reason": stop_reason,
            "before_probe": before,
            "after_probe": after,
            "recovery_probe": recovered,
            "parsed": parsed,
            "note_observation_id": observation_id,
            "follower_display_status": follower_display_status,
            "low_follower_qualified": low_follower_qualified,
        }
    if (
        (coupon_observed or shop_translucent_observed)
        and recovered.get("page_kind") in {"shop_product_list", "account_profile"}
    ):
        device.back()
        time.sleep(wait_seconds)
        recovered = probe_current_page(
            settings,
            device,
            run_id=f"{run_id}-seller-recovered-after-shop-{task_id}",
        )
        process_after_second_recovery = (
            _pidof(device, package) if not already_in_shop else None
        )
        if not already_in_shop and _process_changed(
            process_before,
            process_after_second_recovery,
        ):
            return {
                "blocked": True,
                "reason": "seller_recovery_process_crash",
                "process_change": {
                    "before": process_before,
                    "after": process_after_second_recovery,
                },
                "before_probe": before,
                "after_probe": after,
                "recovery_probe": recovered,
                "parsed": parsed,
                "note_observation_id": observation_id,
                "follower_display_status": follower_display_status,
                "low_follower_qualified": low_follower_qualified,
            }
    if (
        recovered.get("risk_stop_reason")
        or recovered.get("has_anr")
        or recovered.get("page_kind") != "product_detail"
    ):
        return {
            "blocked": True,
            "reason": f"店铺粉丝采集后未回到商品详情：{recovered.get('page_kind')}",
            "before_probe": before,
            "after_probe": after,
            "recovery_probe": recovered,
            "parsed": parsed,
            "note_observation_id": observation_id,
            "follower_display_status": follower_display_status,
            "low_follower_qualified": low_follower_qualified,
        }
    return {
        "parsed": parsed,
        "note_observation_id": observation_id,
        "follower_display_status": follower_display_status,
        "low_follower_qualified": low_follower_qualified,
        "before_probe": before,
        "after_probe": after,
        "recovery_probe": recovered,
    }
