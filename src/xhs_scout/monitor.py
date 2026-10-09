from __future__ import annotations

import re
import sqlite3
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .coupon_overlay import (
    COUPON_ACTIVITY,
    find_coupon_close_button,
)
from .device_preflight import check_device_readiness
from .db import (
    connect,
    get_monitor_state,
    record_infrastructure_hard_stop,
    record_ocr_timeout_hard_stop,
    record_run_event,
    record_search_result_evidence,
    set_monitor_desired_state,
    set_monitor_state,
    utcnow,
)
from .emulator import (
    AdbDevice,
    discover_adb,
    discover_bluestacks_player,
    select_device_serial,
    select_mdns_connect_address,
)
from .home_search_visual import find_home_search_icon
from .note_observation import open_note_author_profile_once, open_related_note_once
from .ocr import OcrTimeoutError
from .probe import is_ocr_timeout_probe, probe_current_page
from .product_keyword_terms import (
    decompose_product_keywords,
    persist_product_keyword_decomposition,
)
from .reports import generate_candidate_report
from .seller_profile import capture_seller_profile_from_product
from .run_control import (
    RetryPolicy,
    acquire_monitor_lease,
    check_lease_safety,
    mark_task_failed,
    release_monitor_lease,
    renew_lease_safety,
    reserve_next_runnable_task,
)
from .ui_automation import (
    UiTarget,
    find_history_keyword,
    find_home_search_entry,
    find_product_cards,
    find_product_tab,
    find_clear_query_button,
    find_search_box,
    find_search_product_button,
    find_exact_text,
    find_top_query_field,
    find_top_query_text,
    find_search_input_query_text,
)
from .workflow import (
    capture_current_page_for_task,
    complete_task_from_observation,
    stop_task,
)
from .signals import gray_metric_items


class MonitorBlocked(RuntimeError):
    def __init__(self, message: str, *, hard: bool = False):
        super().__init__(message)
        self.hard = hard


class AppUnresponsive(MonitorBlocked):
    """A current Xiaohongshu ANR that may use one bounded app-only recovery."""

    def __init__(self, message: str = "ANR detected"):
        super().__init__(message, hard=True)


class LeaseSafetyBlocked(MonitorBlocked):
    def __init__(self, message: str, *, phase: str, reason: str):
        super().__init__(message, hard=True)
        self.phase = phase
        self.reason = reason


class OcrInfrastructureBlocked(MonitorBlocked):
    """A global OCR infrastructure stop with preserved machine-readable evidence."""

    def __init__(self, message: str, *, timeout: dict):
        super().__init__(message, hard=True)
        self.timeout = timeout


class VisionInfrastructureBlocked(MonitorBlocked):
    """本地视觉模型基础设施硬停止及其结构化证据。"""

    def __init__(self, message: str, *, failure: dict):
        super().__init__(message, hard=True)
        self.failure = failure


class UiTreeInfrastructureBlocked(MonitorBlocked):
    """uiautomator 页面结构连续抓取失败后的基础设施硬停止。"""

    def __init__(self, message: str, *, failure: dict):
        super().__init__(message, hard=True)
        self.failure = failure


@dataclass(frozen=True)
class MonitorLimits:
    max_keywords: int = 1
    max_products_per_keyword: int = 1
    search_result_rank: int = 1
    search_card_scan_limit: int = 3
    wait_seconds: float = 5.0
    metrics_swipe: bool = True
    metrics_max_frames: int = 5
    recurring_interval_hours: int = 24
    dry_run: bool = False
    allow_back_recovery: bool = True
    note_evidence: bool = False
    seller_profile: bool = True
    note_rank: int = 1
    note_max_scrolls: int = 3
    requeue_due_keywords: bool = True
    task_id: int | None = None
    expected_keyword: str | None = None
    restart_app_before_round: bool = False


SAFE_XHS_RESTART_PAGES = {
    "home_feed",
    "search_input",
    "search_results",
    "shop_product_list",
}

PRE_TASK_XHS_PAGES = SAFE_XHS_RESTART_PAGES | {
    "product_detail",
    "note_detail",
    "account_profile",
}

DEFAULT_ANDROID_UNICODE_PACKAGE = "com.android.adbkeyboard"
DEFAULT_ANDROID_UNICODE_IME = "com.android.adbkeyboard/.AdbIME"
DEFAULT_ANDROID_RESTORE_IME = "com.sohu.inputmethod.sogou.xiaomi/.SogouIME"

# 1080x2340 Redmi 搜索结果页的顶部查询词安全区。只读取截图 OCR 中
# 中心点落入该区域的文字；商品瀑布流即使上滑到页面顶部也不参与判断。
SEARCH_QUERY_SAFE_ROI = (120.0, 100.0, 820.0, 200.0)
SEARCH_QUERY_MIN_CONFIDENCE = 0.80
SEARCH_INPUT_FIELD_TAP = (430, 150)


def _android_unicode_input_settings(settings: Settings) -> tuple[str, str, str]:
    config = settings.emulator_config()
    return (
        str(config.get("unicode_input_package") or DEFAULT_ANDROID_UNICODE_PACKAGE),
        str(config.get("unicode_input_ime") or DEFAULT_ANDROID_UNICODE_IME),
        str(config.get("restore_input_ime") or DEFAULT_ANDROID_RESTORE_IME),
    )


def _wait_for_default_input_method(
    device: AdbDevice,
    expected: str,
    *,
    attempts: int = 10,
    delay_seconds: float = 0.1,
) -> bool:
    for attempt in range(max(1, attempts)):
        if device.default_input_method() == expected:
            return True
        if attempt + 1 < attempts:
            time.sleep(max(0.0, delay_seconds))
    return False


def _android_unicode_input_preflight(settings: Settings, device: AdbDevice) -> dict:
    """Verify the audited helper before a search task can be reserved.

    The switch test is deliberately performed before reservation and always
    restores the configured Sogou IME.  A helper left active by an interrupted
    prior run is repaired to Sogou before the test continues.
    """

    package, helper_ime, restore_ime = _android_unicode_input_settings(settings)
    result: dict[str, Any] = {
        "ready": False,
        "package": package,
        "helper_ime": helper_ime,
        "restore_ime": restore_ime,
        "package_installed": False,
        "ime_enabled": False,
        "switch_verified": False,
        "restore_verified": False,
        "recovered_stale_helper": False,
    }
    try:
        result["package_installed"] = device.package_path(package).startswith("package:")
        if not result["package_installed"]:
            result["error"] = "unicode input helper package is not installed"
            return result

        enabled = set(device.enabled_input_methods())
        result["ime_enabled"] = helper_ime in enabled
        if not result["ime_enabled"]:
            result["error"] = "unicode input helper IME is not enabled"
            return result

        current_ime = device.default_input_method()
        result["initial_ime"] = current_ime
        if current_ime == helper_ime:
            device.set_input_method(restore_ime)
            if not _wait_for_default_input_method(device, restore_ime):
                result["error"] = "could not restore stale helper IME before task reservation"
                return result
            current_ime = restore_ime
            result["recovered_stale_helper"] = True
        if current_ime != restore_ime:
            result["error"] = f"unexpected original input method: {current_ime or 'unknown'}"
            return result

        try:
            device.set_input_method(helper_ime)
            result["switch_verified"] = _wait_for_default_input_method(device, helper_ime)
            if not result["switch_verified"]:
                result["error"] = "unicode input helper could not become the default IME"
        finally:
            device.set_input_method(restore_ime)
            result["restore_verified"] = _wait_for_default_input_method(device, restore_ime)
        if not result["restore_verified"]:
            result["error"] = "original Sogou IME could not be restored"
            return result
        result["ready"] = bool(result["switch_verified"])
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        try:
            device.set_input_method(restore_ime)
            result["restore_verified"] = _wait_for_default_input_method(
                device,
                restore_ime,
            )
        except Exception as restore_exc:
            result["restore_error"] = f"{type(restore_exc).__name__}: {restore_exc}"
        return result


def _device_process_id(device: AdbDevice, package: str) -> str | None:
    """Read a process id when supported without breaking offline test devices."""

    pidof = getattr(device, "pidof", None)
    if not callable(pidof):
        return None
    try:
        process_id = pidof(package)
    except (OSError, subprocess.SubprocessError):
        return None
    return str(process_id).strip() if process_id else None


def _app_process_restarted(before: str | None, after: str | None) -> bool:
    """Only claim a restart when both observations are known and differ."""

    return bool(before and after and before != after)


def _select_product_card(
    cards: list[UiTarget],
    requested_rank: int,
) -> tuple[UiTarget | None, int | None]:
    """Choose the exact visible rank without wrapping to a duplicate card."""

    if not cards:
        return None, None
    normalized_rank = max(1, int(requested_rank))
    if normalized_rank > len(cards):
        return None, None
    return cards[normalized_rank - 1], normalized_rank


def _product_card_key(card: UiTarget) -> str:
    """Build a stable-enough key for deduplicating an overlapping result scroll."""

    label = re.sub(r"\s+", "", str(card.label or "")).casefold()
    if label:
        # 同一商品卡在滚动前后可能临时多出一段“买家评价”前缀，整段label
        # 因而并不稳定。去重只取核心商品标题：先移除带引号的评价摘要，再
        # 截断价格、销量、加购等交易指标，避免把旧卡误计为新的rank。
        core = re.sub(r'^[“"].{1,120}?[”"]', "", label, count=1)
        core = re.split(
            r"(?:\d+(?:\.\d+)?\+人(?:加购|收藏)|好评率\d+%|"
            r"新客立减|限时立减|券后[¥￥]|[¥￥]\d|已售\d)",
            core,
            maxsplit=1,
        )[0]
        if len(core) >= 8:
            return f"title:{core}"
        return f"label:{label}"
    bounds = card.bounds
    return f"shape:{bounds.width}x{bounds.height}:{card.source}"


def _locate_ranked_product_card(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    keyword: str,
    result_page: dict,
    limits: MonitorLimits,
    max_scrolls: int = 2,
) -> tuple[list[UiTarget], UiTarget | None, int | None, dict]:
    """Locate an exact result rank, scrolling only when it is not yet visible.

    Result cards from each viewport are accumulated by label so an overlapping
    card is counted once.  The function fails closed if the requested rank
    cannot be observed; it never wraps rank 5 back to an earlier card.
    """

    scan_limit = max(
        1,
        limits.max_products_per_keyword,
        limits.search_card_scan_limit,
        limits.search_result_rank,
    )
    requested_rank = max(1, int(limits.search_result_rank))
    discovered: list[UiTarget] = []
    seen: set[str] = set()
    current_page = dict(result_page)

    for scroll_index in range(max(0, int(max_scrolls)) + 1):
        current_probe = dict(current_page.get("probe") or {})
        current_probe, current_xml = _ensure_ui_tree(
            settings,
            device,
            run_id=run_id,
            task_id=task_id,
            probe=current_probe,
            xml_text=current_page.get("xml") or "",
            phase=(
                "search_product_tab"
                if scroll_index == 0
                else f"search_result_scroll_{scroll_index}"
            ),
            dry_run=limits.dry_run,
        )
        current_page = {"probe": current_probe, "xml": current_xml}
        visible = find_product_cards(current_xml, limit=scan_limit)
        for card in visible:
            key = _product_card_key(card)
            if key in seen:
                continue
            seen.add(key)
            discovered.append(card)

        selected, actual_rank = _select_product_card(discovered, requested_rank)
        if selected is not None:
            return discovered, selected, actual_rank, current_page

        if not discovered or limits.dry_run or scroll_index >= max_scrolls:
            break

        device.swipe(540, 1700, 540, 650, 700)
        time.sleep(max(0.0, float(limits.wait_seconds)))
        probe = probe_current_page(
            settings, device, run_id=f"{run_id}-probe-result-scroll-{scroll_index + 1}"
        )
        _guard_probe(
            settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
        )
        xml_text = _read_ui(probe)
        fixed_query_matches = _is_expected_search_context(
            keyword,
            probe,
            xml_text,
        )
        if (
            probe["page_kind"] not in {"search_results", "shop_product_list"}
            and not fixed_query_matches
        ):
            raise MonitorBlocked(
                f"not on search results while scrolling for rank: {probe['page_kind']}",
                hard=True,
            )
        if not fixed_query_matches and not _keyword_matches_search_page(
            keyword, probe, xml_text
        ):
            raise MonitorBlocked(
                "search result keyword changed while locating requested rank",
                hard=True,
            )
        if fixed_query_matches and probe["page_kind"] not in {
            "search_results",
            "shop_product_list",
        }:
            # 商品结果页下滑后，“综合/筛选”等辅助文字可能离开截图，旧的
            # 整页分类器会返回 unknown。此阶段只认固定搜索框和当前任务词，
            # 不再依赖易变化的结果页标签集合。
            probe = {
                **probe,
                "page_kind": "search_results",
                "page_kind_source": "fixed_search_query",
            }
        current_page = {"probe": probe, "xml": xml_text}
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="scroll_product_results_for_rank",
                task_id=task_id,
                data={
                    "keyword": keyword,
                    "requested_rank": requested_rank,
                    "scroll_index": scroll_index + 1,
                    "unique_cards_seen": len(discovered),
                },
            )

    return discovered, None, None, current_page


