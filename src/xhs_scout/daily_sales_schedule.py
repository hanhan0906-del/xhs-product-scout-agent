from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable, Mapping

from .config import Settings
from .daily_sales_collector import DirectLinkDailySalesCollector
from .daily_sales_runner import (
    prepare_daily_sales_cycle,
    run_prepared_daily_sales_cycle,
)
from .daily_sales_tracking import SHANGHAI_TZ
from .db import (
    connect,
    set_monitor_desired_state,
    set_monitor_state,
)


CollectorFactory = Callable[[], Callable[..., Mapping[str, Any]]]


def midnight_cycle_date(now: datetime) -> str | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(SHANGHAI_TZ)
    if local.hour == 0 and 0 <= local.minute <= 15:
        return local.date().isoformat()
    return None


def run_due_daily_sales_cycle(
    settings: Settings,
    *,
    now: datetime,
    collector_factory: CollectorFactory | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    cycle_date = midnight_cycle_date(now)
    if cycle_date is None:
        return {"due": False, "cycle_date": None, "reason": "outside_midnight_window"}

    factory = collector_factory or (
        lambda: DirectLinkDailySalesCollector(settings)
    )
    runner_owner = owner or f"daily-sales-{uuid.uuid4().hex[:12]}"
    with connect(settings.db_path) as conn:
        prepared = prepare_daily_sales_cycle(
            conn,
            cycle_date,
            created_at=now,
        )
        summary = run_prepared_daily_sales_cycle(
            conn,
            cycle_date,
            owner=runner_owner,
            collector=factory(),
            now=now,
            recovery_now=now,
        )
        output = {
            "due": True,
            "cycle_date": cycle_date,
            "prepared": prepared,
            "summary": summary,
        }
        set_monitor_state(conn, "last_daily_sales_output", output)
        if summary.get("hard_stop_reason"):
            reason = (
                "daily sales tracking stopped: "
                f"{summary['hard_stop_reason']}"
            )
            set_monitor_state(conn, "risk_stop_reason", reason)
            set_monitor_state(conn, "last_block_reason", reason)
            set_monitor_desired_state(conn, "paused")
        return output
