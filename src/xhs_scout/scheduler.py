from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable

from .config import Settings
from .continuous_discovery import (
    DEFAULT_DISCOVERY_ROOTS,
    load_continuous_discovery_roots,
    plan_continuous_discovery_round,
)
from .daily_sales_schedule import run_due_daily_sales_cycle
from .db import (
    connect,
    get_monitor_state,
    set_monitor_desired_state,
    set_monitor_state,
    utcnow,
)
from .insights import ensure_portfolio_queue
from .monitor import MonitorLimits, monitor_once
from .run_control import RetryPolicy, mark_task_failed, release_monitor_lease


class MonitorScheduler:
    """Run conservative monitor rounds in one daemon thread per web process."""

    def __init__(
        self,
        settings: Settings,
        *,
        interval_seconds: int = 3600,
        idle_interval_seconds: int = 60,
        limits: MonitorLimits | None = None,
        recovery_initial_seconds: int = 60,
        recovery_max_seconds: int = 900,
        max_consecutive_failures: int = 3,
    ) -> None:
        self.settings = settings
        # A successful round may hand off directly to the next one.  Idle or
        # unsuccessful rounds still use a bounded backoff so a disconnected
        # device or an exhausted keyword set cannot create a busy loop.
        self.interval_seconds = max(0, int(interval_seconds))
        self.idle_interval_seconds = max(1, int(idle_interval_seconds))
        self.recovery_initial_seconds = max(1, int(recovery_initial_seconds))
        self.recovery_max_seconds = max(
            self.recovery_initial_seconds,
            int(recovery_max_seconds),
        )
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))
        self.limits = limits or MonitorLimits(
            max_keywords=1,
            max_products_per_keyword=1,
            wait_seconds=6,
            metrics_swipe=True,
            metrics_max_frames=3,
            recurring_interval_hours=24,
            note_evidence=False,
            requeue_due_keywords=False,
            # Keep a healthy Xiaohongshu process warm between rounds.  An
            # unconditional cold restart can overlap the app's background
            # native-library initialization with GlobalSearchActivity startup
            # and leave the search Activity without a drawn window.  ANR and
            # process-crash recovery remain responsible for targeted restarts.
            restart_app_before_round=False,
        )
        self._guard = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._worker_state = "stopped"
        self._last_exception: dict[str, Any] | None = None
        self._consecutive_failures = 0
        self._recovery_count = 0
        self._next_retry_at: str | None = None

    def start(self) -> bool:
        with self._guard:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._wake.clear()
            self._worker_state = "starting"
            self._consecutive_failures = 0
            self._next_retry_at = None
            self._thread = threading.Thread(
                target=self._run,
                name="xhs-scout-monitor-scheduler",
                daemon=True,
            )
            self._thread.start()
            return True

    def wake(self) -> None:
        self._wake.set()

    def stop(self, *, timeout: float = 5.0) -> None:
        with self._guard:
            self._stop.set()
            self._wake.set()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def snapshot(self) -> dict:
        with self._guard:
            thread = self._thread
            return {
                "thread_alive": bool(thread and thread.is_alive()),
                "worker_state": self._worker_state,
                "last_exception": self._last_exception,
                "consecutive_failures": self._consecutive_failures,
                "recovery_count": self._recovery_count,
                "next_retry_at": self._next_retry_at,
                "max_consecutive_failures": self.max_consecutive_failures,
                "recovery_backoff_seconds": {
                    "initial": self.recovery_initial_seconds,
                    "maximum": self.recovery_max_seconds,
                },
                "interval_seconds": self.interval_seconds,
                "idle_interval_seconds": self.idle_interval_seconds,
                "limits": {
                    "max_keywords": self.limits.max_keywords,
                    "max_products_per_keyword": self.limits.max_products_per_keyword,
                    "metrics_max_frames": self.limits.metrics_max_frames,
                    "note_evidence": self.limits.note_evidence,
                    "restart_app_before_round": self.limits.restart_app_before_round,
                },
            }

    def _set_runtime_state(
        self,
        worker_state: str,
        *,
        consecutive_failures: int | None = None,
        recovery_count: int | None = None,
        next_retry_at: str | None = None,
        last_exception: dict[str, Any] | None = None,
        replace_last_exception: bool = False,
    ) -> None:
        with self._guard:
            self._worker_state = worker_state
            if consecutive_failures is not None:
                self._consecutive_failures = consecutive_failures
            if recovery_count is not None:
                self._recovery_count = recovery_count
            self._next_retry_at = next_retry_at
            if replace_last_exception:
                self._last_exception = last_exception

    def _recovery_backoff(self, consecutive_failures: int) -> int:
        multiplier = 2 ** max(0, consecutive_failures - 1)
        return min(
            self.recovery_max_seconds,
            self.recovery_initial_seconds * multiplier,
        )

    def _recover_interrupted_round(self, reason: str) -> dict:
        """Best-effort cleanup limited to the monitor run that just unwound."""

        recovered_tasks: list[dict] = []
        cleanup_errors: list[str] = []
        owner: str | None = None
        try:
            with connect(self.settings.db_path) as conn:
                owner = get_monitor_state(conn).get("last_run_id")
                if owner:
                    rows = conn.execute(
                        """
                        SELECT id FROM search_tasks
                        WHERE status='running' AND run_owner=?
                        ORDER BY id
                        """,
                        (owner,),
                    ).fetchall()
                    for row in rows:
                        try:
                            recovered_tasks.append(
                                mark_task_failed(
                                    conn,
                                    task_id=row["id"],
                                    owner=owner,
                                    reason=reason,
                                    policy=RetryPolicy(),
                                    retryable=True,
                                )
                            )
                        except Exception as exc:
                            cleanup_errors.append(
                                f"task {row['id']}: {type(exc).__name__}: {exc}"
                            )
                    try:
                        release_monitor_lease(conn, owner=owner)
                    except Exception as exc:
                        cleanup_errors.append(
                            f"monitor lease: {type(exc).__name__}: {exc}"
                        )
        except Exception as exc:
            cleanup_errors.append(f"cleanup: {type(exc).__name__}: {exc}")
        return {
            "run_id": owner,
            "recovered_tasks": recovered_tasks,
            "cleanup_errors": cleanup_errors,
        }

    def _prepare_round(self, conn) -> tuple[dict, MonitorLimits | None]:
        portfolio = ensure_portfolio_queue(
            conn,
            self.settings,
            max_keywords=self.limits.max_keywords,
        )
        return portfolio, self.limits

    def _delay_after_round(
        self,
        round_limits: MonitorLimits | None,
        output: dict[str, Any],
    ) -> int:
        if (
            round_limits is not None
            and not output.get("busy")
            and int(output.get("captured_products") or 0) > 0
        ):
            return self.interval_seconds
        return self.idle_interval_seconds

    def _before_round(self) -> dict | None:
        return None

    def _after_round(
        self,
        conn,
        portfolio: dict,
        round_limits: MonitorLimits | None,
        output: dict[str, Any],
    ) -> None:
        """Persist scheduler-specific success state; base scheduler is a no-op."""

    def _persist_exception_state(
        self,
        *,
        exception_state: dict[str, Any],
        worker_state: str,
        next_retry_at: str | None,
        pause: bool,
    ) -> bool:
        try:
            with connect(self.settings.db_path) as conn:
                set_monitor_state(conn, "last_scheduler_exception", exception_state)
                set_monitor_state(
                    conn,
                    "scheduler_consecutive_failures",
                    exception_state["consecutive_failures"],
                )
                set_monitor_state(
                    conn,
                    "scheduler_recovery_count",
                    self._recovery_count,
                )
                set_monitor_state(conn, "scheduler_recovery_state", worker_state)
                set_monitor_state(conn, "next_run_at", next_retry_at)
                if pause:
                    set_monitor_state(conn, "scheduler_running", False)
                    set_monitor_desired_state(conn, "paused")
                    set_monitor_state(
                        conn,
                        "last_block_reason",
                        "scheduler paused after repeated unexpected failures",
                    )
            return True
        except Exception:
            return False

    def _handle_round_exception(
        self,
        exc: Exception,
        *,
        cleanup_monitor: bool = False,
    ) -> bool:
        consecutive_failures = self._consecutive_failures + 1
        reason = f"scheduler caught {type(exc).__name__}: {exc}"
        cleanup = (
            self._recover_interrupted_round(reason)
            if cleanup_monitor
            else {"run_id": None, "recovered_tasks": [], "cleanup_errors": []}
        )
        exception_state: dict[str, Any] = {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
            "at": utcnow(),
            "consecutive_failures": consecutive_failures,
            "run_id": cleanup["run_id"],
            "recovered_tasks": cleanup["recovered_tasks"],
            "cleanup_errors": cleanup["cleanup_errors"],
        }

        exhausted = consecutive_failures >= self.max_consecutive_failures
        if exhausted:
            worker_state = "paused_after_error_budget"
            next_retry_at = None
        else:
            worker_state = "backing_off"
            next_retry_at = (
                datetime.now().astimezone()
                + timedelta(seconds=self._recovery_backoff(consecutive_failures))
            ).isoformat(timespec="seconds")
        self._set_runtime_state(
            worker_state,
            consecutive_failures=consecutive_failures,
            next_retry_at=next_retry_at,
            last_exception=exception_state,
            replace_last_exception=True,
        )
        persisted = self._persist_exception_state(
            exception_state=exception_state,
            worker_state=worker_state,
            next_retry_at=next_retry_at,
            pause=exhausted,
        )
        if exhausted:
            if not persisted:
                self._set_runtime_state("error_budget_exhausted_unpersisted")
            return False

        if self._wake.wait(self._recovery_backoff(consecutive_failures)):
            self._wake.clear()
        if self._stop.is_set():
            return False
        try:
            with connect(self.settings.db_path) as conn:
                state = get_monitor_state(conn)
                if state.get("risk_stop_reason"):
                    set_monitor_desired_state(conn, "paused")
                    set_monitor_state(conn, "next_run_at", None)
                    self._set_runtime_state("risk_paused")
                    return False
                if state.get("desired_state") != "running":
                    return False
        except Exception as state_exc:
            self._set_runtime_state(
                "recovery_state_check_failed",
                last_exception={
                    "type": type(state_exc).__name__,
                    "message": str(state_exc)[:1000],
                    "at": utcnow(),
                    "consecutive_failures": consecutive_failures,
                    "run_id": None,
                    "recovered_tasks": [],
                    "cleanup_errors": ["failed to verify desired/risk state"],
                },
                replace_last_exception=True,
            )
            return False

        recovery_count = self._recovery_count + 1
        self._set_runtime_state(
            "recovering",
            recovery_count=recovery_count,
            next_retry_at=None,
        )
        try:
            with connect(self.settings.db_path) as conn:
                set_monitor_state(conn, "scheduler_recovery_count", recovery_count)
                set_monitor_state(conn, "scheduler_recovery_state", "recovering")
        except Exception:
            pass
        return True

    def _run(self) -> None:
        self._set_runtime_state("running", next_retry_at=None)
        while not self._stop.is_set():
            try:
                with connect(self.settings.db_path) as conn:
                    state = get_monitor_state(conn)
                    self._recovery_count = int(
                        state.get("scheduler_recovery_count") or self._recovery_count
                    )
                    set_monitor_state(conn, "scheduler_running", True)
                    set_monitor_state(conn, "scheduler_recovery_state", "running")
                    set_monitor_state(conn, "next_run_at", utcnow())
                break
            except Exception as exc:
                if not self._handle_round_exception(exc):
                    self._set_runtime_state(
                        self._worker_state,
                        next_retry_at=None,
                    )
                    return
        try:
            while not self._stop.is_set():
                phase = "state_check"
                try:
                    with connect(self.settings.db_path) as conn:
                        state = get_monitor_state(conn)
                        if state.get("risk_stop_reason"):
                            set_monitor_desired_state(conn, "paused")
                            set_monitor_state(conn, "next_run_at", None)
                            self._set_runtime_state("risk_paused")
                            break
                    if (
                        self._stop.is_set()
                        or state.get("desired_state") != "running"
                    ):
                        break

                    phase = "daily_sales"
                    self._before_round()
                    with connect(self.settings.db_path) as conn:
                        state = get_monitor_state(conn)
                    if (
                        self._stop.is_set()
                        or state.get("risk_stop_reason")
                        or state.get("desired_state") != "running"
                    ):
                        break

                    phase = "portfolio"
                    with connect(self.settings.db_path) as conn:
                        portfolio, round_limits = self._prepare_round(conn)
                    if self._stop.is_set():
                        break
                    phase = "monitor"
                    if round_limits is None:
                        output = {
                            "run_id": None,
                            "captured_products": 0,
                            "blocked": None,
                            "busy": False,
                            "skipped": [
                                portfolio.get("reason") or "no runnable task"
                            ],
                        }
                    else:
                        output = monitor_once(self.settings, limits=round_limits)
                    phase = "post_monitor"
                    self._set_runtime_state(
                        "running",
                        consecutive_failures=0,
                        next_retry_at=None,
                    )
                    with connect(self.settings.db_path) as conn:
                        self._after_round(
                            conn,
                            portfolio,
                            round_limits,
                            output,
                        )
                        scheduler_output = {
                            "run_id": output.get("run_id"),
                            "captured_products": output.get("captured_products", 0),
                            "blocked": output.get("blocked"),
                            "busy": output.get("busy", False),
                            "portfolio_queued": portfolio.get("queued", 0),
                        }
                        if portfolio.get("continuous_discovery") is not None:
                            scheduler_output["continuous_discovery"] = portfolio[
                                "continuous_discovery"
                            ]
                        set_monitor_state(
                            conn,
                            "last_scheduler_output",
                            scheduler_output,
                        )
                        set_monitor_state(conn, "scheduler_consecutive_failures", 0)
                        set_monitor_state(conn, "scheduler_recovery_state", "running")
                        state = get_monitor_state(conn)
                        if (
                            self._stop.is_set()
                            or output.get("blocked")
                            or state.get("desired_state") != "running"
                        ):
                            set_monitor_state(conn, "next_run_at", None)
                            break
                        delay_seconds = self._delay_after_round(
                            round_limits,
                            output,
                        )
                        next_run = (
                            datetime.now().astimezone()
                            + timedelta(seconds=delay_seconds)
                        ).isoformat(timespec="seconds")
                        set_monitor_state(conn, "next_run_at", next_run)
                except Exception as exc:
                    if self._handle_round_exception(
                        exc,
                        cleanup_monitor=phase == "monitor",
                    ):
                        continue
                    break

                if self._wake.wait(delay_seconds):
                    self._wake.clear()
                    if self._stop.is_set():
                        break
                    try:
                        with connect(self.settings.db_path) as conn:
                            if get_monitor_state(conn).get("desired_state") != "running":
                                break
                    except Exception as exc:
                        if self._handle_round_exception(exc):
                            continue
                        break
        finally:
            if self._worker_state not in {
                "paused_after_error_budget",
                "error_budget_exhausted_unpersisted",
                "risk_paused",
                "recovery_state_check_failed",
            }:
                self._set_runtime_state("stopped", next_retry_at=None)
            try:
                with connect(self.settings.db_path) as conn:
                    set_monitor_state(conn, "scheduler_running", False)
                    set_monitor_state(
                        conn,
                        "scheduler_recovery_state",
                        self._worker_state,
                    )
                    if (
                        self._stop.is_set()
                        or get_monitor_state(conn).get("desired_state") != "running"
                    ):
                        set_monitor_state(conn, "next_run_at", None)
            except Exception:
                pass


