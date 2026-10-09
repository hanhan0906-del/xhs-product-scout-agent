from __future__ import annotations

import uuid
from pathlib import Path

from .config import Settings
from .db import (
    connect,
    record_infrastructure_hard_stop,
    record_ocr_timeout_hard_stop,
    record_run_event,
    utcnow,
)
from .detail_metrics import capture_metrics_strip, has_metrics, update_observation_with_metrics
from .emulator import AdbDevice
from .ingest import ingest_image, persist_ingest_result
from .ocr import OcrTimeoutError
from .product_link import (
    capture_product_share_url,
    is_supported_product_direct_url,
    is_supported_product_url,
)
from .probe import _focused_activity
from .vision_fields import VisionFieldsError


STARTABLE_STATUSES = ("pending", "paused", "needs_manual_detail")


def _ocr_timeout_reason(message: str) -> str:
    return f"OCR infrastructure timeout: {message}"


def _persist_ocr_timeout_xml(
    settings: Settings,
    *,
    run_id: str,
    task_id: int,
    ui_tree: str,
) -> tuple[str | None, str | None]:
    if not ui_tree:
        return None, "UI tree was empty before OCR timeout"
    xml_path = settings.capture_dir / f"{run_id}-task-{task_id}-ocr-timeout.xml"
    try:
        xml_path.write_text(ui_tree, encoding="utf-8")
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return str(xml_path), None


def _finish_ocr_timeout(
    settings: Settings,
    *,
    output: dict,
    task: dict,
    run_id: str,
    task_id: int,
    phase: str,
    manage_task_state: bool,
    conn=None,
) -> dict:
    timeout = output.get("ocr_timeout")
    timeout_payload = dict(timeout) if isinstance(timeout, dict) else {}
    exception = timeout_payload.get("exception") or output.get("exception") or {}
    message = str(
        exception.get("message")
        or output.get("risk_stop_reason")
        or "RapidOCR exceeded its process deadline"
    )
    reason = _ocr_timeout_reason(message)
    evidence = dict(timeout_payload.get("evidence") or output.get("evidence") or {})
    timeout_payload.update(
        {
            "reason_code": "ocr_timeout",
            "run_id": run_id,
            "task_id": task_id,
            "phase": phase,
            "exception": {
                "type": str(exception.get("type") or "OcrTimeoutError"),
                "message": message,
            },
            "evidence": evidence,
        }
    )

    hard_stop = {
        "hard_stop": True,
        "reason_code": "ocr_timeout",
        "reason": reason,
        "phase": phase,
        "refunded_tasks": [],
        "evidence": evidence,
    }
    restore_status = str(task.get("status") or "pending")
    if restore_status not in STARTABLE_STATUSES:
        restore_status = "pending"
    if manage_task_state:
        if conn is not None:
            hard_stop = record_ocr_timeout_hard_stop(
                conn,
                run_id=run_id,
                owner=run_id,
                reason=reason,
                phase=phase,
                task_id=task_id,
                restore_status=restore_status,
                evidence=evidence,
            )
        else:
            with connect(settings.db_path) as timeout_conn:
                hard_stop = record_ocr_timeout_hard_stop(
                    timeout_conn,
                    run_id=run_id,
                    owner=run_id,
                    reason=reason,
                    phase=phase,
                    task_id=task_id,
                    restore_status=restore_status,
                    evidence=evidence,
                )

    output.update(
        {
            "run_id": run_id,
            "task_id": task_id,
            "keyword": task["keyword"],
            "page_kind": "ocr_timeout",
            "reason_code": "ocr_timeout",
            "infrastructure_failure": True,
            "hard_stop": True,
            "blocked": reason,
            "risk_stopped": True,
            "risk_stop_reason": reason,
            "ocr_timeout": timeout_payload,
            "ocr_timeout_disposition": hard_stop,
            "task_result": None,
            "task_disposition": {
                "status": restore_status,
                "reason": reason,
                "reason_code": "ocr_timeout",
                "infrastructure_failure": True,
                "attempt_returned": bool(hard_stop.get("refunded_tasks")),
                "retryable_after_resume": bool(hard_stop.get("refunded_tasks")),
            },
            "skip_task_link_reason": reason,
        }
    )
    output.pop("_deferred_ingest", None)
    return output