def _lease_safety_checkpoint(
    settings: Settings,
    *,
    run_id: str,
    task_id: int,
    lease_ttl_seconds: int,
    phase: str,
    renew: bool,
    dry_run: bool = False,
) -> None:
    """Fail closed at a coarse device-operation boundary.

    Checkpoints intentionally wrap whole UI/OCR stages instead of individual
    taps. A pre-stage renewal gives the stage a full lease window; the
    post-stage ownership check prevents any later device action after loss.
    """

    if dry_run:
        return

    try:
        with connect(settings.db_path) as conn:
            if renew:
                result = renew_lease_safety(
                    conn,
                    task_id=task_id,
                    owner=run_id,
                    monitor_ttl_seconds=lease_ttl_seconds,
                    policy=RetryPolicy(),
                )
            else:
                result = check_lease_safety(
                    conn,
                    task_id=task_id,
                    owner=run_id,
                )
            if result.safe_to_continue:
                return

            block_reason = f"lease safety blocked at {phase}: {result.reason}"
            set_monitor_desired_state(conn, "paused")
            set_monitor_state(conn, "risk_stop_reason", block_reason)
            set_monitor_state(conn, "last_block_reason", block_reason)
            task = conn.execute(
                "SELECT status, run_owner FROM search_tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if (
                task
                and task["status"] == "running"
                and task["run_owner"] == run_id
            ):
                mark_task_failed(
                    conn,
                    task_id=task_id,
                    owner=run_id,
                    reason=block_reason,
                    policy=RetryPolicy(),
                    retryable=False,
                )
            record_run_event(
                conn,
                run_id=run_id,
                phase="lease_safety",
                event="lease_safety_blocked",
                level="warning",
                task_id=task_id,
                message=block_reason,
                data={"checkpoint": phase, "lease": asdict(result)},
            )
            # Owner-qualified release never removes a lease taken over by a
            # different executor.
            release_monitor_lease(conn, owner=run_id)
    except sqlite3.Error as exc:
        block_reason = f"lease safety blocked at {phase}: database_unavailable"
        raise LeaseSafetyBlocked(
            f"{block_reason} ({exc})",
            phase=phase,
            reason="database_unavailable",
        ) from exc

    raise LeaseSafetyBlocked(
        block_reason,
        phase=phase,
        reason=result.reason,
    )


def _device(settings: Settings) -> AdbDevice:
    config = settings.emulator_config()
    adb = discover_adb(config.get("adb_path"))
    serial = config.get("serial")
    if not serial:
        model = str(config.get("model") or "").strip()
        if not model:
            # Fail closed rather than falling through to an unscoped
            # ``AdbDevice(serial=None)``, which would silently target
            # whatever single device ADB happens to see instead of the
            # explicitly configured phone.
            raise RuntimeError(
                "未配置 serial 时必须配置 model 才能选择安卓设备"
            )
        base_device = AdbDevice(adb=adb)
        try:
            serial = select_device_serial(
                base_device.devices(),
                model=model,
                service_name=str(config.get("mdns_service") or "") or None,
            )
        except RuntimeError as exc:
            service_name = config.get("mdns_service")
            if not service_name or not str(exc).startswith("未找到已连接"):
                raise
            address = select_mdns_connect_address(
                base_device.mdns_services(),
                service_name=str(service_name),
            )
            base_device.connect(address)
            serial = select_device_serial(
                base_device.devices(),
                model=model,
                service_name=str(service_name),
            )
    return AdbDevice(adb=adb, serial=serial)


def _launch_xhs(settings: Settings, device: AdbDevice, package: str) -> None:
    config = settings.emulator_config()
    if config.get("backend") == "android":
        device.launch_android_package(package)
        return
    instance = str(config.get("instance") or "Rvc64")
    player = discover_bluestacks_player(config.get("player_path"))
    device.launch_with_bluestacks_player(player, instance, package)


def _android_device_preflight(settings: Settings, device: AdbDevice) -> dict | None:
    config = settings.emulator_config()
    if str(config.get("backend") or "bluestacks").strip().casefold() != "android":
        return None
    return check_device_readiness(settings, device).as_dict()


def _prepare_android_xhs_foreground_before_task_reservation(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    limits: MonitorLimits,
) -> dict:
    """Bring Android Xiaohongshu to a verified page before consuming a task.

    A phone may be left in Settings after wireless-debugging recovery.  That is
    an environment precondition, not a search-task attempt.  If Xiaohongshu is
    not already foreground, launch it without force-stopping, then verify a
    known page before task reservation.
    """

    config = settings.emulator_config()
    package = str(config.get("package") or "com.xingin.xhs")
    focus_dump = device.window_focus()
    current_focus_lines = [
        line.strip()
        for line in focus_dump.splitlines()
        if "mCurrentFocus=" in line
    ]
    current_focus = current_focus_lines[-1] if current_focus_lines else None
    if current_focus and f"{package}/" in current_focus:
        return {
            "ready": True,
            "launched": False,
            "activity": current_focus,
            "page_kind": None,
        }

    with connect(settings.db_path) as conn:
        record_run_event(
            conn,
            run_id=run_id,
            phase="device_preflight",
            event="xhs_foreground_missing_before_task_reservation",
            level="warning",
            data={"current_focus": current_focus, "package": package},
        )

    _launch_xhs(settings, device, package)
    time.sleep(max(3.0, float(limits.wait_seconds)))
    probe = probe_current_page(
        settings,
        device,
        run_id=f"{run_id}-probe-pre-task-xhs-foreground",
    )
    _guard_probe(settings, run_id, probe, device=device, dry_run=limits.dry_run)
    activity = str(probe.get("activity") or "")
    page_kind = probe.get("page_kind")
    if not activity.startswith(f"{package}/") or page_kind not in PRE_TASK_XHS_PAGES:
        reason = (
            "Xiaohongshu foreground preflight failed before task reservation: "
            f"activity={activity or 'unknown'}, page_kind={page_kind or 'unknown'}"
        )
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="device_preflight",
                event="xhs_foreground_preflight_failed",
                level="warning",
                message=reason,
                data={"probe": probe},
            )
        raise MonitorBlocked(reason)

    with connect(settings.db_path) as conn:
        record_run_event(
            conn,
            run_id=run_id,
            phase="device_preflight",
            event="xhs_foreground_preflight_passed",
            data={"probe": probe, "launched": True},
        )
    return {
        "ready": True,
        "launched": True,
        "activity": activity,
        "page_kind": page_kind,
        "probe_dir": probe.get("probe_dir"),
    }


def _read_ui(probe: dict) -> str:
    probe_dir = Path(probe["probe_dir"])
    xml_path = probe_dir / "window.xml"
    if not xml_path.exists():
        return ""
    return xml_path.read_text(encoding="utf-8", errors="replace")


def _is_usable_ui_tree(xml_text: str) -> bool:
    if not str(xml_text or "").strip():
        return False
    try:
        ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    return True


def _ensure_ui_tree(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    probe: dict,
    xml_text: str,
    phase: str,
    dry_run: bool,
    max_retries: int = 2,
) -> tuple[dict, str]:
    """对空/损坏的 uiautomator dump 做有界原地重抓。

    截图与 OCR 已经成功时，不重新跑整套页面探测，只重抓轻量 XML。
    连续失败属于设备基础设施故障，必须返还任务尝试，不能冒成普通商品
    失败或未捕获的 HTTP 500。
    """

    if _is_usable_ui_tree(xml_text):
        return probe, xml_text

    errors: list[str] = []
    if not dry_run:
        for attempt in range(1, max(1, int(max_retries)) + 1):
            try:
                recovered = device.ui_dump()
            except Exception as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                recovered = ""
            if _is_usable_ui_tree(recovered):
                probe_dir_value = probe.get("probe_dir")
                if probe_dir_value:
                    xml_path = Path(probe_dir_value) / "window.xml"
                    temp_path = xml_path.with_suffix(".xml.tmp")
                    temp_path.write_text(recovered, encoding="utf-8")
                    temp_path.replace(xml_path)
                recovered_probe = {
                    **probe,
                    "ui_dump_ok": True,
                    "ui_error": None,
                    "ui_tree_retry_attempts": attempt,
                }
                with connect(settings.db_path) as conn:
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="ui_tree",
                        event="ui_tree_retry_recovered",
                        task_id=task_id,
                        data={
                            "source_phase": phase,
                            "retry_attempt": attempt,
                            "probe_dir": probe_dir_value,
                        },
                    )
                return recovered_probe, recovered
            errors.append(f"attempt {attempt}: empty_or_malformed_ui_tree")
            if attempt < max(1, int(max_retries)):
                time.sleep(0.25)

    _raise_ui_tree_hard_stop(
        settings,
        run_id=run_id,
        task_id=task_id,
        message="uiautomator returned an empty or malformed UI tree",
        phase=phase,
        evidence={
            "probe_dir": probe.get("probe_dir"),
            "activity": probe.get("activity"),
            "ui_dump_ok": probe.get("ui_dump_ok"),
            "ui_error": probe.get("ui_error"),
            "retry_errors": errors,
        },
        dry_run=dry_run,
    )
    raise AssertionError("unreachable")


def _target_dict(target: UiTarget | None) -> dict | None:
    if not target:
        return None
    return {
        "x": target.x,
        "y": target.y,
        "bounds": asdict(target.bounds),
        "label": target.label,
        "reason": target.reason,
    }


def _ocr_timeout_reason(message: str) -> str:
    return f"OCR infrastructure timeout: {message}"


def _vision_fields_reason(message: str) -> str:
    return f"Local vision infrastructure failure: {message}"


def _preserve_probe_ocr_timeout_evidence(
    probe: dict,
    *,
    device: AdbDevice | None,
) -> dict:
    probe_dir_value = probe.get("probe_dir")
    probe_dir = Path(probe_dir_value) if probe_dir_value else None
    xml_path = probe_dir / "window.xml" if probe_dir else None
    xml_error = None
    if xml_path and not xml_path.exists() and device is not None:
        try:
            xml_path.write_text(device.ui_dump(), encoding="utf-8")
        except Exception as exc:
            xml_error = f"{type(exc).__name__}: {exc}"
            xml_path = None
    return {
        "probe_dir": str(probe_dir) if probe_dir else None,
        "screenshot": probe.get("screenshot"),
        "xml": str(xml_path) if xml_path and xml_path.exists() else None,
        "xml_error": xml_error,
        "window": str(probe_dir / "window.txt") if probe_dir else None,
        "activity": probe.get("activity"),
    }


def _find_nested_ocr_timeout_probe(payload: dict) -> tuple[str, dict] | None:
    """Find OCR infrastructure evidence returned by a bounded nested collector."""

    def _walk(value, path: str, depth: int) -> tuple[str, dict] | None:
        if depth > 4:
            return None
        if isinstance(value, dict):
            if is_ocr_timeout_probe(value):
                return path or "probe", value
            for key, nested in value.items():
                if not isinstance(nested, (dict, list, tuple)):
                    continue
                nested_path = f"{path}.{key}" if path else str(key)
                found = _walk(nested, nested_path, depth + 1)
                if found is not None:
                    return found
        elif isinstance(value, (list, tuple)):
            for index, nested in enumerate(value):
                nested_path = f"{path}[{index}]" if path else f"[{index}]"
                found = _walk(nested, nested_path, depth + 1)
                if found is not None:
                    return found
        return None

    return _walk(payload, "", 0)


def _raise_ocr_timeout_hard_stop(
    settings: Settings,
    *,
    run_id: str,
    task_id: int | None,
    message: str,
    phase: str,
    evidence: dict,
    dry_run: bool,
    cleanup_note_observation_ids: list[int] | None = None,
) -> None:
    reason = _ocr_timeout_reason(message)
    hard_stop = {
        "hard_stop": True,
        "reason_code": "ocr_timeout",
        "requires_explicit_resume": True,
        "reason": reason,
        "phase": phase,
        "refunded_tasks": [],
        "attempt_returned": False,
        "disposition_attempted": False,
        "evidence": evidence,
    }
    if not dry_run:
        with connect(settings.db_path) as conn:
            hard_stop = record_ocr_timeout_hard_stop(
                conn,
                run_id=run_id,
                owner=run_id,
                reason=reason,
                phase=phase,
                task_id=task_id,
                restore_status="pending",
                refund_all_owned_tasks=True,
                evidence=evidence,
                cleanup_note_observation_ids=cleanup_note_observation_ids,
                require_active_monitor_lease=True,
            )
    timeout = {
        **hard_stop,
        "run_id": run_id,
        "task_id": task_id,
        "exception": {
            "type": "OcrTimeoutError",
            "message": message,
        },
    }
    raise OcrInfrastructureBlocked(reason, timeout=timeout)


def _raise_vision_fields_hard_stop(
    settings: Settings,
    *,
    run_id: str,
    task_id: int | None,
    message: str,
    evidence: dict,
    dry_run: bool,
) -> None:
    reason = _vision_fields_reason(message)
    hard_stop = {
        "hard_stop": True,
        "reason_code": "vision_fields_failure",
        "requires_explicit_resume": True,
        "reason": reason,
        "phase": "product_detail_vision",
        "refunded_tasks": [],
        "attempt_returned": False,
        "disposition_attempted": False,
        "evidence": evidence,
    }
    if not dry_run:
        with connect(settings.db_path) as conn:
            hard_stop = record_infrastructure_hard_stop(
                conn,
                run_id=run_id,
                owner=run_id,
                reason=reason,
                phase="product_detail_vision",
                reason_code="vision_fields_failure",
                event_name="vision_fields_hard_stop",
                failure_label="vision-inference",
                task_id=task_id,
                restore_status="pending",
                refund_all_owned_tasks=True,
                evidence=evidence,
                require_active_monitor_lease=True,
            )
    failure = {
        **hard_stop,
        "run_id": run_id,
        "task_id": task_id,
        "exception": {
            "type": "VisionFieldsError",
            "message": message,
            "code": evidence.get("error_code"),
        },
    }
    raise VisionInfrastructureBlocked(reason, failure=failure)


