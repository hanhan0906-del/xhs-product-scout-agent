from __future__ import annotations

import re
import sqlite3
import subprocess
import time
import uuid
from typing import Any

from .config import Settings
from .db import connect
from .emulator import (
    AdbDevice,
    discover_adb,
    discover_bluestacks_player,
    select_device_serial,
    select_mdns_connect_address,
)
from .probe import probe_current_page
from .product_link import (
    is_supported_product_direct_url,
    resolve_product_launch_url,
)
from .signals import parse_product_text


class DirectLinkDailySalesCollector:
    """Open one frozen product link and read only its visible sales value."""

    def __init__(
        self,
        settings: Settings,
        *,
        device: AdbDevice | None = None,
        wait_seconds: float = 6.0,
    ) -> None:
        self.settings = settings
        self.device = device or _device(settings)
        self.wait_seconds = max(0.0, float(wait_seconds))

    def __call__(self, *, product_id: int, verified_direct_url: str) -> dict[str, Any]:
        observed_at = _observed_at()
        if not is_supported_product_direct_url(verified_direct_url):
            return _hard_stop(
                observed_at,
                "identity_unknown",
                "stored product target is not a verified durable Xiaohongshu product URL",
            )

        try:
            expected = self._expected_product(product_id)
        except sqlite3.OperationalError as error:
            reason = (
                "database_lock_error"
                if "locked" in str(error).casefold()
                or "busy" in str(error).casefold()
                else "unknown_page"
            )
            return _hard_stop(observed_at, reason, str(error))
        if expected is None or not expected["title"]:
            return _hard_stop(
                observed_at,
                "identity_unknown",
                "followed product identity is missing",
            )

        launch = resolve_product_launch_url(
            expected["share_url"],
            verified_direct_url,
        )
        if not launch.get("launch_url"):
            return _hard_stop(
                observed_at,
                "identity_unknown",
                str(launch.get("skip_reason") or "product launch URL is unavailable"),
            )

        try:
            self.device.open_url(str(launch["launch_url"]))
            time.sleep(self.wait_seconds)
            probe = probe_current_page(
                self.settings,
                self.device,
                run_id=f"daily-sales-{product_id}-{uuid.uuid4().hex[:10]}",
                include_ui_tree=False,
            )
        except subprocess.TimeoutExpired as error:
            return self._retry_after_app_recovery(
                product_id=product_id,
                verified_direct_url=verified_direct_url,
                observed_at=observed_at,
                trigger=f"ADB timeout: {error}",
            )
        except sqlite3.OperationalError as error:
            reason = (
                "database_lock_error"
                if "locked" in str(error).casefold()
                or "busy" in str(error).casefold()
                else "unknown_page"
            )
            return _hard_stop(observed_at, reason, str(error))
        except Exception as error:
            return _hard_stop(
                observed_at,
                "unknown_page",
                f"{type(error).__name__}: {error}",
            )
        observed_at = _observed_at()

        if probe.get("has_anr"):
            return self._retry_after_app_recovery(
                product_id=product_id,
                verified_direct_url=verified_direct_url,
                observed_at=observed_at,
                trigger="ANR detected after opening product link",
            )
        if probe.get("risk_stop_reason"):
            visible_reason = str(probe["risk_stop_reason"])
            return _hard_stop(
                observed_at,
                (
                    "ocr_timeout"
                    if probe.get("page_kind") == "ocr_timeout"
                    else "captcha"
                    if "验证码" in visible_reason
                    else "risk_control"
                ),
                visible_reason,
            )
        if probe.get("page_kind") != "product_detail":
            return _hard_stop(
                observed_at,
                "unknown_page",
                f"direct link opened {probe.get('page_kind') or 'unknown'}",
            )

        signals = parse_product_text(probe.get("text") or "")
        if not _identity_matches(
            expected_title=str(expected["title"]),
            observed_title=signals.title,
            page_text=probe.get("text") or "",
        ):
            return _hard_stop(
                observed_at,
                "identity_unknown",
                "visible product title does not match the followed product",
            )

        if signals.cumulative_sales_exact is not None:
            result = {
                "kind": "exact",
                "observed_product_id": product_id,
                "observed_at": observed_at,
                "cumulative_sales_exact": signals.cumulative_sales_exact,
                "cumulative_sales_display": signals.cumulative_sales_display,
                "probe_dir": probe.get("probe_dir"),
            }
        elif signals.cumulative_sales_display:
            result = {
                "kind": "fuzzy",
                "observed_product_id": product_id,
                "observed_at": observed_at,
                "cumulative_sales_display": signals.cumulative_sales_display,
                "probe_dir": probe.get("probe_dir"),
            }
        else:
            return {
                "kind": "failed",
                "observed_product_id": product_id,
                "observed_at": observed_at,
                "reason_code": "sales_not_visible",
                "reason_detail": "product detail opened but cumulative sales was not visible",
                "probe_dir": probe.get("probe_dir"),
            }

        self.device.back()
        time.sleep(min(self.wait_seconds, 1.5))
        return result

    def _retry_after_app_recovery(
        self,
        *,
        product_id: int,
        verified_direct_url: str,
        observed_at: str,
        trigger: str,
    ) -> dict[str, Any]:
        recovery = self._recover_app_once(product_id=product_id, trigger=trigger)
        if not recovery["recovered"]:
            return _hard_stop(
                observed_at,
                recovery["reason_code"],
                recovery["reason_detail"],
            )
        result = self(
            product_id=product_id,
            verified_direct_url=verified_direct_url,
        )
        result["app_recovery"] = recovery
        return result

    def _recover_app_once(self, *, product_id: int, trigger: str) -> dict[str, Any]:
        config = self.settings.emulator_config()
        package = str(config.get("package") or "com.xingin.xhs")
        instance = str(config.get("instance") or "Rvc64")
        backend = str(config.get("backend") or "bluestacks").strip().casefold()
        try:
            self.device.force_stop(package, timeout=15)
            if backend == "android":
                self.device.launch_android_package(package)
            else:
                player = discover_bluestacks_player(config.get("player_path"))
                self.device.launch_with_bluestacks_player(player, instance, package)
            time.sleep(max(3.0, self.wait_seconds))
            probe = probe_current_page(
                self.settings,
                self.device,
                run_id=f"daily-sales-{product_id}-probe-after-app-recovery",
                include_ui_tree=False,
            )
        except Exception as error:
            return {
                "attempted": True,
                "recovered": False,
                "reason_code": "anr",
                "reason_detail": (
                    f"{trigger}; app-only recovery failed: "
                    f"{type(error).__name__}: {error}"
                ),
            }
        if probe.get("has_anr"):
            return {
                "attempted": True,
                "recovered": False,
                "reason_code": "anr",
                "reason_detail": f"{trigger}; ANR remained after app restart",
            }
        if probe.get("risk_stop_reason"):
            visible_reason = str(probe["risk_stop_reason"])
            return {
                "attempted": True,
                "recovered": False,
                "reason_code": (
                    "captcha" if "验证码" in visible_reason else "risk_control"
                ),
                "reason_detail": visible_reason,
            }
        if probe.get("page_kind") not in {
            "home_feed",
            "search_input",
            "search_results",
            "shop_product_list",
        }:
            return {
                "attempted": True,
                "recovered": False,
                "reason_code": "unknown_page",
                "reason_detail": (
                    "reopened Xiaohongshu did not reach a verified safe page: "
                    f"{probe.get('page_kind')}"
                ),
            }
        return {
            "attempted": True,
            "recovered": True,
            "reason_code": None,
            "reason_detail": trigger,
            "page_kind": probe.get("page_kind"),
        }

    def _expected_product(self, product_id: int):
        with connect(self.settings.db_path) as conn:
            return conn.execute(
                "SELECT id, title, shop_name, share_url FROM products WHERE id=?",
                (product_id,),
            ).fetchone()


