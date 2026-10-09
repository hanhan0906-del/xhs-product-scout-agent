from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping

from .daily_sales_tracking import (
    DailySalesBatchHardStop,
    HARD_STOP_REASONS,
    claim_daily_sales_task,
    get_daily_sales_cycle_summary,
    get_next_pending_daily_sales_task,
    hard_stop_daily_sales_cycle,
    initialize_daily_sales_tracking,
    plan_midnight_cycle,
    record_daily_sales_result,
    recover_expired_daily_sales_tasks,
)
from .db import followed_product_sales_snapshot


Collector = Callable[..., Mapping[str, Any]]
COLLECTOR_KINDS = {"exact", "fuzzy", "failed", "skipped", "hard_stop"}


def prepare_daily_sales_cycle(
    conn,
    cycle_date: str | date,
    *,
    created_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Freeze today's upstream-maintained followed-product snapshot."""
    initialize_daily_sales_tracking(conn)
    followed = followed_product_sales_snapshot(conn)
    snapshot = [
        {
            "product_id": item["product_id"],
            "verified_direct_url": item["verified_direct_url"],
        }
        for item in followed
    ]
    result = plan_midnight_cycle(
        conn,
        cycle_date=cycle_date,
        followed_products=snapshot,
        created_at=created_at,
    )
    return {
        **result,
        "current_followed_count": len(snapshot),
        "snapshot_frozen": result["code"]
        in {"snapshot_created", "already_planned", "snapshot_frozen_mismatch"},
    }


def run_prepared_daily_sales_cycle(
    conn,
    cycle_date: str | date,
    *,
    owner: str,
    collector: Collector,
    now: str | datetime | None = None,
    recovery_now: str | datetime | None = None,
    lease_seconds: int = 300,
    recover_expired: bool = True,
) -> dict[str, Any]:
    """Run pending snapshot items sequentially using only their frozen direct URLs."""
    recovered_count = 0
    processed_count = 0
    collector_calls = 0
    if recover_expired:
        recovery = recover_expired_daily_sales_tasks(
            conn,
            now=recovery_now if recovery_now is not None else _timestamp(now),
            recovery_owner=owner,
        )
        recovered_count = recovery["recovered_count"]

    while True:
        task = get_next_pending_daily_sales_task(conn, cycle_date=cycle_date)
        if not task["available"]:
            break

        action_time = _timestamp(now)
        try:
            claim = claim_daily_sales_task(
                conn,
                plan_id=task["plan_id"],
                owner=owner,
                now=action_time,
                lease_seconds=lease_seconds,
            )
        except DailySalesBatchHardStop as error:
            _persist_database_hard_stop_if_possible(
                conn,
                cycle_date=cycle_date,
                owner=owner,
                error=error,
                action_at=action_time,
            )
            break
        if not claim["claimed"]:
            if claim["code"] == "batch_hard_stopped":
                break
            # Another owner or a terminal transition won the race. Re-read state.
            continue

        try:
            collector_calls += 1
            raw_result = collector(
                product_id=task["product_id"],
                verified_direct_url=task["verified_direct_url"],
            )
            normalized = _normalize_collector_result(raw_result, task["product_id"])
        except DailySalesBatchHardStop as error:
            normalized = {
                "outcome": "hard_stop",
                "reason_code": error.reason_code,
                "reason_detail": error.detail,
                "observed_product_id": task["product_id"],
                "observed_at": action_time,
            }
        except Exception as error:
            normalized = {
                "outcome": "failed",
                "reason_code": "collector_exception",
                "reason_detail": f"{type(error).__name__}: {error}",
                "observed_product_id": task["product_id"],
                "observed_at": action_time,
            }

        try:
            recorded = record_daily_sales_result(
                conn,
                plan_id=task["plan_id"],
                owner=owner,
                action_at=_timestamp(now),
                **normalized,
            )
        except DailySalesBatchHardStop as error:
            _persist_database_hard_stop_if_possible(
                conn,
                cycle_date=cycle_date,
                owner=owner,
                error=error,
                action_at=_timestamp(now),
            )
            break
        if recorded.get("recorded"):
            processed_count += 1
        if recorded.get("continue_batch") is False:
            break

    summary = _compact_summary(
        get_daily_sales_cycle_summary(conn, cycle_date=cycle_date)
    )
    return {
        **summary,
        "processed_this_run": processed_count,
        "collector_calls": collector_calls,
        "recovered_this_run": recovered_count,
    }


def _normalize_collector_result(
    value: Mapping[str, Any], expected_product_id: int
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("collector_result_must_be_mapping")
    kind = value.get("kind")
    if kind not in COLLECTOR_KINDS:
        raise ValueError("invalid_collector_result_kind")

    observed_at = value.get("observed_at")
    if observed_at is None:
        raise ValueError("collector_observed_at_required")
    reason_code = value.get("reason_code")
    reason_detail = value.get("reason_detail")

    if kind == "hard_stop":
        if reason_code not in HARD_STOP_REASONS:
            raise ValueError("invalid_hard_stop_reason")
        return {
            "outcome": "hard_stop",
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "observed_product_id": (
                None
                if reason_code == "identity_unknown"
                else value.get("observed_product_id", expected_product_id)
            ),
            "observed_at": observed_at,
        }

    observed_product_id = value.get("observed_product_id")
    if kind in {"exact", "fuzzy"} and observed_product_id is None:
        return {
            "outcome": "hard_stop",
            "reason_code": "identity_unknown",
            "reason_detail": "collector_result_missing_observed_product_id",
            "observed_product_id": None,
            "observed_at": observed_at,
        }
    if observed_product_id is None:
        observed_product_id = expected_product_id

    if kind == "exact":
        exact = value.get("cumulative_sales_exact")
        if type(exact) is not int or exact < 0:
            raise ValueError("invalid_exact_sales")
        return {
            "outcome": "sample",
            "observed_product_id": observed_product_id,
            "observed_at": observed_at,
            "cumulative_sales_exact": exact,
            "cumulative_sales_display": value.get("cumulative_sales_display"),
        }
    if kind == "fuzzy":
        display = value.get("cumulative_sales_display")
        if not isinstance(display, str) or not display.strip():
            raise ValueError("invalid_fuzzy_sales_display")
        return {
            "outcome": "sample",
            "observed_product_id": observed_product_id,
            "observed_at": observed_at,
            "cumulative_sales_display": display,
        }
    return {
        "outcome": kind,
        "reason_code": reason_code or f"collector_{kind}",
        "reason_detail": reason_detail,
        "observed_product_id": observed_product_id,
        "observed_at": observed_at,
    }


def _persist_database_hard_stop_if_possible(
    conn,
    *,
    cycle_date: str | date,
    owner: str,
    error: DailySalesBatchHardStop,
    action_at: str,
) -> None:
    try:
        hard_stop_daily_sales_cycle(
            conn,
            cycle_date=cycle_date,
            reason_code=error.reason_code,
            reason_detail=error.detail,
            owner=owner,
            action_at=action_at,
        )
    except DailySalesBatchHardStop:
        raise error


def _timestamp(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_must_include_timezone")
        return value.isoformat(timespec="seconds")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_must_include_timezone")
    return parsed.isoformat(timespec="seconds")


def _compact_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    pending = int(summary.get("pending", 0))
    running = int(summary.get("running", 0))
    return {
        "cycle_date": summary["cycle_date"],
        "batch_status": summary["batch_status"],
        "total": int(summary.get("total", 0)),
        "completed_exact": int(summary.get("completed_exact", 0)),
        "completed_fuzzy": int(summary.get("completed_fuzzy", 0)),
        "failed": int(summary.get("failed", 0)),
        "skipped": int(summary.get("skipped", 0)),
        "hard_stopped": int(summary.get("risk_stopped", 0)),
        "pending": pending,
        "running": running,
        "remaining": pending + running,
        "hard_stop_reason": summary.get("hard_stop_reason"),
        "all_items_final": bool(summary.get("all_items_final", False)),
    }