def _finish_vision_fields_failure(
    settings: Settings,
    *,
    error: VisionFieldsError,
    task: dict,
    run_id: str,
    task_id: int,
    manage_task_state: bool,
) -> dict:
    message = str(error)
    reason = f"Local vision infrastructure failure: {message}"
    evidence = {
        **error.evidence,
        "error_code": error.code,
    }
    restore_status = str(task.get("status") or "pending")
    if restore_status not in STARTABLE_STATUSES:
        restore_status = "pending"
    hard_stop = {
        "hard_stop": True,
        "reason_code": "vision_fields_failure",
        "reason": reason,
        "phase": "product_detail_vision",
        "refunded_tasks": [],
        "evidence": evidence,
    }
    if manage_task_state:
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
                restore_status=restore_status,
                evidence=evidence,
            )
    failure = {
        "reason_code": "vision_fields_failure",
        "run_id": run_id,
        "task_id": task_id,
        "phase": "product_detail_vision",
        "exception": {
            "type": type(error).__name__,
            "code": error.code,
            "message": message,
        },
        "evidence": evidence,
    }
    return {
        "image": evidence.get("screenshot"),
        "stored": evidence.get("screenshot"),
        "run_id": run_id,
        "task_id": task_id,
        "keyword": task["keyword"],
        "page_kind": "vision_fields_failure",
        "reason_code": "vision_fields_failure",
        "infrastructure_failure": True,
        "hard_stop": True,
        "blocked": reason,
        "risk_stopped": True,
        "risk_stop_reason": reason,
        "exception": failure["exception"],
        "evidence": evidence,
        "vision_fields_failure": failure,
        "vision_fields_disposition": hard_stop,
        "task_result": None,
        "task_disposition": {
            "status": restore_status,
            "reason": reason,
            "reason_code": "vision_fields_failure",
            "infrastructure_failure": True,
            "attempt_returned": bool(hard_stop.get("refunded_tasks")),
            "retryable_after_resume": bool(hard_stop.get("refunded_tasks")),
        },
        "skip_task_link_reason": reason,
    }


def keyword_visible_on_page(keyword: str, text: str) -> bool:
    compact_keyword = "".join(keyword.split())
    compact_text = "".join(text.split())
    return bool(compact_keyword) and compact_keyword in compact_text


def _persist_product_link_result(conn, product_id: int, link_result: dict) -> bool:
    share_url = link_result.get("share_url")
    direct_url = link_result.get("direct_url")
    if not share_url and not direct_url:
        return False
    conn.execute(
        """
        UPDATE products
        SET share_url=COALESCE(NULLIF(?, ''), share_url),
            direct_url=COALESCE(NULLIF(?, ''), direct_url),
            last_seen_at=?
        WHERE id=?
        """,
        (share_url, direct_url, utcnow(), product_id),
    )
    return True