def _device(settings: Settings) -> AdbDevice:
    config = settings.emulator_config()
    adb = discover_adb(config.get("adb_path"))
    serial = config.get("serial")
    backend = str(config.get("backend") or "bluestacks").strip().casefold()
    if backend != "android" or serial:
        return AdbDevice(adb=adb, serial=serial)

    model = str(config.get("model") or "").strip()
    if not model:
        raise RuntimeError("backend=android 且未配置 serial 时必须配置 model")
    service_name = config.get("mdns_service")

    device = AdbDevice(adb=adb)
    try:
        device.serial = select_device_serial(
            device.devices(),
            model=model,
            service_name=service_name,
        )
        return device
    except RuntimeError as error:
        if "多台同型号安卓设备" in str(error):
            raise

    mdns_service = str(service_name or "").strip()
    if not mdns_service:
        raise RuntimeError(
            "未找到已连接的指定安卓设备，且未配置 mdns_service"
        )
    address = select_mdns_connect_address(
        device.mdns_services(),
        service_name=mdns_service,
    )
    device.connect(address)
    device.serial = select_device_serial(
        device.devices(),
        model=model,
        service_name=service_name,
    )
    return device


def _observed_at() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _normalize_identity(value: str | None) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").casefold())


def _identity_matches(
    *,
    expected_title: str,
    observed_title: str | None,
    page_text: str,
) -> bool:
    expected = _normalize_identity(expected_title)
    observed = _normalize_identity(observed_title)
    whole_page = _normalize_identity(page_text)
    if len(expected) < 6:
        return False
    if expected in whole_page:
        return True
    if observed and (expected in observed or observed in expected) and min(
        len(expected), len(observed)
    ) >= 8:
        return True
    prefix_length = min(16, len(expected))
    return prefix_length >= 10 and expected[:prefix_length] in whole_page


def _hard_stop(observed_at: str, reason_code: str, detail: str) -> dict[str, Any]:
    return {
        "kind": "hard_stop",
        "observed_at": observed_at,
        "reason_code": reason_code,
        "reason_detail": detail,
    }