class ContinuousMonitorScheduler(MonitorScheduler):
    """24-hour discovery scheduler isolated from legacy seed/portfolio queues."""

    def __init__(
        self,
        settings: Settings,
        *,
        discovery_roots: tuple[str, ...] | None = None,
        discovery_cooldown_seconds: int = 3600,
        discovery_card_slots: int = 5,
        now_provider: Callable[[], datetime] | None = None,
        daily_sales_collector_factory: Callable | None = None,
        **kwargs,
    ) -> None:
        super().__init__(settings, **kwargs)
        root_config = settings.root / "config" / "discovery_root_terms.txt"
        if discovery_roots is None and root_config.is_file():
            self.discovery_roots = load_continuous_discovery_roots(settings.root)
        else:
            self.discovery_roots = tuple(discovery_roots or DEFAULT_DISCOVERY_ROOTS)
        self.discovery_cooldown_seconds = max(
            60,
            int(discovery_cooldown_seconds),
        )
        self.discovery_card_slots = max(1, min(10, int(discovery_card_slots)))
        self.now_provider = now_provider or (
            lambda: datetime.now().astimezone()
        )
        self.daily_sales_collector_factory = daily_sales_collector_factory

    def _before_round(self) -> dict:
        return run_due_daily_sales_cycle(
            self.settings,
            now=self.now_provider(),
            collector_factory=self.daily_sales_collector_factory,
        )

    def _prepare_round(self, conn) -> tuple[dict, MonitorLimits | None]:
        plan = plan_continuous_discovery_round(
            conn,
            roots=self.discovery_roots,
            cooldown_seconds=self.discovery_cooldown_seconds,
            card_slots=self.discovery_card_slots,
        )
        payload = {
            "queued": 1 if plan.created else 0,
            "reason": plan.reason,
            "continuous_discovery": plan.as_dict(),
        }
        if not plan.selected or plan.task_id is None or not plan.keyword:
            return payload, None
        return payload, replace(
            self.limits,
            task_id=plan.task_id,
            expected_keyword=plan.keyword,
            search_result_rank=plan.search_result_rank or 1,
            search_card_scan_limit=self.discovery_card_slots,
            requeue_due_keywords=False,
        )

    def _after_round(
        self,
        conn,
        portfolio: dict,
        round_limits: MonitorLimits | None,
        output: dict[str, Any],
    ) -> None:
        plan = portfolio.get("continuous_discovery") or {}
        selected_rank = int(plan.get("search_result_rank") or 0)
        completed_final_rank = (
            round_limits is not None
            and selected_rank == self.discovery_card_slots
            and not output.get("blocked")
            and not output.get("busy")
            and int(output.get("captured_products") or 0) > 0
        )
        if not completed_final_rank:
            return
        allowed_count = int(plan.get("allowed_keyword_count") or 0)
        if allowed_count < 1:
            return
        state = get_monitor_state(conn)
        current = int(state.get("continuous_discovery_cursor") or 0)
        set_monitor_state(
            conn,
            "continuous_discovery_cursor",
            (current + 1) % allowed_count,
        )
        set_monitor_state(
            conn,
            "continuous_discovery_last_completed_batch",
            {
                "keyword": plan.get("keyword"),
                "final_rank": selected_rank,
                "card_slots": self.discovery_card_slots,
                "run_id": output.get("run_id"),
                "captured_products": int(
                    output.get("captured_products") or 0
                ),
            },
        )