def start_task(conn, task_id: int, *, owner: str | None = None) -> dict:
    row = conn.execute(
        "SELECT id, keyword, status, attempts, run_owner FROM search_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"搜索任务不存在：{task_id}")
    if row["status"] == "running":
        if owner and row["run_owner"] == owner:
            return dict(row)
        raise ValueError(f"任务 {task_id} 已由其它运行持有")
    if row["status"] not in STARTABLE_STATUSES:
        raise ValueError(f"任务 {task_id} 当前状态不可启动：{row['status']}")
    now = utcnow()
    conn.execute(
        """
        UPDATE search_tasks
        SET status='running', attempts=attempts+1, last_error=NULL,
            run_owner=COALESCE(?, run_owner), last_started_at=?, updated_at=?
        WHERE id=?
        """,
        (owner, now, now, task_id),
    )
    return dict(row)


def stop_task(conn, task_id: int, status: str, reason: str) -> None:
    if status not in {"paused", "needs_manual_detail", "risk_stopped"}:
        raise ValueError(f"不支持的停止状态：{status}")
    conn.execute(
        """
        UPDATE search_tasks
        SET status=?, last_error=?, run_owner=NULL, run_lease_expires_at=NULL,
            last_finished_at=?, updated_at=?
        WHERE id=?
        """,
        (status, reason, utcnow(), utcnow(), task_id),
    )


def complete_task_from_observation(conn, task_id: int, observation_id: int) -> dict:
    task = conn.execute(
        "SELECT id, keyword, status FROM search_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError(f"搜索任务不存在：{task_id}")
    if task["status"] == "completed":
        raise ValueError(f"任务 {task_id} 已完成，不能重复关联")
    observation = conn.execute(
        "SELECT id, product_id, observed_at FROM observations WHERE id=?",
        (observation_id,),
    ).fetchone()
    if observation is None or observation["product_id"] is None:
        raise ValueError(f"观察记录不可关联：{observation_id}")
    now = utcnow()
    conn.execute(
        """
        INSERT OR IGNORE INTO task_results(task_id, product_id, observation_id, captured_at)
        VALUES (?, ?, ?, ?)
        """,
        (task_id, observation["product_id"], observation_id, observation["observed_at"]),
    )
    conn.execute(
        """
        UPDATE search_tasks
        SET status='completed', last_error=NULL, next_run_at=NULL,
            run_owner=NULL, run_lease_expires_at=NULL,
            last_finished_at=?, updated_at=?
        WHERE id=?
        """,
        (now, now, task_id),
    )
    return {
        "task_id": task_id,
        "keyword": task["keyword"],
        "product_id": observation["product_id"],
        "observation_id": observation_id,
        "status": "completed",
    }


def capture_current_page_for_task(
    settings: Settings,
    device: AdbDevice,
    task_id: int,
    destination: Path | None = None,
    capture_metrics: bool = False,
    metrics_roi: tuple[int, int, int, int] | None = None,
    metrics_swipe: bool = False,
    metrics_max_frames: int = 3,
    require_keyword_match: bool = False,
    run_id: str | None = None,
    complete_task: bool = True,
    manage_task_state: bool = True,
) -> dict:
    run_id = run_id or f"detail-{uuid.uuid4().hex[:12]}"
    with connect(settings.db_path) as conn:
        task = start_task(conn, task_id, owner=run_id)
        record_run_event(
            conn,
            run_id=run_id,
            phase="current_detail",
            event="task_started",
            task_id=task_id,
            message=f"开始采集当前详情页：{task['keyword']}",
        )

    screenshot = destination or settings.data_dir / "emulator-current.png"
    ui_tree = ""
    stable_activity = None
    try:
        window_before = ""
        context_error = None
        try:
            window_before = device.window_focus()
        except Exception as exc:
            context_error = f"window_before:{type(exc).__name__}:{exc}"
        device.screenshot(screenshot)
        window_after = ""
        try:
            ui_tree = device.ui_dump()
            window_after = device.window_focus()
        except Exception as exc:
            context_error = f"ui_context:{type(exc).__name__}:{exc}"
        activity_before = _focused_activity(window_before)
        activity_after = _focused_activity(window_after)
        stable_activity = (
            activity_before
            if activity_before and activity_before == activity_after
            else None
        )
        output = ingest_image(
            settings,
            screenshot,
            source="android_emulator_task",
            activity=stable_activity,
            ui_tree=ui_tree if stable_activity else "",
            required_page_kind="product_detail",
            run_id=run_id,
            task_id=task_id,
            persist=not capture_metrics,
        )
        output["page_context"] = {
            "activity": stable_activity,
            "activity_stable": bool(stable_activity),
            "ui_dump_ok": bool(ui_tree),
            "error": context_error,
        }
    except OcrTimeoutError as exc:
        xml_path, xml_error = _persist_ocr_timeout_xml(
            settings,
            run_id=run_id,
            task_id=task_id,
            ui_tree=ui_tree,
        )
        output = {
            "image": str(screenshot),
            "stored": str(screenshot),
            "exception": {"type": type(exc).__name__, "message": str(exc)},
            "evidence": {
                "screenshot": str(screenshot),
                "xml": xml_path,
                "xml_error": xml_error,
                "activity": stable_activity,
            },
            "ocr_timeout": {
                "exception": {"type": type(exc).__name__, "message": str(exc)},
                "evidence": {
                    "screenshot": str(screenshot),
                    "xml": xml_path,
                    "xml_error": xml_error,
                    "activity": stable_activity,
                },
            },
        }
        return _finish_ocr_timeout(
            settings,
            output=output,
            task=task,
            run_id=run_id,
            task_id=task_id,
            phase="current_detail_ocr",
            manage_task_state=manage_task_state,
        )
    except VisionFieldsError as exc:
        return _finish_vision_fields_failure(
            settings,
            error=exc,
            task=task,
            run_id=run_id,
            task_id=task_id,
            manage_task_state=manage_task_state,
        )
    except Exception as exc:
        with connect(settings.db_path) as conn:
            if manage_task_state:
                stop_task(conn, task_id, "paused", f"采集失败：{exc}")
            record_run_event(
                conn,
                run_id=run_id,
                phase="current_detail",
                event="capture_failed",
                level="error",
                task_id=task_id,
                message=str(exc),
            )
        raise

    if output.get("reason_code") == "ocr_timeout" or output.get("ocr_timeout"):
        return _finish_ocr_timeout(
            settings,
            output=output,
            task=task,
            run_id=run_id,
            task_id=task_id,
            phase="current_detail_ocr",
            manage_task_state=manage_task_state,
        )

    with connect(settings.db_path) as conn:
        if output.get("risk_stopped"):
            reason = f"页面出现停止信号：{output['risk_stop_reason']}"
            if manage_task_state:
                stop_task(conn, task_id, "risk_stopped", reason)
            output["task_disposition"] = {
                "status": "risk_stopped",
                "reason": reason,
            }
            output["skip_task_link_reason"] = reason
            record_run_event(
                conn,
                run_id=run_id,
                phase="current_detail",
                event="risk_stopped",
                level="warning",
                task_id=task_id,
                message=output["risk_stop_reason"],
            )
        elif output.get("skipped"):
            if manage_task_state:
                stop_task(conn, task_id, "needs_manual_detail", output["skip_reason"])
            output["task_disposition"] = {
                "status": "needs_manual_detail",
                "reason": output["skip_reason"],
            }
            output["task_result"] = None
            output["skip_task_link_reason"] = output["skip_reason"]
            record_run_event(
                conn,
                run_id=run_id,
                phase="current_detail",
                event="page_skipped",
                level="warning",
                task_id=task_id,
                message=output["skip_reason"],
            )
        elif output.get("page_kind") != "product_detail":
            reason = f"当前页不是商品详情页：{output.get('page_kind')}"
            if manage_task_state:
                stop_task(conn, task_id, "needs_manual_detail", reason)
            output["task_disposition"] = {
                "status": "needs_manual_detail",
                "reason": reason,
            }
            output["task_result"] = None
            output["skip_task_link_reason"] = reason
            record_run_event(
                conn,
                run_id=run_id,
                phase="current_detail",
                event="not_product_detail",
                level="warning",
                task_id=task_id,
                observation_id=output.get("observation_id"),
                product_id=output.get("product_id"),
                message=reason,
                data={"page_kind": output.get("page_kind")},
            )
        elif require_keyword_match and not keyword_visible_on_page(task["keyword"], output.get("text", "")):
            reason = f"当前页未出现任务关键词：{task['keyword']}"
            if manage_task_state:
                stop_task(conn, task_id, "needs_manual_detail", reason)
            output["task_disposition"] = {
                "status": "needs_manual_detail",
                "reason": reason,
            }
            output["task_result"] = None
            output["skip_task_link_reason"] = reason
            record_run_event(
                conn,
                run_id=run_id,
                phase="current_detail",
                event="keyword_mismatch",
                level="warning",
                task_id=task_id,
                observation_id=output.get("observation_id"),
                product_id=output.get("product_id"),
                message=reason,
            )
        else:
            if capture_metrics:
                try:
                    metrics = capture_metrics_strip(
                        settings,
                        device,
                        roi=metrics_roi,
                        max_frames=metrics_max_frames,
                        allow_swipe=metrics_swipe,
                    )
                except OcrTimeoutError as exc:
                    xml_path, xml_error = _persist_ocr_timeout_xml(
                        settings,
                        run_id=run_id,
                        task_id=task_id,
                        ui_tree=ui_tree,
                    )
                    output.update(
                        {
                            "exception": {
                                "type": type(exc).__name__,
                                "message": str(exc),
                            },
                            "evidence": {
                                "screenshot": str(output.get("stored") or screenshot),
                                "xml": xml_path,
                                "xml_error": xml_error,
                                "activity": stable_activity,
                                "product_id": output.get("product_id"),
                                "observation_id": output.get("observation_id"),
                            },
                            "ocr_timeout": {
                                "exception": {
                                    "type": type(exc).__name__,
                                    "message": str(exc),
                                },
                                "evidence": {
                                    "screenshot": str(output.get("stored") or screenshot),
                                    "xml": xml_path,
                                    "xml_error": xml_error,
                                    "activity": stable_activity,
                                    "product_id": output.get("product_id"),
                                    "observation_id": output.get("observation_id"),
                                },
                            },
                        }
                    )
                    return _finish_ocr_timeout(
                        settings,
                        output=output,
                        task=task,
                        run_id=run_id,
                        task_id=task_id,
                        phase="metrics_strip_ocr",
                        manage_task_state=manage_task_state,
                        conn=conn,
                    )
                output = persist_ingest_result(settings, output, conn=conn)
                # The base observation is complete only after every required
                # OCR stage has returned. Commit it before the metrics helper
                # opens its own short-lived connection for the merge.
                conn.commit()
                output["metrics_strip"] = metrics
                if has_metrics(metrics["signals"]):
                    output["metrics_update"] = update_observation_with_metrics(
                        settings,
                        output["observation_id"],
                        metrics,
                    )
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="metrics_strip",
                        event="metrics_updated",
                        task_id=task_id,
                        observation_id=output.get("observation_id"),
                        product_id=output.get("product_id"),
                        message="指标条已合并入观察记录",
                        data={"signals": metrics["signals"], "capture_dir": metrics["capture_dir"]},
                    )
                else:
                    output["metrics_update"] = None
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="metrics_strip",
                        event="metrics_skipped",
                        level="warning",
                        task_id=task_id,
                        observation_id=output.get("observation_id"),
                        product_id=output.get("product_id"),
                        message=metrics.get("skip_reason") or "指标条未识别到可合并指标",
                        data={"capture_dir": metrics["capture_dir"]},
                    )
            try:
                link_result = capture_product_share_url(device)
                if link_result.get("share_url") and not is_supported_product_url(
                    link_result["share_url"]
                ):
                    link_result = {
                        "share_url": None,
                        "skip_reason": "captured URL failed Xiaohongshu product validation",
                    }
                if link_result.get("direct_url") and not is_supported_product_direct_url(
                    link_result["direct_url"]
                ):
                    link_result["direct_url"] = None
                    link_result["direct_url_gap"] = (
                        "resolved target failed Xiaohongshu product validation"
                    )
                output["product_link"] = link_result
                if link_result.get("share_url") or link_result.get("direct_url"):
                    _persist_product_link_result(
                        conn,
                        output["product_id"],
                        link_result,
                    )
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="product_link",
                        event=(
                            "product_link_captured"
                            if link_result.get("share_url")
                            else "product_direct_url_captured"
                        ),
                        task_id=task_id,
                        observation_id=output.get("observation_id"),
                        product_id=output.get("product_id"),
                        data={
                            "share_url": link_result["share_url"],
                            "direct_url": link_result.get("direct_url"),
                            "direct_url_resolution": link_result.get(
                                "direct_url_resolution"
                            ),
                            "direct_url_gap": link_result.get("direct_url_gap"),
                            "share_url_gap": link_result.get("skip_reason"),
                        },
                    )
                else:
                    record_run_event(
                        conn,
                        run_id=run_id,
                        phase="product_link",
                        event="product_link_skipped",
                        level="warning",
                        task_id=task_id,
                        observation_id=output.get("observation_id"),
                        product_id=output.get("product_id"),
                        message=link_result.get("skip_reason"),
                    )
            except Exception as exc:
                output["product_link"] = {"share_url": None, "skip_reason": str(exc)}
                record_run_event(
                    conn,
                    run_id=run_id,
                    phase="product_link",
                    event="product_link_failed",
                    level="warning",
                    task_id=task_id,
                    observation_id=output.get("observation_id"),
                    product_id=output.get("product_id"),
                    message=str(exc),
                )
            if complete_task:
                output["task_result"] = complete_task_from_observation(
                    conn,
                    task_id,
                    output["observation_id"],
                )
                record_run_event(
                    conn,
                    run_id=run_id,
                    phase="current_detail",
                    event="task_completed",
                    task_id=task_id,
                    observation_id=output.get("observation_id"),
                    product_id=output.get("product_id"),
                    message="当前详情页任务完成",
                )
            else:
                output["task_result"] = None
    output["keyword"] = task["keyword"]
    output["run_id"] = run_id
    return output