def _raise_ui_tree_hard_stop(
    settings: Settings,
    *,
    run_id: str,
    task_id: int | None,
    message: str,
    phase: str,
    evidence: dict,
    dry_run: bool,
) -> None:
    reason = f"UI tree infrastructure failure: {message}"
    hard_stop = {
        "hard_stop": True,
        "reason_code": "ui_tree_unavailable",
        "requires_explicit_resume": True,
        "reason": reason,
        "phase": phase,
        "refunded_tasks": [],
        "attempt_returned": False,
        "disposition_attempted": False,
        "evidence": evidence,
    }
    if not dry_run:
        with connect(settings.db_path) as conn:
            hard_stop = record_infrastructure_hard_stop(
                conn,
                run_id=run_id,
                owner=run_id,
                reason=reason,
                phase=phase,
                reason_code="ui_tree_unavailable",
                event_name="ui_tree_hard_stop",
                failure_label="UI-tree",
                task_id=task_id,
                restore_status="pending",
                refund_all_owned_tasks=True,
                evidence=evidence,
                require_active_monitor_lease=True,
            )
    failure = {
        **hard_stop,
        "run_id": run_id,
        "task_id": task_id,
        "exception": {
            "type": "UiTreeUnavailable",
            "message": message,
        },
    }
    raise UiTreeInfrastructureBlocked(reason, failure=failure)


def _guard_probe(
    settings: Settings,
    run_id: str,
    probe: dict,
    task_id: int | None = None,
    *,
    device: AdbDevice | None = None,
    dry_run: bool = False,
) -> None:
    reason = None
    if probe.get("has_anr"):
        raise AppUnresponsive("ANR detected")
    elif is_ocr_timeout_probe(probe):
        message = str(
            probe.get("ocr_error")
            or probe.get("risk_stop_reason")
            or "RapidOCR exceeded its process deadline"
        )
        _raise_ocr_timeout_hard_stop(
            settings,
            run_id=run_id,
            task_id=task_id,
            message=message,
            phase="probe_ocr",
            evidence=_preserve_probe_ocr_timeout_evidence(
                probe,
                device=device,
            ),
            dry_run=dry_run,
        )
    elif probe.get("risk_stop_reason"):
        reason = f"risk stop: {probe['risk_stop_reason']}"
    elif probe.get("page_kind") == "forbidden_interaction_area":
        reason = "forbidden interaction area"
    if not reason:
        return
    with connect(settings.db_path) as conn:
        if not dry_run:
            set_monitor_desired_state(conn, "paused")
            set_monitor_state(conn, "risk_stop_reason", reason)
        record_run_event(
            conn,
            run_id=run_id,
            phase="monitor",
            event="monitor_paused_by_guard",
            level="warning",
            task_id=task_id,
            message=reason,
            data={"probe": probe},
        )
        if task_id and not dry_run:
            stop_task(conn, task_id, "risk_stopped", reason)
    raise MonitorBlocked(reason, hard=True)


def _is_adb_timeout(exc: subprocess.TimeoutExpired) -> bool:
    command = exc.cmd
    if isinstance(command, str):
        executable = command.strip().split(maxsplit=1)[0].strip('"').lower()
    else:
        executable = str(command[0]).lower() if command else ""
    return (
        executable.endswith("adb")
        or executable.endswith("adb.exe")
        or "hd-adb.exe" in executable
    )


def _restart_xhs_to_safe_page(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    limits: MonitorLimits,
    event: str,
    task_id: int | None = None,
) -> dict:
    """Force a fresh app process and verify a known-safe landing page."""

    config = settings.emulator_config()
    package = str(config.get("package") or "com.xingin.xhs")
    with connect(settings.db_path) as conn:
        record_run_event(
            conn,
            run_id=run_id,
            phase="app_recovery",
            event=f"{event}_started",
            task_id=task_id,
            data={"package": package, "backend": config.get("backend") or "bluestacks"},
        )
    device.force_stop(package, timeout=15)
    _launch_xhs(settings, device, package)
    time.sleep(max(3.0, float(limits.wait_seconds)))
    probe = probe_current_page(
        settings,
        device,
        run_id=f"{run_id}-probe-{event}",
    )
    _guard_probe(
        settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
    )
    if probe.get("page_kind") not in SAFE_XHS_RESTART_PAGES:
        reason = (
            "reopened Xiaohongshu did not reach a verified safe page: "
            f"{probe.get('page_kind')}"
        )
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="app_recovery",
                event=f"{event}_failed",
                level="warning",
                task_id=task_id,
                message=reason,
                data={"probe": probe},
            )
        raise MonitorBlocked(reason, hard=True)
    with connect(settings.db_path) as conn:
        record_run_event(
            conn,
            run_id=run_id,
            phase="app_recovery",
            event=f"{event}_succeeded",
            task_id=task_id,
            data={"probe": probe},
        )
    return probe


def _recover_xhs_after_unresponsive(
    settings: Settings,
    *,
    run_id: str,
    limits: MonitorLimits,
    error: Exception,
) -> dict:
    """Abort the round and perform app-only recovery for this ANR.

    The current task is never resumed from an uncertain coordinate. The caller's
    normal finally block releases the run lease. A prior recovery in another
    round never prevents recovery of the current ANR.
    """

    error_type = type(error).__name__
    reason = (
        "Xiaohongshu ANR detected"
        if isinstance(error, AppUnresponsive)
        else "ADB command timed out while controlling Xiaohongshu"
    )
    base_output = {
        "run_id": run_id,
        "dry_run": limits.dry_run,
        "processed_tasks": 0,
        "captured_products": 0,
        "skipped": [],
        "app_recovery": {
            "attempted": False,
            "recovered": False,
            "reason": reason,
        },
        "aborted_reason": reason,
    }
    if limits.dry_run:
        base_output["blocked"] = reason
        return base_output

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        resume_after_recovery = state.get("desired_state") == "running"
        running_task = conn.execute(
            """
            SELECT id
            FROM search_tasks
            WHERE status='running' AND run_owner=?
            ORDER BY id
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        task_id = int(running_task["id"]) if running_task else None
        set_monitor_desired_state(conn, "paused")
        set_monitor_state(conn, "risk_stop_reason", reason)
        set_monitor_state(conn, "last_block_reason", reason)
        record_run_event(
            conn,
            run_id=run_id,
            phase="app_recovery",
            event="app_unresponsive_detected",
            level="warning",
            task_id=task_id,
            message=reason,
            data={
                "error_type": error_type,
                "error": str(error)[:1000],
            },
        )

    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "app_recovery_last_attempt_at", utcnow())

    device = _device(settings)
    config = settings.emulator_config()
    package = str(config.get("package") or "com.xingin.xhs")
    recovery_probe: dict | None = None
    try:
        device.force_stop(package, timeout=15)
        _launch_xhs(settings, device, package)
        time.sleep(max(3.0, float(limits.wait_seconds)))
        recovery_probe = probe_current_page(
            settings,
            device,
            run_id=f"{run_id}-probe-after-app-recovery",
        )
        if is_ocr_timeout_probe(recovery_probe):
            _raise_ocr_timeout_hard_stop(
                settings,
                run_id=run_id,
                task_id=task_id,
                message=str(
                    recovery_probe.get("ocr_error")
                    or recovery_probe.get("risk_stop_reason")
                    or "RapidOCR exceeded its process deadline"
                ),
                phase="app_recovery_probe_ocr",
                evidence=_preserve_probe_ocr_timeout_evidence(
                    recovery_probe,
                    device=device,
                ),
                dry_run=limits.dry_run,
            )
        safe_page = recovery_probe.get("page_kind") in {
            "home_feed",
            "search_input",
            "search_results",
            "shop_product_list",
        }
        if (
            recovery_probe.get("has_anr")
            or recovery_probe.get("risk_stop_reason")
            or not safe_page
        ):
            raise RuntimeError(
                "reopened Xiaohongshu did not reach a verified safe page: "
                f"{recovery_probe.get('page_kind')}"
            )
    except OcrInfrastructureBlocked as blocked:
        output = _ocr_timeout_monitor_output(
            run_id=run_id,
            dry_run=limits.dry_run,
            blocked=blocked,
        )
        output["app_recovery"] = {
            "attempted": True,
            "recovered": False,
            "reason": str(blocked),
            "probe": recovery_probe,
        }
        output["aborted_reason"] = str(blocked)
        return output
    except Exception as recovery_error:
        failed_reason = (
            f"{reason}; app-only recovery failed: "
            f"{type(recovery_error).__name__}: {recovery_error}"
        )
        with connect(settings.db_path) as conn:
            set_monitor_state(conn, "risk_stop_reason", failed_reason)
            set_monitor_state(conn, "last_block_reason", failed_reason)
            set_monitor_state(conn, "app_recovery_last_result", "failed")
            record_run_event(
                conn,
                run_id=run_id,
                phase="app_recovery",
                event="app_recovery_failed",
                level="warning",
                task_id=task_id,
                message=failed_reason,
                data={"probe": recovery_probe},
            )
        base_output["blocked"] = failed_reason
        base_output["app_recovery"].update(
            {"attempted": True, "reason": failed_reason}
        )
        return base_output

    with connect(settings.db_path) as conn:
        current = get_monitor_state(conn)
        if current.get("risk_stop_reason") == reason:
            set_monitor_state(conn, "risk_stop_reason", None)
        set_monitor_state(conn, "last_block_reason", None)
        set_monitor_state(conn, "app_recovery_last_result", "recovered")
        set_monitor_state(conn, "app_recovery_last_success_at", utcnow())
        set_monitor_desired_state(
            conn,
            "running" if resume_after_recovery else "paused",
        )
        record_run_event(
            conn,
            run_id=run_id,
            phase="app_recovery",
            event="app_recovery_succeeded",
            task_id=task_id,
            message="小红书已自动关闭并重开；当前轮中止，等待下一轮从安全起点继续",
            data={
                "probe": recovery_probe,
                "resume_after_recovery": resume_after_recovery,
            },
        )
    base_output["app_recovery"].update(
        {
            "attempted": True,
            "recovered": True,
            "page_kind": recovery_probe.get("page_kind"),
            "resume_after_recovery": resume_after_recovery,
        }
    )
    return base_output


def _next_pending_tasks(settings: Settings, limit: int) -> list[dict]:
    with connect(settings.db_path) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, keyword, attempts
                FROM search_tasks
                WHERE status='pending'
                ORDER BY priority DESC, id
                LIMIT ?
                """,
                (limit,),
            )
        ]


def _requeue_due_keywords(settings: Settings, *, limit: int, interval_hours: int) -> int:
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT keyword, MAX(updated_at) AS last_completed
            FROM search_tasks
            WHERE status='completed'
            GROUP BY keyword
            HAVING NOT EXISTS (
                SELECT 1 FROM search_tasks active
                WHERE active.keyword=search_tasks.keyword
                  AND active.status IN ('pending', 'running', 'paused', 'needs_manual_detail', 'risk_stopped')
            )
            ORDER BY last_completed
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        now = utcnow()
        inserted = 0
        for row in rows:
            last_completed = row["last_completed"] or ""
            # ISO timestamps sort lexicographically within the same timezone format.
            if last_completed and interval_hours > 0:
                # Keep the comparison conservative; if parsing fails, skip requeue this round.
                try:
                    last_epoch = time.mktime(time.strptime(last_completed[:19], "%Y-%m-%dT%H:%M:%S"))
                except ValueError:
                    continue
                if time.time() - last_epoch < interval_hours * 3600:
                    continue
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO search_tasks(keyword, source, created_at, updated_at)
                VALUES (?, 'recurring_monitor', ?, ?)
                """,
                (row["keyword"], now, now),
            )
            inserted += cur.rowcount
        return inserted


def _tap(device: AdbDevice, target: UiTarget, *, dry_run: bool) -> None:
    if dry_run:
        return
    device.tap(target.x, target.y)


def _exact_top_query_matches(keyword: str, xml_text: str) -> bool:
    return find_top_query_text(xml_text) == keyword.strip()


def _enter_keyword(
    device: AdbDevice,
    xml_text: str,
    keyword: str,
    *,
    dry_run: bool,
    android_unicode: bool = False,
    helper_ime: str = DEFAULT_ANDROID_UNICODE_IME,
    restore_ime: str = DEFAULT_ANDROID_RESTORE_IME,
    query_probe: Callable[[int], dict] | None = None,
) -> dict:
    history = find_history_keyword(xml_text, keyword)
    if history and not android_unicode:
        _tap(device, history, dry_run=dry_run)
        return {"method": "history", "target": _target_dict(history)}
    search_box = find_search_box(xml_text)
    if not search_box:
        raise MonitorBlocked("search input not found")
    if android_unicode:
        # 当前Redmi搜索输入框固定在顶部；先把焦点明确落到输入区，再由
        # ADBKeyBoard执行全选清空，避免依赖偶尔缺失的“全部删除”节点。
        if not dry_run:
            device.tap(*SEARCH_INPUT_FIELD_TAP)
    else:
        _tap(device, search_box, dry_run=dry_run)
        clear_button = find_clear_query_button(xml_text)
        if clear_button:
            _tap(device, clear_button, dry_run=dry_run)
    if dry_run:
        return {
            "method": "adb_keyboard_base64" if android_unicode else "clipboard_paste",
            "target": _target_dict(search_box),
        }
    if android_unicode:
        original_ime = device.default_input_method()
        if original_ime != restore_ime:
            raise MonitorBlocked(
                f"unexpected input method before Unicode entry: {original_ime or 'unknown'}"
            )
        try:
            device.set_input_method(helper_ime)
            if not _wait_for_default_input_method(device, helper_ime):
                raise MonitorBlocked("ADBKeyBoard did not become the active input method")
            device.adb_keyboard_clear_text()
            device.adb_keyboard_input_text(keyword)
            query_before_submit = None
            query_read_attempts = 0
            max_query_read_attempts = 3 if query_probe is not None else 10
            for query_read_attempts in range(1, max_query_read_attempts + 1):
                if query_probe is None:
                    query_xml = device.ui_dump()
                    query_before_submit = find_search_input_query_text(query_xml)
                else:
                    query_before_submit = _fixed_search_query_from_probe(
                        query_probe(query_read_attempts)
                    )
                if query_before_submit == keyword.strip():
                    break
                if query_read_attempts < max_query_read_attempts:
                    time.sleep(0.3)
            if query_before_submit != keyword.strip():
                raise MonitorBlocked(
                    "search input fixed-ROI query mismatch before submit: "
                    f"expected={keyword!r}, actual={query_before_submit!r}"
                )
            device.adb_keyboard_submit_search()
        finally:
            device.set_input_method(original_ime)
            if not _wait_for_default_input_method(device, original_ime):
                raise MonitorBlocked(
                    "failed to restore original input method after Unicode entry",
                    hard=True,
                )
        return {
            "method": "adb_keyboard_base64",
            "target": _target_dict(search_box),
            "query_before_submit": query_before_submit,
            "query_read_attempts": query_read_attempts,
            "query_verified": True,
            "query_verification_source": (
                "screenshot_fixed_roi" if query_probe is not None else "ui_tree"
            ),
            "restored_ime": original_ime,
        }

    device.paste_text_via_windows_clipboard(keyword)
    search_button = find_exact_text(xml_text, "\u641c\u7d22")
    if search_button:
        _tap(device, search_button, dry_run=False)
    else:
        device.enter()
    return {"method": "clipboard_paste", "target": _target_dict(search_box)}


def _fixed_search_query_from_probe(probe: dict) -> str | None:
    left, top, right, bottom = SEARCH_QUERY_SAFE_ROI
    candidates: list[str] = []
    for detail in probe.get("ocr") or []:
        if not isinstance(detail, dict):
            continue
        try:
            confidence = float(detail.get("confidence"))
            points = detail.get("box")
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
        except (TypeError, ValueError, IndexError):
            continue
        if not xs or not ys or confidence < SEARCH_QUERY_MIN_CONFIDENCE:
            continue
        center_x = (min(xs) + max(xs)) / 2
        center_y = (min(ys) + max(ys)) / 2
        if not (left <= center_x <= right and top <= center_y <= bottom):
            continue
        text = str(detail.get("text") or "").strip()
        if text:
            candidates.append(text)
    return candidates[0] if len(candidates) == 1 else None


def _probe_search_input_query_before_submit(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    attempt: int,
) -> dict:
    probe = probe_current_page(
        settings,
        device,
        run_id=f"{run_id}-probe-query-before-submit-{attempt}",
    )
    _guard_probe(settings, run_id, probe, task_id, device=device, dry_run=False)
    if probe.get("page_kind") != "search_input":
        raise MonitorBlocked(
            "query verification left search input: "
            f"{probe.get('page_kind') or 'unknown'}"
        )
    return probe


def _keyword_matches_search_page(keyword: str, probe: dict, xml_text: str) -> bool:
    # 这里有意不使用 ``xml_text``：结果页上滑后，Android 无障碍树会把已经
    # 离屏的商品节点报告到顶部坐标。截图 OCR 的几何位置才与真实画面一致。
    _ = xml_text
    top_query = _fixed_search_query_from_probe(probe)
    compact_keyword = "".join(keyword.split())
    compact_query = "".join((top_query or "").split())
    return bool(compact_keyword) and compact_keyword == compact_query


def _is_expected_search_context(keyword: str, probe: dict, xml_text: str) -> bool:
    """只用搜索Activity和固定搜索框确认当前任务的搜索上下文。"""

    return (
        "GlobalSearchActivity" in (probe.get("activity") or "")
        and _keyword_matches_search_page(keyword, probe, xml_text)
    )


def _normalize_expected_search_results(
    keyword: str,
    probe: dict,
    xml_text: str,
) -> tuple[dict, bool]:
    """将分类器漏判、但证据完整的搜索结果页规范为search_results。

    页面归类与“搜索框是否等于当前任务词”是两件事：同词时可直接复用，
    异词时也必须先认出这是结果页，随后由既有query-reset分支点击顶部
    搜索框并替换关键词；不能错误回退到首页搜索入口。
    """

    if probe.get("page_kind") in {"search_results", "shop_product_list"}:
        return probe, False
    if "GlobalSearchActivity" not in (probe.get("activity") or ""):
        return probe, False
    if _fixed_search_query_from_probe(probe) is None:
        return probe, False
    # 固定搜索框只能证明处于搜索Activity；至少一张完整商品卡用于区分
    # 搜索结果页与仍停留在输入框的页面。
    if not find_product_cards(xml_text, limit=1):
        return probe, False
    return (
        {
            **probe,
            "page_kind": "search_results",
            "page_kind_source": "fixed_search_query",
        },
        _keyword_matches_search_page(keyword, probe, xml_text),
    )


def _current_search_query_matches(
    keyword: str,
    probe: dict,
    xml_text: str,
    *,
    android_unicode: bool,
    dry_run: bool,
) -> bool:
    """搜索Activity统一使用固定截图框；其他页面保留原兼容规则。"""

    if "GlobalSearchActivity" in (probe.get("activity") or ""):
        return _is_expected_search_context(keyword, probe, xml_text)
    if android_unicode and not dry_run:
        return _exact_top_query_matches(keyword, xml_text)
    return _keyword_matches_search_page(keyword, probe, xml_text)


def _normalize_activity_page_kind(probe: dict) -> dict:
    """分类器无结论时，用小红书明确Activity补足笔记详情身份。"""

    if probe.get("page_kind") != "unknown":
        return probe
    activity = str(probe.get("activity") or "")
    if "NoteDetailActivity" not in activity:
        return probe
    return {
        **probe,
        "page_kind": "note_detail",
        "page_kind_source": "activity",
    }


def _try_back_to_search_input(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    limits: MonitorLimits,
) -> tuple[dict, str] | None:
    if limits.dry_run:
        return None
    with connect(settings.db_path) as conn:
        record_run_event(
            conn,
            run_id=run_id,
            phase="search_ui",
            event="back_for_query_reset",
            task_id=task_id,
            data={"dry_run": limits.dry_run},
        )
    device.back()
    time.sleep(limits.wait_seconds)
    probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-query-back")
    _guard_probe(
        settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
    )
    xml_text = _read_ui(probe)
    if probe["page_kind"] == "search_input":
        return probe, xml_text
    return None


def _open_search_input_from_result_page(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    xml_text: str,
    limits: MonitorLimits,
    try_back_first: bool = True,
) -> tuple[dict, str]:
    if try_back_first:
        back_result = _try_back_to_search_input(
            settings,
            device,
            run_id=run_id,
            task_id=task_id,
            limits=limits,
        )
        if back_result:
            return back_result

    reset_targets = [
        target
        for target in (find_top_query_field(xml_text), find_clear_query_button(xml_text))
        if target is not None
    ][:2]
    if not reset_targets:
        raise MonitorBlocked("top query field not found for keyword reset")
    for index, target in enumerate(reset_targets, start=1):
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="tap_query_reset_target",
                task_id=task_id,
                data={"target": _target_dict(target), "attempt": index, "dry_run": limits.dry_run},
            )
        _tap(device, target, dry_run=limits.dry_run)
        if not limits.dry_run:
            time.sleep(limits.wait_seconds)
        probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-query-reset-{index}")
        _guard_probe(
            settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
        )
        xml_text = _read_ui(probe)
        if probe["page_kind"] == "search_input":
            return probe, xml_text
    raise MonitorBlocked(f"query reset did not open search input: {probe['page_kind']}")


def _opened_page_reason(probe: dict) -> str:
    text = probe.get("text") or ""
    if probe.get("page_kind") == "open_error":
        if "常在网上混" in text:
            return "opened product error page: 常在网上混，总有卡住的时候"
        return "opened product error page"
    return f"opened page is {probe.get('page_kind')}"


def _is_transient_open_probe(probe: dict) -> bool:
    text = re.sub(r"\s+", "", probe.get("text") or "")
    return probe.get("page_kind") == "unknown" and (
        not probe.get("activity")
        or ("小红书" in text and "你的生活兴趣社区" in text)
        or not probe.get("ocr_count")
    )


def _is_home_feed_misclassified_as_search_results(
    probe: dict,
    xml_text: str,
) -> bool:
    return (
        probe.get("page_kind") == "search_results"
        and "IndexActivityV2" in (probe.get("activity") or "")
        and find_home_search_entry(xml_text) is not None
    )


def _probe_search_input_after_entry(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    limits: MonitorLimits,
) -> dict:
    probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-search-input")
    _guard_probe(
        settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
    )
    for attempt in range(1, 3):
        if not _is_transient_open_probe(probe):
            break
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="wait_transient_search_entry",
                task_id=task_id,
                data={"attempt": attempt, "probe": probe},
            )
        if not limits.dry_run:
            time.sleep(limits.wait_seconds)
        probe = probe_current_page(
            settings,
            device,
            run_id=f"{run_id}-probe-search-input-stable-{attempt}",
        )
        _guard_probe(
            settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
        )
    return probe


def _probe_opened_product_page(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    limits: MonitorLimits,
) -> dict:
    probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-detail-{task_id}")
    _guard_probe(
        settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
    )
    for attempt in range(1, 3):
        if not _is_transient_open_probe(probe):
            break
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="wait_transient_product_open",
                task_id=task_id,
                data={"attempt": attempt, "probe": probe},
            )
        time.sleep(limits.wait_seconds)
        probe = probe_current_page(
            settings,
            device,
            run_id=f"{run_id}-probe-detail-stable-{task_id}-{attempt}",
        )
        _guard_probe(
            settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
        )
    return probe


def _recover_to_search_results_after_detail(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    expected_keyword: str,
    limits: MonitorLimits,
) -> bool:
    if limits.dry_run:
        return True
    last_probe: dict | None = None
    for attempt in range(1, 3):
        device.back()
        time.sleep(limits.wait_seconds)
        probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-after-detail-back-{attempt}")
        _guard_probe(
            settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
        )
        last_probe = probe
        is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")
        xml_text = _read_ui(probe)
        keyword_matches = _keyword_matches_search_page(
            expected_keyword,
            probe,
            xml_text,
        )
        fixed_search_context = _is_expected_search_context(
            expected_keyword,
            probe,
            xml_text,
        )
        is_verified_search_results = keyword_matches and (
            probe["page_kind"] == "search_results"
            or fixed_search_context
        )
        is_verified_shop_search_results = (
            probe["page_kind"] == "shop_product_list"
            and is_search_activity
            and keyword_matches
        )
        if is_verified_search_results or is_verified_shop_search_results:
            with connect(settings.db_path) as conn:
                record_run_event(
                    conn,
                    run_id=run_id,
                    phase="search_ui",
                    event="back_to_search_results",
                    task_id=task_id,
                    data={
                        "attempt": attempt,
                        "probe": probe,
                        "expected_keyword": expected_keyword,
                        "keyword_matches": keyword_matches,
                        "activity_match": is_search_activity,
                        "fixed_search_context": fixed_search_context,
                    },
                )
            return True
    reason = f"post-capture back did not reach search results: {last_probe.get('page_kind') if last_probe else 'unknown'}"
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "paused")
        set_monitor_state(conn, "last_block_reason", reason)
        record_run_event(
            conn,
            run_id=run_id,
            phase="search_ui",
            event="post_capture_back_failed",
            level="warning",
            task_id=task_id,
            message=reason,
            data={"probe": last_probe},
        )
    return False


def _recover_to_product_detail_after_note_evidence(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    limits: MonitorLimits,
) -> bool:
    if limits.dry_run:
        return True
    last_probe: dict | None = None
    for attempt in range(1, 4):
        probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-note-recover-{attempt}")
        _guard_probe(
            settings, run_id, probe, task_id, device=device, dry_run=limits.dry_run
        )
        last_probe = probe
        if probe.get("page_kind") == "product_detail":
            return True
        if (
            probe.get("page_kind") == "unknown"
            and not probe.get("activity")
            and not probe.get("ocr_count")
        ):
            time.sleep(limits.wait_seconds)
            continue
        if probe.get("page_kind") not in {"note_detail", "account_profile"}:
            break
        device.back()
        time.sleep(limits.wait_seconds)
    reason = f"note evidence recovery did not reach product detail: {last_probe.get('page_kind') if last_probe else 'unknown'}"
    with connect(settings.db_path) as conn:
        record_run_event(
            conn,
            run_id=run_id,
            phase="note_observation",
            event="note_evidence_recovery_failed",
            level="warning",
            task_id=task_id,
            message=reason,
            data={"probe": last_probe},
        )
    return False


def _capture_note_evidence_for_current_detail(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task_id: int,
    product_id: int | None,
    limits: MonitorLimits,
) -> dict:
    if not limits.note_evidence:
        return {"skipped": True, "skip_reason": "note evidence disabled"}
    result: dict[str, Any] = {"enabled": True}
    ocr_hard_stop = False
    try:
        note = open_related_note_once(
            settings,
            device,
            product_id=product_id,
            rank=max(1, limits.note_rank),
            wait_seconds=limits.wait_seconds,
            max_scrolls=max(0, limits.note_max_scrolls),
            dry_run=limits.dry_run,
        )
        result["note"] = note
        note_timeout = _find_nested_ocr_timeout_probe(note)
        if note_timeout is not None:
            probe_path, timeout_probe = note_timeout
            ocr_hard_stop = True
            _raise_ocr_timeout_hard_stop(
                settings,
                run_id=run_id,
                task_id=task_id,
                message=str(
                    timeout_probe.get("ocr_error")
                    or timeout_probe.get("risk_stop_reason")
                    or "RapidOCR exceeded its process deadline"
                ),
                phase=f"note_evidence_{probe_path.replace('.', '_')}_ocr",
                evidence=_preserve_probe_ocr_timeout_evidence(
                    timeout_probe,
                    device=device,
                ),
                dry_run=limits.dry_run,
                cleanup_note_observation_ids=(
                    [note["note_observation_id"]]
                    if type(note.get("note_observation_id")) is int
                    else None
                ),
            )
        if not note.get("skipped") and not limits.dry_run:
            author = open_note_author_profile_once(
                settings,
                device,
                product_id=product_id,
                wait_seconds=limits.wait_seconds,
                dry_run=limits.dry_run,
            )
            result["author"] = author
            author_timeout = _find_nested_ocr_timeout_probe(author)
            if author_timeout is not None:
                probe_path, timeout_probe = author_timeout
                ocr_hard_stop = True
                _raise_ocr_timeout_hard_stop(
                    settings,
                    run_id=run_id,
                    task_id=task_id,
                    message=str(
                        timeout_probe.get("ocr_error")
                        or timeout_probe.get("risk_stop_reason")
                        or "RapidOCR exceeded its process deadline"
                    ),
                    phase=f"note_author_{probe_path.replace('.', '_')}_ocr",
                    evidence=_preserve_probe_ocr_timeout_evidence(
                        timeout_probe,
                        device=device,
                    ),
                    dry_run=limits.dry_run,
                    cleanup_note_observation_ids=(
                        [author["note_observation_id"]]
                        if type(author.get("note_observation_id")) is int
                        else None
                    ),
                )
    except OcrInfrastructureBlocked:
        ocr_hard_stop = True
        raise
    except Exception as exc:
        result["error"] = str(exc)
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="note_observation",
                event="note_evidence_failed",
                level="warning",
                task_id=task_id,
                product_id=product_id,
                message=str(exc),
            )
    finally:
        if not limits.dry_run and not ocr_hard_stop:
            result["recovered_to_product_detail"] = _recover_to_product_detail_after_note_evidence(
                settings,
                device,
                run_id=run_id,
                task_id=task_id,
                limits=limits,
            )
    with connect(settings.db_path) as conn:
        record_run_event(
            conn,
            run_id=run_id,
            phase="note_observation",
            event="note_evidence_stage_finished",
            task_id=task_id,
            product_id=product_id,
            level="warning" if result.get("error") or result.get("recovered_to_product_detail") is False else "info",
            data=result,
        )
    return result


def _should_back_recover_from_shop_list(probe: dict) -> bool:
    if probe.get("page_kind") != "shop_product_list":
        return False
    activity = probe.get("activity") or ""
    if "GlobalSearchActivity" in activity:
        return False
    return "GoodsDetailActivity" in activity or "ShopDetailActivity" in activity


class CouponOverlayHardStop(RuntimeError):
    def __init__(self, reason: str, data: dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.data = data


def _close_visual_coupon_overlay_once(
    settings: Settings,
    device,
    *,
    probe: dict,
    run_id: str,
    task_id: int,
    dry_run: bool,
    wait_seconds: float,
) -> tuple[dict, dict]:
    """Close one verified translucent coupon control or fail closed."""

    activity = str(probe.get("activity") or "")
    base = {"activity": activity, "screenshot": probe.get("screenshot")}

    def hard_stop(reason: str, **extra: Any) -> None:
        raise CouponOverlayHardStop(reason, {**base, **extra})

    if COUPON_ACTIVITY not in activity:
        hard_stop("coupon_close_activity_not_translucent")
    if probe.get("risk_stop_reason"):
        hard_stop("coupon_close_risk_stop", risk=probe.get("risk_stop_reason"))
    if probe.get("has_anr"):
        hard_stop("coupon_close_anr")
    package = str(settings.emulator_config().get("package") or "com.xingin.xhs")
    pid_before = str(device.pidof(package) or "").strip()
    if not pid_before:
        hard_stop("coupon_close_pid_unknown")
    target = find_coupon_close_button(probe.get("screenshot") or "")
    if target is None:
        hard_stop("coupon_close_unique_visual_target_missing")
    target_data = {
        "x": target.x,
        "y": target.y,
        "bounds": asdict(target.bounds),
        "reason": target.reason,
    }
    if dry_run:
        hard_stop("coupon_close_dry_run_no_tap", target=target_data)

    device.tap(target.x, target.y)
    time.sleep(wait_seconds)
    after = probe_current_page(
        settings,
        device,
        run_id=f"{run_id}-probe-after-start-coupon-close",
    )
    pid_after = str(device.pidof(package) or "").strip()
    if not pid_after or pid_after != pid_before:
        hard_stop(
            "coupon_close_pid_changed",
            target=target_data,
            pid_before=pid_before,
            pid_after=pid_after or None,
            after_probe=after,
        )
    if after.get("risk_stop_reason"):
        hard_stop(
            "coupon_close_post_risk_stop",
            target=target_data,
            after_probe=after,
        )
    if after.get("has_anr"):
        hard_stop("coupon_close_post_anr", target=target_data, after_probe=after)
    after_activity = str(after.get("activity") or "")
    if COUPON_ACTIVITY in after_activity:
        hard_stop(
            "coupon_close_overlay_still_present",
            target=target_data,
            after_probe=after,
        )
    if (
        after.get("page_kind") not in {"shop_product_list", "account_profile"}
        or "ShopDetailActivity" not in after_activity
    ):
        hard_stop(
            "coupon_close_unknown_or_abnormal_destination",
            target=target_data,
            after_probe=after,
        )
    return after, {
        "target": target_data,
        "pid_before": pid_before,
        "pid_after": pid_after,
        "after_activity": after_activity,
    }


def _resolve_search_entry(probe: dict, xml_text: str) -> tuple[UiTarget | None, str]:
    search_button = find_search_product_button(xml_text)
    search_event = "tap_search_product_button"
    if search_button or probe.get("page_kind") != "home_feed":
        return search_button, search_event

    search_button = find_home_search_entry(xml_text)
    if search_button and search_button.reason == "home-search-button":
        return search_button, "tap_home_search_button"
    if search_button and search_button.reason == "home-search-bar":
        return search_button, "tap_home_search_bar"
    if search_button:
        return search_button, "tap_home_search_entry"

    if "IndexActivity" not in (probe.get("activity") or ""):
        return None, "tap_home_search_entry"
    screenshot = probe.get("screenshot")
    if not screenshot:
        return None, "tap_home_search_entry"
    search_button = find_home_search_icon(screenshot)
    if search_button:
        return search_button, "tap_home_search_visual_icon"
    return None, "tap_home_search_entry"


def _open_search_results(
    settings: Settings,
    device: AdbDevice,
    *,
    run_id: str,
    task: dict,
    limits: MonitorLimits,
) -> dict:
    config = settings.emulator_config()
    android_unicode = (
        str(config.get("backend") or "bluestacks").strip().casefold() == "android"
    )
    _, helper_ime, restore_ime = _android_unicode_input_settings(settings)
    probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-start")
    _guard_probe(
        settings, run_id, probe, task["id"], device=device, dry_run=limits.dry_run
    )
    probe = _normalize_activity_page_kind(probe)
    xml_text = _read_ui(probe)
    is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")
    if _is_home_feed_misclassified_as_search_results(probe, xml_text):
        probe = {**probe, "page_kind": "home_feed"}
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="home_feed_classification_corrected",
                task_id=task["id"],
                data={"activity": probe.get("activity")},
            )

    if COUPON_ACTIVITY in str(probe.get("activity") or ""):
        probe, coupon_close = _close_visual_coupon_overlay_once(
            settings,
            device,
            probe=probe,
            run_id=run_id,
            task_id=task["id"],
            dry_run=limits.dry_run,
            wait_seconds=limits.wait_seconds,
        )
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="coupon_closed_by_unique_visual_x",
                task_id=task["id"],
                data=coupon_close,
            )
        _guard_probe(
            settings, run_id, probe, task["id"], device=device, dry_run=limits.dry_run
        )
        xml_text = _read_ui(probe)
        is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")

    if (
        probe["page_kind"] in {"note_detail", "account_profile"}
        and limits.allow_back_recovery
        and not limits.dry_run
    ):
        for attempt in range(1, 4):
            with connect(settings.db_path) as conn:
                record_run_event(
                    conn,
                    run_id=run_id,
                    phase="search_ui",
                    event="back_recovery_from_note_context",
                    task_id=task["id"],
                    data={"attempt": attempt, "probe": probe},
                )
            device.back()
            time.sleep(limits.wait_seconds)
            probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-after-note-context-back-{attempt}")
            _guard_probe(
                settings, run_id, probe, task["id"], device=device, dry_run=limits.dry_run
            )
            probe = _normalize_activity_page_kind(probe)
            xml_text = _read_ui(probe)
            is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")
            probe, _ = _normalize_expected_search_results(
                task["keyword"], probe, xml_text
            )
            if probe["page_kind"] in {"product_detail", "search_results", "shop_product_list", "search_input"}:
                break

    if _should_back_recover_from_shop_list(probe) and limits.allow_back_recovery:
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="back_recovery_from_shop_list",
                task_id=task["id"],
                data={"dry_run": limits.dry_run, "probe": probe},
            )
        if not limits.dry_run:
            device.back()
            time.sleep(limits.wait_seconds)
        probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-after-back-recovery")
        _guard_probe(
            settings, run_id, probe, task["id"], device=device, dry_run=limits.dry_run
        )
        xml_text = _read_ui(probe)
        is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")

    probe, reused_search_context = _normalize_expected_search_results(
        task["keyword"], probe, xml_text
    )
    if reused_search_context:
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="round_start_search_context_reused",
                task_id=task["id"],
                data={
                    "keyword": task["keyword"],
                    "activity": probe.get("activity"),
                    "page_kind_source": probe.get("page_kind_source"),
                },
            )

    if probe["page_kind"] not in {"search_input", "search_results"} and not (
        probe["page_kind"] == "shop_product_list" and is_search_activity
    ):
        search_button, search_event = _resolve_search_entry(probe, xml_text)
        if not search_button:
            raise MonitorBlocked("search product button not found")
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event=search_event,
                task_id=task["id"],
                data={"target": _target_dict(search_button), "dry_run": limits.dry_run},
            )
        _tap(device, search_button, dry_run=limits.dry_run)
        if not limits.dry_run:
            time.sleep(limits.wait_seconds)
        probe = _probe_search_input_after_entry(
            settings,
            device,
            run_id=run_id,
            task_id=task["id"],
            limits=limits,
        )
        xml_text = _read_ui(probe)
        is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")

    if probe["page_kind"] == "search_input":
        input_result = _enter_keyword(
            device,
            xml_text,
            task["keyword"],
            dry_run=limits.dry_run,
            android_unicode=android_unicode,
            helper_ime=helper_ime,
            restore_ime=restore_ime,
            query_probe=(
                (
                    lambda attempt: _probe_search_input_query_before_submit(
                        settings,
                        device,
                        run_id=run_id,
                        task_id=task["id"],
                        attempt=attempt,
                    )
                )
                if android_unicode and not limits.dry_run
                else None
            ),
        )
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="keyword_submitted",
                task_id=task["id"],
                data={**input_result, "keyword": task["keyword"], "dry_run": limits.dry_run},
            )
        if not limits.dry_run:
            time.sleep(limits.wait_seconds)
        probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-search-results")
        _guard_probe(
            settings, run_id, probe, task["id"], device=device, dry_run=limits.dry_run
        )
        xml_text = _read_ui(probe)
        is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")
        probe, _ = _normalize_expected_search_results(
            task["keyword"], probe, xml_text
        )
        if (
            android_unicode
            and not limits.dry_run
            and not _current_search_query_matches(
                task["keyword"],
                probe,
                xml_text,
                android_unicode=android_unicode,
                dry_run=limits.dry_run,
            )
        ):
            raise MonitorBlocked("search results query mismatch after Unicode submit")

    should_reset_mismatched_query = (
        probe["page_kind"] == "search_results"
        or (probe["page_kind"] == "shop_product_list" and is_search_activity)
    )
    query_matches = _current_search_query_matches(
        task["keyword"],
        probe,
        xml_text,
        android_unicode=android_unicode,
        dry_run=limits.dry_run,
    )
    if should_reset_mismatched_query and not query_matches:
        probe, xml_text = _open_search_input_from_result_page(
            settings,
            device,
            run_id=run_id,
            task_id=task["id"],
            xml_text=xml_text,
            limits=limits,
            try_back_first=is_search_activity,
        )
        input_result = _enter_keyword(
            device,
            xml_text,
            task["keyword"],
            dry_run=limits.dry_run,
            android_unicode=android_unicode,
            helper_ime=helper_ime,
            restore_ime=restore_ime,
            query_probe=(
                (
                    lambda attempt: _probe_search_input_query_before_submit(
                        settings,
                        device,
                        run_id=run_id,
                        task_id=task["id"],
                        attempt=attempt,
                    )
                )
                if android_unicode and not limits.dry_run
                else None
            ),
        )
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="search_ui",
                event="keyword_resubmitted",
                task_id=task["id"],
                data={**input_result, "keyword": task["keyword"], "dry_run": limits.dry_run},
            )
        if not limits.dry_run:
            time.sleep(limits.wait_seconds)
        probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-search-results-reset")
        _guard_probe(
            settings, run_id, probe, task["id"], device=device, dry_run=limits.dry_run
        )
        xml_text = _read_ui(probe)
        is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")
        probe, _ = _normalize_expected_search_results(
            task["keyword"], probe, xml_text
        )
        reset_query_matches = _current_search_query_matches(
            task["keyword"],
            probe,
            xml_text,
            android_unicode=android_unicode,
            dry_run=limits.dry_run,
        )
        if not reset_query_matches:
            raise MonitorBlocked("search results keyword mismatch after reset")

    tab = find_product_tab(xml_text)
    if tab and probe["page_kind"] == "search_results":
        _tap(device, tab, dry_run=limits.dry_run)
        if not limits.dry_run:
            time.sleep(limits.wait_seconds)
        probe = probe_current_page(settings, device, run_id=f"{run_id}-probe-product-tab")
        _guard_probe(
            settings, run_id, probe, task["id"], device=device, dry_run=limits.dry_run
        )
        xml_text = _read_ui(probe)
        is_search_activity = "GlobalSearchActivity" in (probe.get("activity") or "")
        probe, _ = _normalize_expected_search_results(
            task["keyword"], probe, xml_text
        )

    if probe["page_kind"] == "shop_product_list" and not is_search_activity:
        raise MonitorBlocked("shop product list is not a search results page")
    if probe["page_kind"] not in {"search_results", "shop_product_list"}:
        raise MonitorBlocked(f"not on search results: {probe['page_kind']}")
    final_query_matches = _current_search_query_matches(
        task["keyword"],
        probe,
        xml_text,
        android_unicode=android_unicode,
        dry_run=limits.dry_run,
    )
    if not final_query_matches:
        raise MonitorBlocked("search results keyword mismatch")
    return {"probe": probe, "xml": xml_text}


def _ocr_timeout_monitor_output(
    *,
    run_id: str,
    dry_run: bool,
    blocked: OcrInfrastructureBlocked,
) -> dict:
    output = {
        "run_id": run_id,
        "dry_run": dry_run,
        "processed_tasks": 0,
        "captured_products": 0,
        "skipped": [
            {
                "task_id": blocked.timeout.get("task_id"),
                "reason": str(blocked),
                "reason_code": "ocr_timeout",
                "retryable": False,
                "retryable_after_resume": bool(
                    blocked.timeout.get("refunded_tasks")
                ),
            }
        ],
        "blocked": str(blocked),
        "reason_code": "ocr_timeout",
        "hard_stop": True,
        "requires_explicit_resume": True,
        "attempt_returned": bool(blocked.timeout.get("attempt_returned")),
        "ocr_timeout": blocked.timeout,
    }
    if blocked.timeout.get("lease_safety_blocked"):
        output["lease_safety_blocked"] = blocked.timeout[
            "lease_safety_blocked"
        ]
    return output


def _vision_fields_monitor_output(
    *,
    run_id: str,
    dry_run: bool,
    blocked: VisionInfrastructureBlocked,
) -> dict:
    failure = blocked.failure
    output = {
        "run_id": run_id,
        "dry_run": dry_run,
        "processed_tasks": 0,
        "captured_products": 0,
        "skipped": [
            {
                "task_id": failure.get("task_id"),
                "reason": str(blocked),
                "reason_code": "vision_fields_failure",
                "retryable": False,
                "retryable_after_resume": bool(failure.get("refunded_tasks")),
            }
        ],
        "blocked": str(blocked),
        "reason_code": "vision_fields_failure",
        "hard_stop": True,
        "requires_explicit_resume": True,
        "attempt_returned": bool(failure.get("attempt_returned")),
        "vision_fields_failure": failure,
    }
    if failure.get("lease_safety_blocked"):
        output["lease_safety_blocked"] = failure["lease_safety_blocked"]
    return output


def _ui_tree_monitor_output(
    *,
    run_id: str,
    dry_run: bool,
    blocked: UiTreeInfrastructureBlocked,
) -> dict:
    failure = blocked.failure
    output = {
        "run_id": run_id,
        "dry_run": dry_run,
        "processed_tasks": 0,
        "captured_products": 0,
        "skipped": [
            {
                "task_id": failure.get("task_id"),
                "reason": str(blocked),
                "reason_code": "ui_tree_unavailable",
                "retryable": False,
                "retryable_after_resume": bool(failure.get("refunded_tasks")),
            }
        ],
        "blocked": str(blocked),
        "reason_code": "ui_tree_unavailable",
        "hard_stop": True,
        "requires_explicit_resume": True,
        "attempt_returned": bool(failure.get("attempt_returned")),
        "ui_tree_failure": failure,
    }
    if failure.get("lease_safety_blocked"):
        output["lease_safety_blocked"] = failure["lease_safety_blocked"]
    return output


def monitor_once(settings: Settings, *, limits: MonitorLimits | None = None, ignore_paused: bool = False) -> dict:
    limits = limits or MonitorLimits()
    run_id = f"monitor-{uuid.uuid4().hex[:12]}"
    lease_ttl_seconds = max(
        900,
        int((limits.max_keywords * limits.max_products_per_keyword) * 240),
    )
    with connect(settings.db_path) as conn:
        lease_result = acquire_monitor_lease(
            conn,
            owner=run_id,
            ttl_seconds=lease_ttl_seconds,
            metadata={"limits": asdict(limits), "ignore_paused": ignore_paused},
        )
    if not lease_result["acquired"]:
        return {
            "run_id": run_id,
            "dry_run": limits.dry_run,
            "processed_tasks": 0,
            "captured_products": 0,
            "skipped": ["monitor already running"],
            "busy": True,
            "active_lease": lease_result.get("lease"),
        }
    result: dict | None = None
    try:
        try:
            result = _monitor_once_owned(
                settings,
                limits=limits,
                ignore_paused=ignore_paused,
                run_id=run_id,
                lease_ttl_seconds=lease_ttl_seconds,
            )
        except OcrInfrastructureBlocked as exc:
            result = _ocr_timeout_monitor_output(
                run_id=run_id,
                dry_run=limits.dry_run,
                blocked=exc,
            )
        except VisionInfrastructureBlocked as exc:
            result = _vision_fields_monitor_output(
                run_id=run_id,
                dry_run=limits.dry_run,
                blocked=exc,
            )
        except UiTreeInfrastructureBlocked as exc:
            result = _ui_tree_monitor_output(
                run_id=run_id,
                dry_run=limits.dry_run,
                blocked=exc,
            )
        except OcrTimeoutError as exc:
            try:
                _raise_ocr_timeout_hard_stop(
                    settings,
                    run_id=run_id,
                    task_id=None,
                    message=str(exc),
                    phase="monitor_ocr",
                    evidence={
                        "exception": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    },
                    dry_run=limits.dry_run,
                )
            except OcrInfrastructureBlocked as blocked:
                result = _ocr_timeout_monitor_output(
                    run_id=run_id,
                    dry_run=limits.dry_run,
                    blocked=blocked,
                )
        except AppUnresponsive as exc:
            result = _recover_xhs_after_unresponsive(
                settings,
                run_id=run_id,
                limits=limits,
                error=exc,
            )
        except subprocess.TimeoutExpired as exc:
            if not _is_adb_timeout(exc):
                raise
            result = _recover_xhs_after_unresponsive(
                settings,
                run_id=run_id,
                limits=limits,
                error=exc,
            )
        return result
    finally:
        with connect(settings.db_path) as conn:
            lease_safety_blocked = bool(
                result and result.get("lease_safety_blocked")
            )
            if lease_safety_blocked:
                block_reason = result["blocked"]
                set_monitor_desired_state(conn, "paused")
                set_monitor_state(conn, "risk_stop_reason", block_reason)
                set_monitor_state(conn, "last_block_reason", block_reason)
                recorded = conn.execute(
                    """
                    SELECT 1
                    FROM run_events
                    WHERE run_id=? AND event='lease_safety_blocked'
                    LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                if not recorded:
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="lease_safety",
                        event="lease_safety_blocked",
                        level="warning",
                        message=block_reason,
                        data=result["lease_safety_blocked"],
                    )
            unfinished = conn.execute(
                """
                SELECT id FROM search_tasks
                WHERE status='running' AND run_owner=?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
            if unfinished and result and result.get("reason_code") == "ocr_timeout":
                timeout = dict(result.get("ocr_timeout") or {})
                if not timeout.get("disposition_attempted"):
                    try:
                        disposition = record_ocr_timeout_hard_stop(
                            conn,
                            run_id=run_id,
                            owner=run_id,
                            reason=str(result["blocked"]),
                            phase=str(
                                timeout.get("phase") or "monitor_ocr_finalizer"
                            ),
                            task_id=int(unfinished[0]["id"]),
                            restore_status="pending",
                            refund_all_owned_tasks=True,
                            evidence=dict(timeout.get("evidence") or {}),
                            require_active_monitor_lease=True,
                        )
                        timeout.update(disposition)
                    except Exception as exc:
                        set_monitor_desired_state(conn, "paused")
                        set_monitor_state(
                            conn, "risk_stop_reason", str(result["blocked"])
                        )
                        set_monitor_state(
                            conn, "last_block_reason", str(result["blocked"])
                        )
                        finalizer_block = {
                            "reason": "ocr_timeout_finalizer_failed",
                            "owner": run_id,
                            "task_id": int(unfinished[0]["id"]),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        timeout.update(
                            {
                                "attempt_returned": False,
                                "disposition_attempted": True,
                                "lease_safety_blocked": finalizer_block,
                            }
                        )
                        result["lease_safety_blocked"] = finalizer_block
                result["attempt_returned"] = bool(
                    timeout.get("attempt_returned")
                )
                if timeout.get("lease_safety_blocked"):
                    result["lease_safety_blocked"] = timeout[
                        "lease_safety_blocked"
                    ]
                result["ocr_timeout"] = timeout
                # OCR disposition is authoritative.  Do not run the generic task
                # failure path after a success or a fail-closed lease refusal.
                unfinished = []
            if (
                unfinished
                and result
                and result.get("reason_code") == "vision_fields_failure"
            ):
                failure = dict(result.get("vision_fields_failure") or {})
                if not failure.get("disposition_attempted"):
                    try:
                        disposition = record_infrastructure_hard_stop(
                            conn,
                            run_id=run_id,
                            owner=run_id,
                            reason=str(result["blocked"]),
                            phase=str(
                                failure.get("phase")
                                or "product_detail_vision_finalizer"
                            ),
                            reason_code="vision_fields_failure",
                            event_name="vision_fields_hard_stop",
                            failure_label="vision-inference",
                            task_id=int(unfinished[0]["id"]),
                            restore_status="pending",
                            refund_all_owned_tasks=True,
                            evidence=dict(failure.get("evidence") or {}),
                            require_active_monitor_lease=True,
                        )
                        failure.update(disposition)
                    except Exception as exc:
                        set_monitor_desired_state(conn, "paused")
                        set_monitor_state(
                            conn, "risk_stop_reason", str(result["blocked"])
                        )
                        set_monitor_state(
                            conn, "last_block_reason", str(result["blocked"])
                        )
                        finalizer_block = {
                            "reason": "vision_fields_finalizer_failed",
                            "owner": run_id,
                            "task_id": int(unfinished[0]["id"]),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        failure.update(
                            {
                                "attempt_returned": False,
                                "disposition_attempted": True,
                                "lease_safety_blocked": finalizer_block,
                            }
                        )
                        result["lease_safety_blocked"] = finalizer_block
                result["attempt_returned"] = bool(
                    failure.get("attempt_returned")
                )
                if failure.get("lease_safety_blocked"):
                    result["lease_safety_blocked"] = failure[
                        "lease_safety_blocked"
                    ]
                result["vision_fields_failure"] = failure
                # 视觉基础设施处置已经决定任务状态，不能再走普通失败扣attempt。
                unfinished = []
            for row in unfinished:
                mark_task_failed(
                    conn,
                    task_id=row["id"],
                    owner=run_id,
                    reason=(
                        result["blocked"]
                        if lease_safety_blocked
                        else (
                            result.get("aborted_reason")
                            if result
                            else "monitor run ended before task completion"
                        )
                    ),
                    policy=RetryPolicy(),
                    retryable=not lease_safety_blocked,
                )
            release_monitor_lease(conn, owner=run_id)


def _monitor_once_owned(
    settings: Settings,
    *,
    limits: MonitorLimits,
    ignore_paused: bool,
    run_id: str,
    lease_ttl_seconds: int,
) -> dict:
    output: dict[str, Any] = {
        "run_id": run_id,
        "dry_run": limits.dry_run,
        "processed_tasks": 0,
        "captured_products": 0,
        "skipped": [],
    }
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        set_monitor_state(conn, "last_run_id", run_id)
        set_monitor_state(conn, "last_heartbeat", utcnow())
        if not limits.dry_run and (ignore_paused or state.get("desired_state") == "running"):
            set_monitor_state(conn, "last_block_reason", None)
            set_monitor_state(conn, "last_skip_reason", None)
        record_run_event(
            conn,
            run_id=run_id,
            phase="monitor",
            event="monitor_once_started",
            data={"limits": asdict(limits), "ignore_paused": ignore_paused},
        )
    if state.get("risk_stop_reason") and not limits.dry_run:
        output["blocked"] = state["risk_stop_reason"]
        output["skipped"].append("risk stop requires explicit resume")
        return output
    if state.get("desired_state") != "running" and not ignore_paused and not limits.dry_run:
        output["skipped"].append("monitor paused")
        return output

    requeued = 0
    if not limits.dry_run and limits.requeue_due_keywords:
        requeued = _requeue_due_keywords(
            settings,
            limit=max(1, limits.max_keywords),
            interval_hours=limits.recurring_interval_hours,
        )
    output["requeued_tasks"] = requeued
    device: AdbDevice | None = None
    if not limits.dry_run:
        config = settings.emulator_config()
        if str(config.get("backend") or "bluestacks").strip().casefold() == "android":
            try:
                device = _device(settings)
                device_preflight = _android_device_preflight(settings, device)
            except Exception as exc:
                device_preflight = {
                    "ready": False,
                    "serial": None,
                    "checks": [
                        {
                            "code": "device_selection",
                            "status": "hard_failure",
                            "message": "could not select the configured Android device",
                            "details": {"error": f"{type(exc).__name__}: {exc}"},
                        }
                    ],
                }
            output["device_preflight"] = device_preflight
            with connect(settings.db_path) as conn:
                record_run_event(
                    conn,
                    run_id=run_id,
                    phase="device_preflight",
                    event=(
                        "device_preflight_passed"
                        if device_preflight and device_preflight.get("ready")
                        else "device_preflight_failed"
                    ),
                    level=(
                        "info"
                        if device_preflight and device_preflight.get("ready")
                        else "warning"
                    ),
                    data=device_preflight,
                )
            if not device_preflight or not device_preflight.get("ready"):
                failed_codes = [
                    str(check.get("code"))
                    for check in (device_preflight or {}).get("checks", [])
                    if check.get("status") == "hard_failure"
                ]
                reason = "device preflight failed"
                if failed_codes:
                    reason += ": " + ", ".join(failed_codes)
                with connect(settings.db_path) as conn:
                    set_monitor_desired_state(conn, "paused")
                    set_monitor_state(conn, "last_block_reason", reason)
                output["blocked"] = reason
                output["skipped"].append("device preflight failed before task reservation")
                return output
            unicode_input_preflight = _android_unicode_input_preflight(settings, device)
            output["unicode_input_preflight"] = unicode_input_preflight
            with connect(settings.db_path) as conn:
                record_run_event(
                    conn,
                    run_id=run_id,
                    phase="device_preflight",
                    event=(
                        "unicode_input_preflight_passed"
                        if unicode_input_preflight.get("ready")
                        else "unicode_input_preflight_failed"
                    ),
                    level="info" if unicode_input_preflight.get("ready") else "warning",
                    data=unicode_input_preflight,
                )
            if not unicode_input_preflight.get("ready"):
                reason = (
                    "unicode input helper preflight failed before task reservation: "
                    + str(unicode_input_preflight.get("error") or "unknown")
                )
                with connect(settings.db_path) as conn:
                    set_monitor_desired_state(conn, "paused")
                    set_monitor_state(conn, "last_block_reason", reason)
                output["blocked"] = reason
                output["skipped"].append(
                    "unicode input helper failed before task reservation"
                )
                return output
            try:
                foreground_preflight = (
                    _prepare_android_xhs_foreground_before_task_reservation(
                        settings,
                        device,
                        run_id=run_id,
                        limits=limits,
                    )
                )
            except AppUnresponsive:
                raise
            except OcrInfrastructureBlocked as exc:
                output.update(
                    {
                        "blocked": str(exc),
                        "reason_code": "ocr_timeout",
                        "hard_stop": True,
                        "requires_explicit_resume": True,
                        "ocr_timeout": exc.timeout,
                    }
                )
                output["skipped"].append(
                    {
                        "task_id": None,
                        "reason": str(exc),
                        "reason_code": "ocr_timeout",
                        "retryable": False,
                        "retryable_after_resume": bool(
                            exc.timeout.get("refunded_tasks")
                        ),
                    }
                )
                return output
            except MonitorBlocked as exc:
                with connect(settings.db_path) as conn:
                    set_monitor_desired_state(conn, "paused")
                    set_monitor_state(conn, "last_block_reason", str(exc))
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="monitor",
                        event="monitor_blocked_before_task_reservation",
                        level="warning",
                        message=str(exc),
                    )
                output["blocked"] = str(exc)
                output["skipped"].append(
                    "Xiaohongshu foreground preflight failed before task reservation"
                )
                return output
            output["foreground_preflight"] = foreground_preflight

    if limits.dry_run:
        tasks = _next_pending_tasks(settings, max(1, limits.max_keywords))
    else:
        tasks = []
        with connect(settings.db_path) as conn:
            for _ in range(max(1, limits.max_keywords)):
                task = reserve_next_runnable_task(
                    conn,
                    owner=run_id,
                    policy=RetryPolicy(),
                    task_id=limits.task_id,
                    expected_keyword=limits.expected_keyword,
                )
                if not task:
                    break
                tasks.append(task)
    if not tasks:
        output["skipped"].append("no pending task")
        return output

    round_app_restarted = False
    for task in tasks:
        if output["processed_tasks"] >= limits.max_keywords:
            break
        try:
            _lease_safety_checkpoint(
                settings,
                run_id=run_id,
                task_id=task["id"],
                lease_ttl_seconds=lease_ttl_seconds,
                phase="before_first_device_operation",
                renew=True,
                dry_run=limits.dry_run,
            )
            if device is None:
                device = _device(settings)
            if (
                limits.restart_app_before_round
                and not limits.dry_run
                and not round_app_restarted
            ):
                restart_probe = _restart_xhs_to_safe_page(
                    settings,
                    device,
                    run_id=run_id,
                    limits=limits,
                    event="pre_round_app_restart",
                    task_id=task["id"],
                )
                round_app_restarted = True
                output["pre_round_app_restart"] = {
                    "restarted": True,
                    "page_kind": restart_probe.get("page_kind"),
                }
            result_page = _open_search_results(
                settings,
                device,
                run_id=run_id,
                task=task,
                limits=limits,
            )
            _lease_safety_checkpoint(
                settings,
                run_id=run_id,
                task_id=task["id"],
                lease_ttl_seconds=lease_ttl_seconds,
                phase="after_search_stage",
                renew=False,
                dry_run=limits.dry_run,
            )
            cards, card, actual_result_rank, result_page = _locate_ranked_product_card(
                settings,
                device,
                run_id=run_id,
                task_id=task["id"],
                keyword=task["keyword"],
                result_page=result_page,
                limits=limits,
            )
            if not cards:
                with connect(settings.db_path) as conn:
                    retry = mark_task_failed(
                        conn,
                        task_id=task["id"],
                        owner=run_id,
                        reason="no product card found",
                        policy=RetryPolicy(),
                        retryable=True,
                    )
                output["skipped"].append(
                    {
                        "task_id": task["id"],
                        "reason": "no product card found",
                        "retry": retry,
                    }
                )
                continue
            if card is None or actual_result_rank is None:
                raise MonitorBlocked(
                    f"requested product rank {limits.search_result_rank} not found",
                    hard=True,
                )
            package = str(
                settings.emulator_config().get("package") or "com.xingin.xhs"
            )
            process_crashed = False
            repeated_process_crash = False
            crash_recovery_count = 0
            process_change: dict[str, str | None] | None = None
            while True:
                tap_event = (
                    "tap_product_card"
                    if crash_recovery_count == 0
                    else "retap_product_card_after_process_restart"
                )
                with connect(settings.db_path) as conn:
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="search_ui",
                        event=tap_event,
                        task_id=task["id"],
                        data={
                            "target": _target_dict(card),
                            "requested_rank": limits.search_result_rank,
                            "rank": actual_result_rank,
                            "visible_card_count": len(cards),
                            "crash_recovery_count": crash_recovery_count,
                            "dry_run": limits.dry_run,
                        },
                    )
                _lease_safety_checkpoint(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    phase="before_product_click_and_wait",
                    renew=True,
                    dry_run=limits.dry_run,
                )
                process_before = _device_process_id(device, package)
                _tap(device, card, dry_run=limits.dry_run)
                if limits.dry_run:
                    output["processed_tasks"] += 1
                    output["captured_products"] += 0
                    break
                time.sleep(limits.wait_seconds)
                detail_probe = _probe_opened_product_page(
                    settings,
                    device,
                    run_id=run_id,
                    task_id=task["id"],
                    limits=limits,
                )
                process_after = _device_process_id(device, package)
                _lease_safety_checkpoint(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    phase="after_product_click_and_detail_probe",
                    renew=False,
                    dry_run=limits.dry_run,
                )
                if detail_probe["page_kind"] == "product_detail":
                    break
                if not _app_process_restarted(process_before, process_after):
                    break

                process_crashed = True
                process_change = {
                    "before": process_before,
                    "after": process_after,
                }
                with connect(settings.db_path) as conn:
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="app_recovery",
                        event="app_process_restart_detected_during_product_open",
                        level="warning",
                        task_id=task["id"],
                        message="小红书进程在打开商品详情时崩溃并被系统重启",
                        data={
                            "process": process_change,
                            "probe": detail_probe,
                            "recovery_count": crash_recovery_count,
                        },
                    )
                if crash_recovery_count >= 1:
                    repeated_process_crash = True
                    break

                crash_recovery_count += 1
                _lease_safety_checkpoint(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    phase="before_product_open_crash_recovery",
                    renew=True,
                    dry_run=limits.dry_run,
                )
                restart_probe = _restart_xhs_to_safe_page(
                    settings,
                    device,
                    run_id=run_id,
                    limits=limits,
                    event="product_open_crash_recovery",
                    task_id=task["id"],
                )
                result_page = _open_search_results(
                    settings,
                    device,
                    run_id=run_id,
                    task=task,
                    limits=limits,
                )
                _lease_safety_checkpoint(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    phase="after_product_open_crash_research",
                    renew=False,
                    dry_run=limits.dry_run,
                )
                cards, card, actual_result_rank, result_page = _locate_ranked_product_card(
                    settings,
                    device,
                    run_id=run_id,
                    task_id=task["id"],
                    keyword=task["keyword"],
                    result_page=result_page,
                    limits=limits,
                )
                if card is None or actual_result_rank is None:
                    raise MonitorBlocked(
                        "no product card found after app process crash recovery"
                    )
                output["app_process_crash_recovery"] = {
                    "attempted": True,
                    "safe_page": restart_probe.get("page_kind"),
                    "keyword": task["keyword"],
                }

            if limits.dry_run:
                continue
            if detail_probe["page_kind"] != "product_detail":
                reason = (
                    "Xiaohongshu process crashed again while opening product"
                    if repeated_process_crash
                    else _opened_page_reason(detail_probe)
                )
                with connect(settings.db_path) as conn:
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="search_ui",
                        event="opened_non_product_detail",
                        level="warning",
                        task_id=task["id"],
                        message=reason,
                        data={"probe": detail_probe, "process": process_change},
                    )
                if not limits.dry_run:
                    if process_crashed or detail_probe.get("page_kind") == "home_feed" or _is_transient_open_probe(detail_probe):
                        block_reason = (
                            reason
                            if process_crashed
                            else f"app left search flow while opening product: {detail_probe['page_kind']}"
                        )
                        with connect(settings.db_path) as conn:
                            retry = mark_task_failed(
                                conn,
                                task_id=task["id"],
                                owner=run_id,
                                reason=reason,
                                policy=RetryPolicy(),
                                retryable=True,
                            )
                            set_monitor_state(conn, "last_skip_reason", reason)
                            set_monitor_desired_state(conn, "paused")
                            set_monitor_state(conn, "last_block_reason", block_reason)
                        output["skipped"].append(
                            {
                                "task_id": task["id"],
                                "reason": reason,
                                "retry": retry,
                            }
                        )
                        output["blocked"] = block_reason
                        break
                    # 恢复动作必须发生在任务仍由当前run持有时。旧顺序先
                    # mark_task_failed清空run_owner，再做租约检查，导致任何
                    # 非商品页恢复都必然报task_not_running。
                    _lease_safety_checkpoint(
                        settings,
                        run_id=run_id,
                        task_id=task["id"],
                        lease_ttl_seconds=lease_ttl_seconds,
                        phase="before_non_product_recovery",
                        renew=True,
                        dry_run=limits.dry_run,
                    )
                    device.back()
                    time.sleep(limits.wait_seconds)
                    recovery_probe = probe_current_page(
                        settings,
                        device,
                        run_id=f"{run_id}-probe-after-non-product-back-{task['id']}",
                    )
                    _guard_probe(
                        settings,
                        run_id,
                        recovery_probe,
                        task["id"],
                        device=device,
                        dry_run=limits.dry_run,
                    )
                    _lease_safety_checkpoint(
                        settings,
                        run_id=run_id,
                        task_id=task["id"],
                        lease_ttl_seconds=lease_ttl_seconds,
                        phase="after_non_product_recovery",
                        renew=False,
                        dry_run=limits.dry_run,
                    )
                    is_search_activity = "GlobalSearchActivity" in (recovery_probe.get("activity") or "")
                    if (
                        is_search_activity
                        and recovery_probe.get("page_kind")
                        not in {"search_results", "shop_product_list"}
                    ):
                        recovery_xml = _read_ui(recovery_probe)
                        recovery_probe, _ = _normalize_expected_search_results(
                            task["keyword"], recovery_probe, recovery_xml
                        )
                    with connect(settings.db_path) as conn:
                        retry = mark_task_failed(
                            conn,
                            task_id=task["id"],
                            owner=run_id,
                            reason=reason,
                            policy=RetryPolicy(),
                            retryable=True,
                        )
                        set_monitor_state(conn, "last_skip_reason", reason)
                    output["skipped"].append(
                        {"task_id": task["id"], "reason": reason, "retry": retry}
                    )
                    if not (is_search_activity and recovery_probe["page_kind"] in {"search_results", "shop_product_list"}):
                        output["blocked"] = f"non-product recovery did not reach search results: {recovery_probe['page_kind']}"
                        break
                continue
            _lease_safety_checkpoint(
                settings,
                run_id=run_id,
                task_id=task["id"],
                lease_ttl_seconds=lease_ttl_seconds,
                phase="before_detail_capture_and_metrics_ocr",
                renew=True,
                dry_run=limits.dry_run,
            )
            try:
                capture = capture_current_page_for_task(
                    settings,
                    device,
                    task["id"],
                    capture_metrics=True,
                    metrics_swipe=limits.metrics_swipe,
                    metrics_max_frames=limits.metrics_max_frames,
                    require_keyword_match=False,
                    run_id=run_id,
                    complete_task=False,
                    manage_task_state=False,
                )
            except OcrTimeoutError as exc:
                _raise_ocr_timeout_hard_stop(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    message=str(exc),
                    phase="current_detail_ocr",
                    evidence={
                        "exception": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    },
                    dry_run=limits.dry_run,
                )
            if capture.get("reason_code") == "ocr_timeout" or capture.get(
                "ocr_timeout"
            ):
                timeout = capture.get("ocr_timeout")
                timeout = dict(timeout) if isinstance(timeout, dict) else {}
                exception = timeout.get("exception") or capture.get("exception") or {}
                _raise_ocr_timeout_hard_stop(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    message=str(
                        exception.get("message")
                        or capture.get("risk_stop_reason")
                        or "RapidOCR exceeded its process deadline"
                    ),
                    phase=str(timeout.get("phase") or "current_detail_ocr"),
                    evidence=dict(
                        timeout.get("evidence") or capture.get("evidence") or {}
                    ),
                    dry_run=limits.dry_run,
                )
            if capture.get("reason_code") == "vision_fields_failure" or capture.get(
                "vision_fields_failure"
            ):
                failure = capture.get("vision_fields_failure")
                failure = dict(failure) if isinstance(failure, dict) else {}
                exception = failure.get("exception") or capture.get("exception") or {}
                evidence = dict(
                    failure.get("evidence") or capture.get("evidence") or {}
                )
                if exception.get("code") and not evidence.get("error_code"):
                    evidence["error_code"] = exception["code"]
                _raise_vision_fields_hard_stop(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    message=str(
                        exception.get("message")
                        or capture.get("risk_stop_reason")
                        or "本地视觉模型未返回可用标题和价格"
                    ),
                    evidence=evidence,
                    dry_run=limits.dry_run,
                )
            _lease_safety_checkpoint(
                settings,
                run_id=run_id,
                task_id=task["id"],
                lease_ttl_seconds=lease_ttl_seconds,
                phase="after_detail_capture_and_metrics_ocr",
                renew=False,
                dry_run=limits.dry_run,
            )
            disposition = capture.get("task_disposition")
            if disposition:
                disposition_status = str(
                    disposition.get("status") or "needs_manual_detail"
                )
                disposition_reason = str(
                    disposition.get("reason")
                    or capture.get("skip_task_link_reason")
                    or "详情采集未通过安全分类"
                )
                with connect(settings.db_path) as conn:
                    stop_task(
                        conn,
                        task["id"],
                        disposition_status,
                        disposition_reason,
                    )
                raise MonitorBlocked(disposition_reason, hard=True)
            with connect(settings.db_path) as conn:
                record_search_result_evidence(
                    conn,
                    task_id=task["id"],
                    product_id=capture.get("product_id"),
                    observation_id=capture.get("observation_id"),
                    source_keyword=task["keyword"],
                    result_rank=actual_result_rank,
                    page_kind=result_page["probe"].get("page_kind"),
                    search_probe_dir=result_page["probe"].get("probe_dir"),
                    search_screenshot_path=result_page["probe"].get("screenshot"),
                    text_excerpt=(result_page["probe"].get("text") or "")[:500],
                )
            output["processed_tasks"] += 1
            output["captured_products"] += 1
            if limits.seller_profile:
                _lease_safety_checkpoint(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    phase="before_seller_profile",
                    renew=True,
                    dry_run=limits.dry_run,
                )
                seller_profile = capture_seller_profile_from_product(
                    settings,
                    device,
                    run_id=run_id,
                    task_id=task["id"],
                    product_id=capture["product_id"],
                    wait_seconds=limits.wait_seconds,
                )
                output.setdefault("seller_profiles", []).append(
                    {"task_id": task["id"], "product_id": capture.get("product_id"), **seller_profile}
                )
                seller_timeout = _find_nested_ocr_timeout_probe(seller_profile)
                if seller_timeout is not None:
                    probe_key, timeout_probe = seller_timeout
                    _raise_ocr_timeout_hard_stop(
                        settings,
                        run_id=run_id,
                        task_id=task["id"],
                        message=str(
                            timeout_probe.get("ocr_error")
                            or timeout_probe.get("risk_stop_reason")
                            or "RapidOCR exceeded its process deadline"
                        ),
                        phase=f"seller_profile_{probe_key}_ocr",
                        evidence=_preserve_probe_ocr_timeout_evidence(
                            timeout_probe,
                            device=device,
                        ),
                        dry_run=limits.dry_run,
                    )
                if seller_profile.get("blocked"):
                    reason = seller_profile.get("reason") or "店铺粉丝采集触发安全停止"
                    raise MonitorBlocked(reason, hard=True)
                _lease_safety_checkpoint(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    phase="after_seller_profile",
                    renew=False,
                    dry_run=limits.dry_run,
                )
                if seller_profile.get("skipped"):
                    disposition = seller_profile.get("task_disposition") or {}
                    reason = str(
                        disposition.get("reason")
                        or seller_profile.get("skip_reason")
                        or "seller_profile_skipped"
                    )
                    _lease_safety_checkpoint(
                        settings,
                        run_id=run_id,
                        task_id=task["id"],
                        lease_ttl_seconds=lease_ttl_seconds,
                        phase="before_return_after_seller_skip",
                        renew=True,
                        dry_run=limits.dry_run,
                    )
                    recovered = _recover_to_search_results_after_detail(
                        settings,
                        device,
                        run_id=run_id,
                        task_id=task["id"],
                        expected_keyword=task["keyword"],
                        limits=limits,
                    )
                    _lease_safety_checkpoint(
                        settings,
                        run_id=run_id,
                        task_id=task["id"],
                        lease_ttl_seconds=lease_ttl_seconds,
                        phase="after_return_after_seller_skip",
                        renew=False,
                        dry_run=limits.dry_run,
                    )
                    if not recovered:
                        raise MonitorBlocked(
                            "seller profile skipped and search results recovery failed"
                        )
                    with connect(settings.db_path) as conn:
                        retry = mark_task_failed(
                            conn,
                            task_id=task["id"],
                            owner=run_id,
                            reason=reason,
                            policy=RetryPolicy(),
                            retryable=bool(disposition.get("retryable", True)),
                        )
                        record_run_event(
                            conn,
                            run_id=run_id,
                            phase="seller_profile",
                            event="seller_profile_skipped",
                            level="warning",
                            task_id=task["id"],
                            observation_id=capture.get("observation_id"),
                            product_id=capture.get("product_id"),
                            message=reason,
                            data={
                                "retry": retry,
                                "seller_profile": seller_profile,
                            },
                        )
                    output["skipped"].append(
                        {
                            "task_id": task["id"],
                            "reason": reason,
                            "retry": retry,
                        }
                    )
                    continue
            if limits.note_evidence:
                _lease_safety_checkpoint(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    phase="before_note_evidence",
                    renew=True,
                    dry_run=limits.dry_run,
                )
            note_evidence = _capture_note_evidence_for_current_detail(
                settings,
                device,
                run_id=run_id,
                task_id=task["id"],
                product_id=capture.get("product_id"),
                limits=limits,
            )
            if limits.note_evidence:
                _lease_safety_checkpoint(
                    settings,
                    run_id=run_id,
                    task_id=task["id"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    phase="after_note_evidence",
                    renew=False,
                    dry_run=limits.dry_run,
                )
                output.setdefault("note_evidence", []).append(
                    {"task_id": task["id"], "product_id": capture.get("product_id"), **note_evidence}
                )
            _lease_safety_checkpoint(
                settings,
                run_id=run_id,
                task_id=task["id"],
                lease_ttl_seconds=lease_ttl_seconds,
                phase="before_return_to_search_results",
                renew=True,
                dry_run=limits.dry_run,
            )
            recovered = _recover_to_search_results_after_detail(
                settings,
                device,
                run_id=run_id,
                task_id=task["id"],
                expected_keyword=task["keyword"],
                limits=limits,
            )
            _lease_safety_checkpoint(
                settings,
                run_id=run_id,
                task_id=task["id"],
                lease_ttl_seconds=lease_ttl_seconds,
                phase="after_return_to_search_results",
                renew=False,
                dry_run=limits.dry_run,
            )
            if not recovered:
                output["blocked"] = "post-capture back did not reach search results"
                break
            with connect(settings.db_path) as conn:
                product_row = conn.execute(
                    """
                    SELECT p.title, p.share_url, o.raw_signals_json, o.screenshot_path
                    FROM observations o
                    JOIN products p ON p.id=o.product_id
                    WHERE o.id=?
                    """,
                    (capture["observation_id"],),
                ).fetchone()
                gray_items = gray_metric_items(product_row["raw_signals_json"])
                if len(gray_items) >= 3 and product_row["title"]:
                    evidence_path = (
                        result_page["probe"].get("screenshot")
                        or product_row["screenshot_path"]
                    )
                    decomposition = decompose_product_keywords(
                        source_root=task["keyword"],
                        source_keyword=task["keyword"],
                        run_id=run_id,
                        task_id=task["id"],
                        product_id=capture["product_id"],
                        observation_id=capture["observation_id"],
                        raw_title=product_row["title"],
                        search_result_rank=actual_result_rank,
                        search_context_recovered=True,
                        evidence_path=evidence_path,
                        evidence={
                            "gray_metric_items": list(gray_items),
                            "search_probe_dir": result_page["probe"].get("probe_dir"),
                            "search_screenshot_path": result_page["probe"].get("screenshot"),
                            "detail_screenshot_path": product_row["screenshot_path"],
                        },
                        discovery_roots=(task["keyword"],),
                        share_url=product_row["share_url"],
                        link_gap=None if product_row["share_url"] else "商品分享链接待补采",
                    )
                    record_id = persist_product_keyword_decomposition(
                        conn,
                        decomposition,
                        evidence_allowed_roots=(settings.data_dir,),
                    )
                    output.setdefault("keyword_decompositions", []).append(
                        {
                            "record_id": record_id,
                            "product_id": capture["product_id"],
                            "terms": {
                                name: [term.as_dict() for term in terms]
                                for name, terms in decomposition.terms.items()
                            },
                            "status": decomposition.decomposition_status,
                        }
                    )
                capture["task_result"] = complete_task_from_observation(
                    conn,
                    task["id"],
                    capture["observation_id"],
                )
                record_run_event(
                    conn,
                    run_id=run_id,
                    phase="monitor",
                    event="task_completed",
                    task_id=task["id"],
                    observation_id=capture.get("observation_id"),
                    product_id=capture.get("product_id"),
                    message="商品采集、补充取证和搜索页恢复均完成",
                )
        except LeaseSafetyBlocked as exc:
            output["blocked"] = str(exc)
            output["lease_safety_blocked"] = {
                "phase": exc.phase,
                "reason": exc.reason,
            }
            output["skipped"].append(
                {
                    "task_id": task["id"],
                    "reason": str(exc),
                    "retryable": False,
                }
            )
            break
        except AppUnresponsive:
            raise
        except OcrInfrastructureBlocked as exc:
            output.update(
                {
                    "blocked": str(exc),
                    "reason_code": "ocr_timeout",
                    "hard_stop": True,
                    "requires_explicit_resume": True,
                    "ocr_timeout": exc.timeout,
                }
            )
            output["skipped"].append(
                {
                    "task_id": task["id"],
                    "reason": str(exc),
                    "reason_code": "ocr_timeout",
                    "retryable": False,
                    "retryable_after_resume": bool(
                        exc.timeout.get("refunded_tasks")
                    ),
                }
            )
            break
        except UiTreeInfrastructureBlocked as exc:
            failure = exc.failure
            output.update(
                {
                    "blocked": str(exc),
                    "reason_code": "ui_tree_unavailable",
                    "hard_stop": True,
                    "requires_explicit_resume": True,
                    "attempt_returned": bool(failure.get("attempt_returned")),
                    "ui_tree_failure": failure,
                }
            )
            if failure.get("lease_safety_blocked"):
                output["lease_safety_blocked"] = failure[
                    "lease_safety_blocked"
                ]
            output["skipped"].append(
                {
                    "task_id": task["id"],
                    "reason": str(exc),
                    "reason_code": "ui_tree_unavailable",
                    "retryable": False,
                    "retryable_after_resume": bool(failure.get("refunded_tasks")),
                }
            )
            break
        except MonitorBlocked as exc:
            with connect(settings.db_path) as conn:
                if not limits.dry_run:
                    if exc.hard:
                        set_monitor_desired_state(conn, "paused")
                        set_monitor_state(conn, "risk_stop_reason", str(exc))
                    else:
                        set_monitor_desired_state(conn, "paused")
                        task_state = conn.execute(
                            "SELECT status, run_owner FROM search_tasks WHERE id=?",
                            (task["id"],),
                        ).fetchone()
                        if (
                            task_state
                            and task_state["status"] == "running"
                            and task_state["run_owner"] == run_id
                        ):
                            mark_task_failed(
                                conn,
                                task_id=task["id"],
                                owner=run_id,
                                reason=str(exc),
                                policy=RetryPolicy(),
                                retryable=True,
                            )
                        set_monitor_state(conn, "last_block_reason", str(exc))
                record_run_event(
                    conn,
                    run_id=run_id,
                    phase="monitor",
                    event="monitor_blocked",
                    level="warning",
                    task_id=task["id"],
                    message=str(exc),
                )
            output["blocked"] = str(exc)
            break

    report = generate_candidate_report(settings, limit=20)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "last_report_path", report["report_path"])
        set_monitor_state(conn, "last_heartbeat", utcnow())
        record_run_event(
            conn,
            run_id=run_id,
            phase="monitor",
            event="monitor_once_finished",
            data={**output, "report": report},
        )
    output["report"] = report
    return output


def monitor_loop(
    settings: Settings,
    *,
    limits: MonitorLimits | None = None,
    interval_seconds: int = 900,
    max_rounds: int | None = None,
) -> dict:
    limits = limits or MonitorLimits()
    rounds = 0
    last_output = None
    while max_rounds is None or rounds < max_rounds:
        with connect(settings.db_path) as conn:
            if get_monitor_state(conn).get("desired_state") != "running":
                break
        last_output = monitor_once(settings, limits=limits)
        rounds += 1
        if last_output.get("blocked"):
            break
        time.sleep(interval_seconds)
    return {"rounds": rounds, "last_output": last_output}