def next_startable_task(conn) -> dict | None:
    row = conn.execute(
        """
        SELECT id, keyword, status, attempts
        FROM search_tasks
        WHERE status IN ('pending', 'paused', 'needs_manual_detail')
        ORDER BY priority DESC, id
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def capture_next_current_detail(
    settings: Settings,
    device: AdbDevice,
    *,
    capture_metrics: bool = True,
    metrics_swipe: bool = False,
    metrics_max_frames: int = 3,
    require_keyword_match: bool = True,
) -> dict:
    run_id = f"pilot-{uuid.uuid4().hex[:12]}"
    with connect(settings.db_path) as conn:
        task = next_startable_task(conn)
    if task is None:
        with connect(settings.db_path) as conn:
            record_run_event(
                conn,
                run_id=run_id,
                phase="current_detail",
                event="no_startable_task",
                level="warning",
                message="没有可启动的搜索任务",
            )
        return {
            "skipped": True,
            "skip_reason": "没有可启动的搜索任务",
            "run_id": run_id,
        }
    output = capture_current_page_for_task(
        settings,
        device,
        task["id"],
        capture_metrics=capture_metrics,
        metrics_swipe=metrics_swipe,
        metrics_max_frames=metrics_max_frames,
        require_keyword_match=require_keyword_match,
        run_id=run_id,
    )
    output["pilot_mode"] = "current_detail_only"
    output["pilot_limits"] = {
        "max_tasks": 1,
        "max_products": 1,
        "search_ui": False,
        "transaction_clicks": False,
        "metrics_swipe": metrics_swipe,
    }
    return output
