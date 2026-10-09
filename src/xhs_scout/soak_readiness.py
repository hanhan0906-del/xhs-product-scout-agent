from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .product_link import is_supported_product_url
from .scheduler_evidence import (
    SchedulerEvidenceRecord,
    SchedulerEvidenceReport,
    evaluate_scheduler_evidence,
    read_scheduler_evidence,
)
from .soak_ack import AckReadiness, evaluate_ack_readiness
from .soak_baseline import (
    SoakBaselineError,
    SoakBaselineManifest,
    read_baseline_manifest,
    validate_baseline_manifest,
)


GATES = ("G0", "G1", "G2", "G3", "G4", "G5", "G6")
PASS = "passed"
FAILED = "failed"
INSUFFICIENT = "insufficient_evidence"
NOT_REACHED = "not_reached"
ELIGIBLE = "eligible_for_evaluation"

REAL_SOURCES = {"real", "live", "production", "controlled_real"}
SUCCESS_RESULTS = {"success", "succeeded", "completed", "captured", "passed"}
METRIC_FIELDS = (
    "cumulative_sales_min",
    "sales_24h_min",
    "sales_7d_min",
    "sales_30d_min",
    "cart_24h_min",
    "new_30d_min",
    "positive_reviews_30d_min",
    "favorites_30d_min",
    "interested_7d_min",
    "interested_30d_min",
    "viewers_now",
    "sales_surging",
)
ACTIVE_TASK_STATUSES = {"running"}
SEARCH_RECOVERY_EVENTS = {"back_to_search_results"}
SQLITE_LOCK_MARKERS = ("database is locked", "database is busy", "sqlite_busy", "sqlite_locked")


@dataclass(frozen=True)
class GateDecision:
    gate: str
    status: str
    reasons: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == PASS

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SoakReadinessReport:
    target: str
    evidence_kind: str
    generated_at: str
    summary: Mapping[str, Any]
    gates: Mapping[str, GateDecision]
    record: Mapping[str, Any]
    warnings: tuple[str, ...] = ()

    @property
    def ready_for_pre_soak(self) -> bool:
        return all(self.gates[name].passed for name in ("G0", "G1", "G2", "G3"))

    @property
    def ready_for_24h_soak(self) -> bool:
        return all(self.gates[name].passed for name in ("G0", "G1", "G2", "G3", "G4"))

    @property
    def pre_soak_start_authorized(self) -> bool:
        return False

    @property
    def soak_24h_start_authorized(self) -> bool:
        return False

    @property
    def scheduler_start_authorized(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "evidence_kind": self.evidence_kind,
            "generated_at": self.generated_at,
            "summary": dict(self.summary),
            "gates": {name: decision.as_dict() for name, decision in self.gates.items()},
            "record": dict(self.record),
            "warnings": list(self.warnings),
            "ready_for_pre_soak": self.ready_for_pre_soak,
            "ready_for_24h_soak": self.ready_for_24h_soak,
            "pre_soak_start_authorized": self.pre_soak_start_authorized,
            "soak_24h_start_authorized": self.soak_24h_start_authorized,
            "scheduler_start_authorized": self.scheduler_start_authorized,
        }


def evaluate_soak_readiness(
    evidence: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    target: str = "pre_soak",
    generated_at: datetime | str | None = None,
    ack_ledger_path: str | Path | None = None,
    ack_allowed_roots: Sequence[str | Path] | None = None,
    ack_readiness: AckReadiness | Mapping[str, Any] | None = None,
    scheduler_evidence_ledger_path: str | Path | None = None,
    scheduler_evidence_allowed_roots: Sequence[str | Path] | None = None,
    scheduler_evidence_readiness: SchedulerEvidenceReport | Mapping[str, Any] | None = None,
    expected_scheduler_scheduled_at: Mapping[
        str, Sequence[datetime | str]
    ] | None = None,
    baseline_manifest: SoakBaselineManifest | Mapping[str, Any] | None = None,
    baseline_manifest_path: str | Path | None = None,
    baseline_allowed_roots: Sequence[str | Path] | None = None,
) -> SoakReadinessReport:
    """Aggregate caller-supplied evidence without reading or mutating live state.

    ``evidence`` may be a bundle with a ``rounds`` list or a plain iterable of
    round mappings. Missing gate evidence is deliberately not inferred.
    """

    if target not in {"pre_soak", "24h_soak", "expansion"}:
        raise ValueError("target must be pre_soak, 24h_soak, or expansion")
    bundle = _bundle(evidence)
    rounds = [_normalise_round(item, bundle) for item in bundle.get("rounds", ())]
    evidence_kind = _evidence_kind(bundle, rounds)
    generated = _parse_datetime(generated_at) or datetime.now().astimezone()

    real_rounds = [row for row in rounds if row["is_real"]]
    started_real = [row for row in real_rounds if row["started_at"] is not None]
    successful_real = [row for row in real_rounds if row["qualified_success"]]
    recorded_outcomes = [row for row in real_rounds if row["has_outcome"]]
    due_rounds = [row for row in real_rounds if row["scheduled_at"] is not None]
    span_hours = _span_hours(real_rounds)
    monitor_state = dict(bundle.get("monitor_state") or {})
    scheduler_snapshot = dict(
        bundle.get("scheduler_snapshot") or bundle.get("scheduler") or {}
    )
    risk_count = sum(bool(row["risk_stop_reason"]) for row in rounds)
    block_count = sum(bool(row["blocked"]) for row in rounds)
    skip_count = sum(bool(row["skip_reason"]) for row in rounds)
    search_recovery_count = sum(bool(row["search_recovered"]) for row in successful_real)
    real_link_count = sum(bool(row["real_link"]) for row in successful_real)
    metrics_result_count = sum(bool(row["metrics_ok"]) for row in successful_real)
    sqlite_lock_count = _sqlite_lock_count(bundle, rounds)
    active_leases = _active_leases(bundle)
    running_tasks = _running_tasks(bundle)
    scheduler_recovery = _scheduler_recovery(bundle)
    alert_state = _alert_state(
        bundle,
        ack_ledger_path=ack_ledger_path,
        ack_allowed_roots=ack_allowed_roots,
        ack_readiness=ack_readiness,
    )
    scheduler_evidence_state = _scheduler_evidence_state(
        bundle,
        ledger_path=scheduler_evidence_ledger_path,
        allowed_roots=scheduler_evidence_allowed_roots,
        readiness=scheduler_evidence_readiness,
        expected_scheduled_at=expected_scheduler_scheduled_at,
    )
    baseline_state = _baseline_readiness_state(
        manifest=baseline_manifest,
        manifest_path=baseline_manifest_path,
        allowed_roots=baseline_allowed_roots,
    )
    snapshot_coverage = _snapshot_coverage(bundle)
    snapshot_phases = snapshot_coverage["combined"]
    missed_due_points = sum(not row["has_outcome"] for row in due_rounds)
    max_start_delay = _max_start_delay(real_rounds)

    summary = {
        "round_count": len(rounds),
        "real_round_count": len(real_rounds),
        "real_started_round_count": len(started_real),
        "successful_round_count": len(successful_real),
        "recorded_outcome_count": len(recorded_outcomes),
        "due_point_count": len(due_rounds),
        "missed_due_point_count": missed_due_points,
        "wall_clock_span_hours": span_hours,
        "risk_count": risk_count,
        "block_count": block_count,
        "skip_count": skip_count,
        "search_recovery_count": search_recovery_count,
        "real_link_count": real_link_count,
        "metrics_result_count": metrics_result_count,
        "active_lease_count": len(active_leases),
        "running_task_count": len(running_tasks),
        "scheduler_exception_count": scheduler_recovery["exception_count"],
        "scheduler_recovery_count": scheduler_recovery["recovery_count"],
        "unrecovered_scheduler_exception_count": scheduler_recovery["unrecovered_count"],
        "sqlite_lock_error_count": sqlite_lock_count,
        "digest_unacked_critical_error_count": alert_state["digest_unacked"],
        "quality_error_count": alert_state["quality_errors"],
        "quality_unacked_error_count": alert_state["quality_unacked"],
        "ack_required_alert_count": len(alert_state["required_alert_ids"]),
        "ack_required_alert_ids": list(alert_state["required_alert_ids"]),
        "acknowledged_alert_ids": list(alert_state["acknowledged_alert_ids"]),
        "ack_missing_alert_ids": list(alert_state["missing_alert_ids"]),
        "ack_unresolved_alert_ids": list(alert_state["unresolved_alert_ids"]),
        "ack_latest_decisions": dict(alert_state["latest_decisions"]),
        "ack_integrity_error": alert_state["integrity_error"],
        "ack_evidence_mismatches": list(alert_state["evidence_mismatches"]),
        "ack_ready": alert_state["ready"],
        "ack_source": alert_state["source"],
        "snapshot_phases": sorted(snapshot_phases),
        "digest_snapshot_phases": sorted(snapshot_coverage["digest"]),
        "quality_snapshot_phases": sorted(snapshot_coverage["quality"]),
        "max_start_delay_seconds": max_start_delay,
        "active_risk_stop_reason": monitor_state.get("risk_stop_reason"),
        "last_block_reason": monitor_state.get("last_block_reason"),
        "last_skip_reason": monitor_state.get("last_skip_reason"),
        "scheduler_thread_alive": bool(scheduler_snapshot.get("thread_alive")),
        "scheduler_evidence_source": scheduler_evidence_state["source"],
        "scheduler_evidence_integrity_ok": scheduler_evidence_state[
            "ledger_integrity_ok"
        ],
        "scheduler_evidence_integrity_error": scheduler_evidence_state[
            "integrity_error"
        ],
        "scheduler_evidence_stages": scheduler_evidence_state["summary_stages"],
        "baseline": baseline_state,
        "baseline_status": baseline_state["status"],
        "baseline_source": baseline_state["source"],
        "baseline_integrity_ok": baseline_state["integrity_ok"],
        "baseline_id": baseline_state["baseline_id"],
        "baseline_manifest_hash": baseline_state["manifest_hash"],
        "pre_soak_start_authorized": False,
        "soak_24h_start_authorized": False,
        "scheduler_start_authorized": False,
    }

    gates: dict[str, GateDecision] = {}
    gates["G0"] = _gate_g0(bundle, sqlite_lock_count, baseline_state)
    gates["G1"] = _gate_g1(real_rounds, successful_real, risk_count)
    gates["G2"] = _gate_g2(
        real_rounds,
        recorded_outcomes,
        due_rounds,
        successful_real,
        span_hours,
        missed_due_points,
        max_start_delay,
        scheduler_evidence_state,
    )
    gates["G3"] = _gate_g3(
        bundle,
        active_leases,
        running_tasks,
        scheduler_recovery,
        alert_state,
        monitor_state,
        scheduler_snapshot,
    )
    gates["G4"] = _gate_g4(
        evidence_kind,
        real_rounds,
        span_hours,
        missed_due_points,
        sqlite_lock_count,
        snapshot_coverage,
        alert_state,
        active_leases,
        running_tasks,
        scheduler_evidence_state,
    )
    gates["G5"] = _gate_g5(
        gates,
        evidence_kind,
        real_rounds,
        started_real,
        span_hours,
        missed_due_points,
        max_start_delay,
        snapshot_coverage,
        alert_state,
    )
    gates["G6"] = _gate_g6(gates, bundle)

    warnings: list[str] = []
    if evidence_kind != "real":
        warnings.append(
            "模拟、dry-run 或合成测试只能作为离线结构证据，不能等同于真实 pre-soak 或 24 小时 soak。"
        )
    if not rounds:
        warnings.append("没有轮次证据；准入判定按 fail closed 返回证据不足。")
    if not alert_state["ready"]:
        warnings.append("critical/error 告警的人工 ACK 证据未通过完整性与身份一致性校验。")
    warnings.extend(baseline_state["warnings"])
    record = _structured_record(
        bundle,
        rounds,
        summary,
        gates,
        generated,
        evidence_kind,
        scheduler_evidence_state,
        baseline_state,
    )
    return SoakReadinessReport(
        target=target,
        evidence_kind=evidence_kind,
        generated_at=generated.isoformat(timespec="seconds"),
        summary=summary,
        gates=gates,
        record=record,
        warnings=tuple(warnings),
    )


def load_sqlite_evidence(
    source: str | Path | sqlite3.Connection,
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read an existing SQLite fixture/database without schema creation or writes."""

    owns_connection = not isinstance(source, sqlite3.Connection)
    if owns_connection:
        path = Path(source).resolve()
        uri = f"{path.as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = source
    previous_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        tables = _table_names(conn)
        state = _read_monitor_state(conn) if "monitor_state" in tables else {}
        events = _rows(conn, "SELECT * FROM run_events ORDER BY id") if "run_events" in tables else []
        tasks = _rows(conn, "SELECT * FROM search_tasks ORDER BY id") if "search_tasks" in tables else []
        leases = _rows(conn, "SELECT * FROM run_leases ORDER BY name") if "run_leases" in tables else []
        products = {
            row["id"]: row
            for row in (_rows(conn, "SELECT * FROM products ORDER BY id") if "products" in tables else [])
        }
        observations = {
            row["id"]: row
            for row in (
                _rows(conn, "SELECT * FROM observations ORDER BY id")
                if "observations" in tables
                else []
            )
        }
        search_rows = (
            _rows(conn, "SELECT * FROM search_result_evidence ORDER BY id")
            if "search_result_evidence" in tables
            else []
        )
        rounds = _rounds_from_events(events, tasks, products, observations, search_rows)
    finally:
        conn.row_factory = previous_factory
        if owns_connection:
            conn.close()

    bundle = dict(context or {})
    bundle.update(
        {
            "rounds": rounds,
            "monitor_state": {**state, **dict(bundle.get("monitor_state") or {})},
            "tasks": tasks,
            "leases": leases,
            "sqlite_source": "read_only",
        }
    )
    return bundle


def evaluate_sqlite_readiness(
    source: str | Path | sqlite3.Connection,
    *,
    context: Mapping[str, Any] | None = None,
    target: str = "pre_soak",
    generated_at: datetime | str | None = None,
    ack_ledger_path: str | Path | None = None,
    ack_allowed_roots: Sequence[str | Path] | None = None,
    ack_readiness: AckReadiness | Mapping[str, Any] | None = None,
    scheduler_evidence_ledger_path: str | Path | None = None,
    scheduler_evidence_allowed_roots: Sequence[str | Path] | None = None,
    scheduler_evidence_readiness: SchedulerEvidenceReport | Mapping[str, Any] | None = None,
    expected_scheduler_scheduled_at: Mapping[
        str, Sequence[datetime | str]
    ] | None = None,
    baseline_manifest: SoakBaselineManifest | Mapping[str, Any] | None = None,
    baseline_manifest_path: str | Path | None = None,
    baseline_allowed_roots: Sequence[str | Path] | None = None,
) -> SoakReadinessReport:
    return evaluate_soak_readiness(
        load_sqlite_evidence(source, context=context),
        target=target,
        generated_at=generated_at,
        ack_ledger_path=ack_ledger_path,
        ack_allowed_roots=ack_allowed_roots,
        ack_readiness=ack_readiness,
        scheduler_evidence_ledger_path=scheduler_evidence_ledger_path,
        scheduler_evidence_allowed_roots=scheduler_evidence_allowed_roots,
        scheduler_evidence_readiness=scheduler_evidence_readiness,
        expected_scheduler_scheduled_at=expected_scheduler_scheduled_at,
        baseline_manifest=baseline_manifest,
        baseline_manifest_path=baseline_manifest_path,
        baseline_allowed_roots=baseline_allowed_roots,
    )


def _bundle(
    evidence: Mapping[str, Any] | Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    if isinstance(evidence, Mapping):
        bundle = dict(evidence)
        rounds = bundle.get("rounds", bundle.get("records", ()))
        bundle["rounds"] = list(rounds or ())
        return bundle
    return {"rounds": list(evidence)}


def _normalise_round(row: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(row)
    source = str(
        item.get("evidence_kind")
        or item.get("source_kind")
        or bundle.get("evidence_kind")
        or bundle.get("source_kind")
        or "unknown"
    ).strip().casefold()
    dry_run = _truthy(item.get("dry_run"))
    simulated = _truthy(item.get("simulated")) or source in {"simulation", "simulated", "synthetic", "test"}
    result = str(item.get("result") or item.get("status") or "").strip().casefold()
    successful = item.get("success")
    if successful is None:
        successful = result in SUCCESS_RESULTS
    blocked = item.get("blocked") or item.get("last_block_reason")
    risk = item.get("risk_stop_reason") or item.get("risk")
    skip = item.get("skip_reason") or item.get("last_skip_reason")
    metrics = item.get("metrics") or item.get("metrics_result") or {}
    metrics_ok = item.get("metrics_ok")
    if metrics_ok is None:
        metrics_ok = _has_metrics(metrics) or any(item.get(name) not in (None, "", False) for name in METRIC_FIELDS)
    search_recovered = item.get("search_recovered")
    if search_recovered is None:
        search_recovered = item.get("returned_to_search_results")
    share_url = item.get("share_url") or item.get("product_url")
    evidence_path = (
        item.get("probe_or_evidence_path")
        or item.get("evidence_path")
        or item.get("screenshot_path")
        or item.get("report_path")
    )
    is_real = source in REAL_SOURCES and not dry_run and not simulated
    required_ids = all(item.get(key) not in (None, "") for key in ("run_id", "task_id", "product_id", "observation_id"))
    qualified_success = all(
        (
            is_real,
            _truthy(successful),
            not blocked,
            not risk,
            required_ids,
            bool(evidence_path),
            _truthy(search_recovered),
            is_supported_product_url(str(share_url or "")),
            _truthy(metrics_ok),
        )
    )
    return {
        **item,
        "source_kind": source,
        "is_real": is_real,
        "scheduled_at": _parse_datetime(item.get("scheduled_at")),
        "started_at": _parse_datetime(item.get("started_at") or item.get("start_at")),
        "finished_at": _parse_datetime(item.get("finished_at") or item.get("end_at")),
        "success": _truthy(successful),
        "qualified_success": qualified_success,
        "blocked": blocked,
        "risk_stop_reason": risk,
        "skip_reason": skip,
        "search_recovered": _truthy(search_recovered),
        "share_url": share_url,
        "real_link": is_supported_product_url(str(share_url or "")),
        "metrics_ok": _truthy(metrics_ok),
        "evidence_path": evidence_path,
        "has_outcome": bool(
            _truthy(successful) or blocked or risk or skip or result in {"busy", "skipped", "failed", "error"}
        ),
    }


def _evidence_kind(bundle: Mapping[str, Any], rounds: Sequence[Mapping[str, Any]]) -> str:
    explicit = str(bundle.get("evidence_kind") or bundle.get("source_kind") or "").casefold()
    if explicit in REAL_SOURCES and rounds and all(row["is_real"] for row in rounds):
        return "real"
    if explicit in {"simulation", "simulated", "synthetic", "test"}:
        return "simulation"
    if rounds and all(row["is_real"] for row in rounds):
        return "real"
    if any(row["is_real"] for row in rounds):
        return "mixed"
    return explicit or "unknown"


def _scheduler_evidence_state(
    bundle: Mapping[str, Any],
    *,
    ledger_path: str | Path | None,
    allowed_roots: Sequence[str | Path] | None,
    readiness: SchedulerEvidenceReport | Mapping[str, Any] | None,
    expected_scheduled_at: Mapping[str, Sequence[datetime | str]] | None,
) -> dict[str, Any]:
    resolved_ledger = (
        ledger_path
        if ledger_path is not None
        else bundle.get("scheduler_evidence_ledger_path")
    )
    resolved_roots = (
        allowed_roots
        if allowed_roots is not None
        else bundle.get("scheduler_evidence_allowed_roots")
    )
    resolved_readiness = (
        readiness
        if readiness is not None
        else bundle.get("scheduler_evidence_readiness")
    )
    resolved_expected = (
        expected_scheduled_at
        if expected_scheduled_at is not None
        else bundle.get("expected_scheduler_scheduled_at")
    )

    expected: dict[str, tuple[str, ...]] = {}
    expected_errors: list[str] = []
    try:
        expected = _normalise_expected_scheduler_times(resolved_expected)
    except (TypeError, ValueError) as exc:
        expected_errors.append(str(exc))

    source = "not_provided"
    integrity_ok: bool | None = None
    integrity_error: str | None = None
    report_values: Mapping[str, Any] = {}
    records: tuple[SchedulerEvidenceRecord, ...] = ()
    source_errors: list[str] = []

    if resolved_ledger is not None and resolved_readiness is not None:
        source = "ambiguous"
        source_errors.append("同时提供 scheduler evidence 账本和评估结果，来源不唯一")
    elif resolved_ledger is not None:
        source = "ledger"
        if not resolved_roots:
            integrity_ok = False
            integrity_error = "scheduler evidence 账本缺少 allowed_roots"
        elif not expected:
            integrity_ok = False
            integrity_error = "缺少调用方显式 expected scheduled_at 清单"
        else:
            try:
                records = read_scheduler_evidence(
                    resolved_ledger,
                    allowed_roots=resolved_roots,
                )
                evaluated = evaluate_scheduler_evidence(
                    resolved_ledger,
                    allowed_roots=resolved_roots,
                    expected_due_points={
                        stage: len(times) for stage, times in expected.items()
                    },
                )
                report_values = evaluated.as_dict()
                integrity_ok = evaluated.ledger_integrity_ok
                integrity_error = evaluated.integrity_error
            except (OSError, TypeError, ValueError) as exc:
                integrity_ok = False
                integrity_error = str(exc)
    elif resolved_readiness is not None:
        source = "evaluation"
        report_values = (
            resolved_readiness.as_dict()
            if isinstance(resolved_readiness, SchedulerEvidenceReport)
            else dict(resolved_readiness)
        )
        integrity_ok = report_values.get("ledger_integrity_ok") is True
        integrity_error = (
            str(report_values.get("integrity_error"))
            if report_values.get("integrity_error")
            else None
        )

    report_stages = (
        report_values.get("stages")
        if isinstance(report_values.get("stages"), Mapping)
        else {}
    )
    supplied_times = (
        report_values.get("scheduled_at_by_stage")
        if isinstance(report_values.get("scheduled_at_by_stage"), Mapping)
        else {}
    )
    stages: dict[str, dict[str, Any]] = {}
    for stage in ("G2", "G4"):
        expected_times = expected.get(stage, ())
        stage_report = (
            dict(report_stages.get(stage) or {})
            if isinstance(report_stages.get(stage), Mapping)
            else {}
        )
        if source == "ledger":
            recorded_times = tuple(
                record.scheduled_at for record in records if record.stage == stage
            )
        else:
            raw_times = supplied_times.get(stage)
            if raw_times is None:
                raw_times = stage_report.get("recorded_scheduled_at")
            try:
                recorded_times = _normalise_scheduler_time_list(
                    raw_times,
                    f"{stage} recorded scheduled_at",
                    allow_empty=True,
                )
            except (TypeError, ValueError) as exc:
                recorded_times = ()
                source_errors.append(str(exc))

        missing: list[str] = []
        failed: list[str] = []
        if expected_errors:
            failed.extend(expected_errors)
        if not expected_times:
            missing.append(f"缺少 {stage} 调用方显式 expected scheduled_at 清单")
        if source in {"not_provided", "ambiguous"}:
            missing.append(f"缺少 {stage} scheduler evidence 账本或评估结果")
        if source_errors:
            failed.extend(source_errors)
        if integrity_ok is False:
            failed.append(
                f"{stage} scheduler evidence 完整性失败"
                + (f"：{integrity_error}" if integrity_error else "")
            )
        if source in {"ledger", "evaluation"} and not stage_report:
            missing.append(f"scheduler evidence 评估缺少 {stage} 阶段")

        recorded_counts = Counter(recorded_times)
        duplicate_times = tuple(
            sorted(value for value, count in recorded_counts.items() if count > 1)
        )
        missing_times = tuple(sorted(set(expected_times) - set(recorded_times)))
        unexpected_times = tuple(sorted(set(recorded_times) - set(expected_times)))
        if source == "evaluation" and not recorded_times:
            missing.append(
                f"{stage} 预评估结果没有逐点 scheduled_at 绑定；需提供账本或带绑定的评估 mapping"
            )
        elif source == "ledger" and not records:
            missing.append("scheduler evidence 账本缺失或为空")
        if duplicate_times:
            failed.append(f"{stage} scheduler evidence 存在重复 scheduled_at")
        if missing_times and not (source == "evaluation" and not recorded_times):
            failed.append(f"{stage} scheduler evidence 缺少预期到期点")
        if unexpected_times:
            failed.append(f"{stage} scheduler evidence 出现未预期到期点")
        if stage_report and stage_report.get("ready_for_gate_evaluation") is not True:
            reasons = stage_report.get("reasons") or ()
            detail = "；".join(str(reason) for reason in reasons)
            failed.append(
                f"{stage} scheduler evidence 未通过 T46 健康评估"
                + (f"：{detail}" if detail else "")
            )

        span_hours = _datetime_span_hours(expected_times)
        if stage == "G2" and expected_times and len(expected_times) < 3:
            missing.append("G2 显式预期到期点不足 3 个")
        if stage == "G4" and expected_times and span_hours < 6:
            missing.append("G4 显式预期到期点墙钟跨度不足 6 小时")
        stages[stage] = {
            "ready": not missing and not failed,
            "expected_scheduled_at": list(expected_times),
            "recorded_scheduled_at": list(recorded_times),
            "missing_scheduled_at": list(missing_times),
            "unexpected_scheduled_at": list(unexpected_times),
            "duplicate_scheduled_at": list(duplicate_times),
            "expected_span_hours": span_hours,
            "t46_ready_for_gate_evaluation": (
                stage_report.get("ready_for_gate_evaluation") is True
            ),
            "missing_reasons": list(dict.fromkeys(missing)),
            "failed_reasons": list(dict.fromkeys(failed)),
        }

    return {
        "source": source,
        "ledger_integrity_ok": integrity_ok,
        "integrity_error": integrity_error,
        "stages": stages,
        "summary_stages": {
            stage: {
                key: value
                for key, value in values.items()
                if key != "ready"
            }
            | {"ready": values["ready"]}
            for stage, values in stages.items()
        },
    }


def _normalise_expected_scheduler_times(
    value: Any,
) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(
            "expected_scheduler_scheduled_at 必须是 G2/G4 到 scheduled_at 列表的 mapping"
        )
    result: dict[str, tuple[str, ...]] = {}
    for raw_stage, raw_times in value.items():
        stage = str(raw_stage).strip().upper()
        if stage not in {"G2", "G4"}:
            raise ValueError("expected_scheduler_scheduled_at 只允许 G2/G4")
        times = _normalise_scheduler_time_list(
            raw_times,
            f"{stage} expected scheduled_at",
        )
        if len(set(times)) != len(times):
            raise ValueError(f"{stage} expected scheduled_at 清单包含重复时间")
        result[stage] = times
    return result


def _normalise_scheduler_time_list(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        if allow_empty and value is None:
            return ()
        raise TypeError(f"{label} 必须是列表")
    times: list[str] = []
    for raw in value:
        parsed = _scheduler_datetime(raw, label)
        times.append(parsed.isoformat(timespec="seconds"))
    if not times and not allow_empty:
        raise ValueError(f"{label} 不能为空")
    return tuple(sorted(times))


def _scheduler_datetime(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label} 必须是 ISO-8601 时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} 必须包含时区")
    return parsed


def _datetime_span_hours(values: Sequence[str]) -> float:
    if len(values) < 2:
        return 0.0
    points = [_scheduler_datetime(value, "scheduled_at") for value in values]
    return round((max(points) - min(points)).total_seconds() / 3600, 3)


def _scheduler_gate_reasons(
    state: Mapping[str, Any],
    stage: str,
) -> tuple[list[str], list[str]]:
    values = state["stages"][stage]
    return (
        list(values["missing_reasons"]),
        list(values["failed_reasons"]),
    )


def _baseline_readiness_state(
    *,
    manifest: SoakBaselineManifest | Mapping[str, Any] | None,
    manifest_path: str | Path | None,
    allowed_roots: Sequence[str | Path] | None,
) -> dict[str, Any]:
    source = "not_provided"
    status = INSUFFICIENT
    integrity_ok: bool | None = None
    baseline_id: str | None = None
    manifest_hash: str | None = None
    gaps: list[str] = []
    warnings: list[str] = []

    if manifest is not None and manifest_path is not None:
        source = "ambiguous"
        status = FAILED
        integrity_ok = False
        gaps.append("baseline 清单对象与路径不能同时提供")
    elif manifest_path is not None:
        source = "path"
        if not allowed_roots:
            status = FAILED
            integrity_ok = False
            gaps.append("baseline 路径缺少显式 baseline_allowed_roots")
        else:
            try:
                validated = read_baseline_manifest(
                    manifest_path,
                    allowed_roots=allowed_roots,
                    verify_files=True,
                )
                authorization_paths = _true_authorization_paths(
                    validated.as_dict()
                )
                if authorization_paths:
                    raise SoakBaselineError(
                        "baseline 包含 authorization=true："
                        + "、".join(authorization_paths)
                    )
            except (OSError, TypeError, ValueError) as exc:
                status = FAILED
                integrity_ok = False
                gaps.append(f"baseline 路径校验失败：{exc}")
            else:
                status = PASS
                integrity_ok = True
                baseline_id = validated.baseline_id
                manifest_hash = validated.manifest_hash
    elif manifest is not None:
        source = "manifest"
        try:
            validated = validate_baseline_manifest(manifest, verify_files=True)
            authorization_paths = _true_authorization_paths(validated.as_dict())
            if authorization_paths:
                raise SoakBaselineError(
                    "baseline 包含 authorization=true："
                    + "、".join(authorization_paths)
                )
        except (OSError, TypeError, ValueError) as exc:
            status = FAILED
            integrity_ok = False
            gaps.append(f"baseline 清单校验失败：{exc}")
        else:
            status = PASS
            integrity_ok = True
            baseline_id = validated.baseline_id
            manifest_hash = validated.manifest_hash
    else:
        gaps.append("缺少调用方显式提供的 baseline 清单或路径")

    if status != PASS:
        warnings.append("pre-soak baseline 未通过离线准入；readiness 按 fail closed 处理。")
    return {
        "stage": "baseline",
        "status": status,
        "source": source,
        "integrity_ok": integrity_ok,
        "baseline_id": baseline_id,
        "manifest_hash": manifest_hash,
        "files_reverified": status == PASS,
        "gaps": list(dict.fromkeys(gaps)),
        "warnings": list(dict.fromkeys(warnings)),
        "pre_soak_start_authorized": False,
        "soak_24h_start_authorized": False,
        "scheduler_start_authorized": False,
    }


def _true_authorization_paths(value: Any, *, path: str = "manifest") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.strip().casefold().replace("-", "_")
            item_path = f"{path}.{key_text}"
            if (
                ("authoriz" in normalized or "authoris" in normalized)
                and _truthy(item)
            ):
                found.append(item_path)
            found.extend(_true_authorization_paths(item, path=item_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(
                _true_authorization_paths(item, path=f"{path}[{index}]")
            )
    return tuple(dict.fromkeys(found))


def _gate_g0(
    bundle: Mapping[str, Any],
    sqlite_lock_count: int,
    baseline: Mapping[str, Any],
) -> GateDecision:
    missing: list[str] = []
    failed: list[str] = []
    for key, label in (
        ("offline_tests_passed", "离线测试全绿"),
        ("sqlite_stress_passed", "SQLite 并发压力通过"),
        ("scheduler_recovery_tested", "scheduler 异常恢复离线验证"),
        ("lease_safety_tested", "长步骤租约/lease-lost 安全验证"),
    ):
        value = _explicit_bool(bundle, key)
        if value is None:
            missing.append(f"缺少{label}证据")
        elif value is False:
            failed.append(f"{label}未通过")
    if sqlite_lock_count:
        failed.append(f"发现 {sqlite_lock_count} 个 SQLite lock/busy 错误")
    if baseline["status"] == INSUFFICIENT:
        missing.extend(baseline["gaps"])
    elif baseline["status"] != PASS:
        failed.extend(baseline["gaps"])
    return _decision(
        "G0",
        missing,
        failed,
        {
            "sqlite_lock_error_count": sqlite_lock_count,
            "baseline": dict(baseline),
        },
    )


def _gate_g1(
    real_rounds: Sequence[Mapping[str, Any]],
    successful: Sequence[Mapping[str, Any]],
    risk_count: int,
) -> GateDecision:
    missing: list[str] = []
    failed: list[str] = []
    if len(real_rounds) < 3:
        missing.append("真实受控单轮不足 3 次")
    if len(successful) < 3:
        missing.append("满足 ID、搜索恢复、真实链接、指标和证据路径的成功轮次不足 3 次")
    if risk_count:
        failed.append("轮次中出现硬风险停止")
    bad = len(real_rounds) - len(successful)
    if len(real_rounds) >= 3 and bad:
        failed.append(f"{bad} 个真实轮次未满足完整成功证据")
    return _decision(
        "G1",
        missing,
        failed,
        {"real_round_count": len(real_rounds), "successful_round_count": len(successful)},
    )


def _gate_g2(
    real_rounds: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    due_rounds: Sequence[Mapping[str, Any]],
    successful: Sequence[Mapping[str, Any]],
    span_hours: float,
    missed_due_points: int,
    max_start_delay: float | None,
    scheduler_evidence: Mapping[str, Any],
) -> GateDecision:
    missing: list[str] = []
    failed: list[str] = []
    if len(due_rounds) < 3:
        missing.append("带 scheduled_at 的真实小时级到期点不足 3 个")
    if len(successful) < 3:
        missing.append("真实小时级成功轮次不足 3 个")
    if span_hours < 2:
        missing.append("真实轮次墙钟跨度不足以证明 3 个小时级决策点")
    if missed_due_points:
        failed.append(f"有 {missed_due_points} 个到期点缺少结果")
    if max_start_delay is not None and max_start_delay > 900:
        failed.append("至少一个轮次启动延迟超过 15 分钟")
    duplicate_keywords = _cooldown_duplicates(real_rounds)
    if duplicate_keywords:
        failed.append("发现 24 小时冷却内重复关键词：" + "、".join(duplicate_keywords))
    scheduler_missing, scheduler_failed = _scheduler_gate_reasons(
        scheduler_evidence,
        "G2",
    )
    missing.extend(scheduler_missing)
    failed.extend(scheduler_failed)
    return _decision(
        "G2",
        missing,
        failed,
        {
            "due_point_count": len(due_rounds),
            "recorded_outcome_count": len(outcomes),
            "span_hours": span_hours,
            "max_start_delay_seconds": max_start_delay,
            "scheduler_evidence": scheduler_evidence["summary_stages"]["G2"],
        },
    )


def _gate_g3(
    bundle: Mapping[str, Any],
    active_leases: Sequence[Mapping[str, Any]],
    running_tasks: Sequence[Mapping[str, Any]],
    scheduler: Mapping[str, int],
    alerts: Mapping[str, int],
    monitor_state: Mapping[str, Any],
    scheduler_snapshot: Mapping[str, Any],
) -> GateDecision:
    missing: list[str] = []
    failed: list[str] = []
    for key, label in (
        ("lease_recovery_verified", "租约/崩溃恢复演练"),
        ("scheduler_recovery_verified", "scheduler-dead 检测与恢复演练"),
        ("risk_recovery_verified", "风险后人工确认恢复演练"),
    ):
        value = _explicit_bool(bundle, key)
        if value is None:
            missing.append(f"缺少{label}证据")
        elif value is False:
            failed.append(f"{label}未通过")
    if active_leases:
        failed.append(f"结束时仍有 {len(active_leases)} 个租约残留")
    if running_tasks:
        failed.append(f"结束时仍有 {len(running_tasks)} 个 running 任务")
    if scheduler["unrecovered_count"]:
        failed.append(f"有 {scheduler['unrecovered_count']} 个 scheduler 异常未恢复")
    if not alerts["ready"]:
        failed.append(_ack_failure_reason(alerts))
    if monitor_state.get("risk_stop_reason"):
        failed.append("结束状态仍保留 risk_stop_reason")
    if scheduler_snapshot.get("thread_alive") and monitor_state.get("desired_state") != "running":
        failed.append("scheduler 线程存活但 desired_state 不是 running")
    return _decision(
        "G3",
        missing,
        failed,
        {
            "active_lease_count": len(active_leases),
            "running_task_count": len(running_tasks),
            **scheduler,
        },
    )


def _gate_g4(
    evidence_kind: str,
    rounds: Sequence[Mapping[str, Any]],
    span_hours: float,
    missed_due_points: int,
    sqlite_locks: int,
    coverage: Mapping[str, set[str]],
    alerts: Mapping[str, int],
    leases: Sequence[Mapping[str, Any]],
    tasks: Sequence[Mapping[str, Any]],
    scheduler_evidence: Mapping[str, Any],
) -> GateDecision:
    missing: list[str] = []
    failed: list[str] = []
    if evidence_kind != "real":
        missing.append("缺少真实 pre-soak 证据；模拟测试不能替代")
    if span_hours < 6:
        missing.append("真实连续墙钟跨度不足 6 小时")
    required_phases = {"start", "mid", "end"}
    if not required_phases.issubset(coverage["digest"]):
        missing.append("digest 缺少开始/中点/结束快照")
    if not required_phases.issubset(coverage["quality"]):
        missing.append("quality 缺少开始/中点/结束快照")
    if not rounds:
        missing.append("缺少 pre-soak 轮次")
    if missed_due_points:
        failed.append("pre-soak 存在无结果到期点")
    if sqlite_locks:
        failed.append("pre-soak 出现 SQLite lock/busy 错误")
    if not alerts["ready"]:
        failed.append(_ack_failure_reason(alerts, prefix="pre-soak "))
    if leases or tasks:
        failed.append("pre-soak 结束状态未清理")
    if any(row.get("risk_stop_reason") or row.get("blocked") for row in rounds):
        failed.append("pre-soak 中出现 risk/block 安全事件")
    scheduler_missing, scheduler_failed = _scheduler_gate_reasons(
        scheduler_evidence,
        "G4",
    )
    missing.extend(scheduler_missing)
    failed.extend(scheduler_failed)
    return _decision(
        "G4",
        missing,
        failed,
        {
            "span_hours": span_hours,
            "digest_snapshot_phases": sorted(coverage["digest"]),
            "quality_snapshot_phases": sorted(coverage["quality"]),
            "scheduler_evidence": scheduler_evidence["summary_stages"]["G4"],
        },
    )


def _gate_g5(
    gates: Mapping[str, GateDecision],
    evidence_kind: str,
    rounds: Sequence[Mapping[str, Any]],
    started: Sequence[Mapping[str, Any]],
    span_hours: float,
    missed_due_points: int,
    max_delay: float | None,
    coverage: Mapping[str, set[str]],
    alerts: Mapping[str, int],
) -> GateDecision:
    missing: list[str] = []
    failed: list[str] = []
    prior = [name for name in ("G0", "G1", "G2", "G3", "G4") if not gates[name].passed]
    if prior:
        missing.append("前置门槛未全部通过：" + "、".join(prior))
    if evidence_kind != "real":
        missing.append("缺少真实 24 小时 soak；快速模拟周期不计入")
    if span_hours < 24:
        missing.append("连续墙钟跨度不足 24 小时")
    if len(started) < 18:
        missing.append("真实开始轮次不足 18 次")
    if not {"start", "mid", "end"}.issubset(coverage["digest"]) or not {
        "start",
        "mid",
        "end",
    }.issubset(coverage["quality"]):
        missing.append("缺少开始/约 12h/结束快照")
    if missed_due_points:
        failed.append("24 小时窗口内有无结果到期点")
    if max_delay is not None and max_delay > 900:
        failed.append("24 小时窗口内启动延迟超过 15 分钟")
    if any(row.get("risk_stop_reason") for row in rounds):
        failed.append("24 小时窗口内出现硬风险停止")
    if not alerts["ready"]:
        failed.append(_ack_failure_reason(alerts, prefix="24 小时窗口"))
    return _decision(
        "G5",
        missing,
        failed,
        {"span_hours": span_hours, "real_started_round_count": len(started)},
    )


def _gate_g6(gates: Mapping[str, GateDecision], bundle: Mapping[str, Any]) -> GateDecision:
    if not gates["G5"].passed:
        return GateDecision("G6", NOT_REACHED, ("G5 未通过，不进入扩容评估",))
    if _explicit_bool(bundle, "expansion_evaluation_approved") is True:
        return GateDecision(
            "G6",
            ELIGIBLE,
            ("仅允许另行评估 3–5 词预算；不代表已授权扩容",),
        )
    return GateDecision(
        "G6",
        ELIGIBLE,
        ("G5 已通过，但这不代表已授权扩容；仍需另立预算并由用户再次确认",),
    )


def _decision(
    gate: str,
    missing: Sequence[str],
    failed: Sequence[str],
    evidence: Mapping[str, Any] | None = None,
) -> GateDecision:
    if failed:
        return GateDecision(gate, FAILED, tuple(failed) + tuple(missing), evidence or {})
    if missing:
        return GateDecision(gate, INSUFFICIENT, tuple(missing), evidence or {})
    return GateDecision(gate, PASS, (), evidence or {})


def _structured_record(
    bundle: Mapping[str, Any],
    rounds: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    gates: Mapping[str, GateDecision],
    generated: datetime,
    evidence_kind: str,
    scheduler_evidence: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    serialised_rounds = []
    for index, row in enumerate(rounds, start=1):
        serialised_rounds.append(
            {
                "sequence": row.get("sequence") or index,
                "run_id": row.get("run_id"),
                "task_id": row.get("task_id"),
                "keyword": row.get("keyword"),
                "scheduled_at": _iso(row.get("scheduled_at")),
                "started_at": _iso(row.get("started_at")),
                "finished_at": _iso(row.get("finished_at")),
                "result": row.get("result") or row.get("status"),
                "busy": bool(row.get("busy")),
                "blocked": row.get("blocked"),
                "skip_reason": row.get("skip_reason"),
                "risk_stop_reason": row.get("risk_stop_reason"),
                "product_id": row.get("product_id"),
                "observation_id": row.get("observation_id"),
                "search_recovered": bool(row.get("search_recovered")),
                "share_url": row.get("share_url"),
                "metrics_ok": bool(row.get("metrics_ok")),
                "evidence_path": row.get("evidence_path"),
                "source_kind": row.get("source_kind"),
                "qualified_success": bool(row.get("qualified_success")),
            }
        )
    return {
        "schema_version": 1,
        "soak_id": bundle.get("soak_id"),
        "evidence_kind": evidence_kind,
        "window_kind": bundle.get("window_kind"),
        "generated_at": generated.isoformat(timespec="seconds"),
        "simulation_disclaimer": (
            "模拟测试不等于真实 soak；只有真实墙钟与真实轮次证据可通过 G1–G5。"
        ),
        "authorization": {
            "pre_soak_start_authorized": False,
            "soak_24h_start_authorized": False,
            "scheduler_start_authorized": False,
            "statement": "Readiness evidence never authorizes a soak or scheduler start.",
        },
        "baseline": dict(baseline),
        "summary": dict(summary),
        "rounds": serialised_rounds,
        "end_state": dict(bundle.get("monitor_state") or {}),
        "scheduler_snapshot": dict(
            bundle.get("scheduler_snapshot") or bundle.get("scheduler") or {}
        ),
        "snapshot_counts": {
            "digest": len(bundle.get("digest_snapshots") or ()),
            "quality": len(bundle.get("quality_snapshots") or ()),
        },
        "scheduler_evidence": {
            "source": scheduler_evidence["source"],
            "ledger_integrity_ok": scheduler_evidence["ledger_integrity_ok"],
            "integrity_error": scheduler_evidence["integrity_error"],
            "stages": scheduler_evidence["summary_stages"],
        },
        "gates": {name: gate.as_dict() for name, gate in gates.items()},
    }


def _rounds_from_events(
    events: Sequence[Mapping[str, Any]],
    tasks: Sequence[Mapping[str, Any]],
    products: Mapping[Any, Mapping[str, Any]],
    observations: Mapping[Any, Mapping[str, Any]],
    search_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    task_by_id = {row.get("id"): row for row in tasks}
    by_run: dict[str, list[dict[str, Any]]] = {}
    for raw in events:
        row = dict(raw)
        row["data"] = _json_object(row.get("data_json"))
        by_run.setdefault(str(row.get("run_id") or ""), []).append(row)

    rounds: list[dict[str, Any]] = []
    for run_id, group in by_run.items():
        started = next((row for row in group if row.get("event") == "monitor_once_started"), None)
        finished = next((row for row in reversed(group) if row.get("event") == "monitor_once_finished"), None)
        if not started and not finished:
            continue
        finish_data = dict((finished or {}).get("data") or {})
        task_id = next((row.get("task_id") for row in group if row.get("task_id") is not None), None)
        product_id = next((row.get("product_id") for row in reversed(group) if row.get("product_id") is not None), None)
        observation_id = next(
            (row.get("observation_id") for row in reversed(group) if row.get("observation_id") is not None),
            None,
        )
        product = products.get(product_id, {})
        observation = observations.get(observation_id, {})
        metrics = {name: observation.get(name) for name in METRIC_FIELDS if observation.get(name) is not None}
        matching_search = [
            row
            for row in search_rows
            if (observation_id is not None and row.get("observation_id") == observation_id)
            or (product_id is not None and row.get("product_id") == product_id)
        ]
        task = task_by_id.get(task_id, {})
        skips = finish_data.get("skipped") or ()
        skip_reason = None
        if skips:
            first = skips[0]
            skip_reason = first.get("reason") if isinstance(first, Mapping) else str(first)
        dry_run = bool(((started or {}).get("data") or {}).get("limits", {}).get("dry_run"))
        rounds.append(
            {
                "run_id": run_id,
                "task_id": task_id,
                "keyword": task.get("keyword"),
                "started_at": (started or {}).get("event_at"),
                "finished_at": (finished or {}).get("event_at"),
                "result": "completed" if finished and finish_data.get("captured_products", 0) else "failed",
                "success": bool(finished and finish_data.get("captured_products", 0)),
                "busy": bool(finish_data.get("busy")),
                "blocked": finish_data.get("blocked"),
                "skip_reason": skip_reason,
                "risk_stop_reason": next(
                    (
                        row.get("message")
                        for row in group
                        if row.get("event") == "monitor_paused_by_guard"
                    ),
                    None,
                ),
                "product_id": product_id,
                "observation_id": observation_id,
                "search_recovered": any(row.get("event") in SEARCH_RECOVERY_EVENTS for row in group),
                "share_url": product.get("share_url"),
                "metrics": metrics,
                "evidence_path": (
                    observation.get("screenshot_path")
                    or next((row.get("search_probe_dir") for row in matching_search if row.get("search_probe_dir")), None)
                    or (finish_data.get("report") or {}).get("report_path")
                ),
                "dry_run": dry_run,
                "source_kind": "simulation" if dry_run else "real",
                "sqlite_error": next(
                    (
                        row.get("message")
                        for row in group
                        if _contains_sqlite_lock(row.get("message"))
                        or _contains_sqlite_lock(row.get("data"))
                    ),
                    None,
                ),
            }
        )
    return sorted(rounds, key=lambda row: str(row.get("started_at") or ""))


def _read_monitor_state(conn: sqlite3.Connection) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value FROM monitor_state"):
        try:
            state[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            state[row["key"]] = row["value"]
    return state


def _scheduler_recovery(bundle: Mapping[str, Any]) -> dict[str, int]:
    events = list(bundle.get("scheduler_events") or ())
    state = dict(bundle.get("monitor_state") or {})
    snapshot = dict(bundle.get("scheduler_snapshot") or bundle.get("scheduler") or {})
    exception_count = sum(
        1 for row in events if str(row.get("kind") or row.get("event") or "").casefold() in {"exception", "scheduler_exception"}
    )
    recovery_count = sum(
        1 for row in events if _truthy(row.get("recovered")) or str(row.get("kind") or "").casefold() == "recovered"
    )
    if not events and state.get("last_scheduler_exception"):
        exception_count = 1
        recovery_count = int(state.get("scheduler_recovery_count") or 0)
    elif not events and snapshot.get("last_exception"):
        exception_count = 1
        recovery_count = int(snapshot.get("recovery_count") or 0)
    unrecovered = sum(
        1
        for row in events
        if str(row.get("kind") or row.get("event") or "").casefold() in {"exception", "scheduler_exception"}
        and not _truthy(row.get("recovered"))
    )
    if not events and exception_count:
        consecutive = int(
            state.get("scheduler_consecutive_failures")
            if state.get("scheduler_consecutive_failures") is not None
            else snapshot.get("consecutive_failures") or 0
        )
        unrecovered = 0 if recovery_count and consecutive == 0 else 1
    return {
        "exception_count": exception_count,
        "recovery_count": recovery_count,
        "unrecovered_count": unrecovered,
    }


def _alert_state(
    bundle: Mapping[str, Any],
    *,
    ack_ledger_path: str | Path | None,
    ack_allowed_roots: Sequence[str | Path] | None,
    ack_readiness: AckReadiness | Mapping[str, Any] | None,
) -> dict[str, Any]:
    digest_unacked = 0
    quality_errors = 0
    quality_unacked = 0
    required_alert_ids: set[str] = set()
    evidence_mismatches: list[str] = []
    for snapshot in bundle.get("digest_snapshots") or ():
        named_alert_count = 0
        digest_unacked += int(snapshot.get("unacked_critical_count") or snapshot.get("unacked_error_count") or 0)
        for alert in snapshot.get("alerts") or ():
            if str(alert.get("severity") or "").casefold() not in {"critical", "error"}:
                continue
            named_alert_count += 1
            alert_id = _alert_id(alert)
            if alert_id is None:
                evidence_mismatches.append("digest critical/error 告警缺少 alert_id")
            else:
                required_alert_ids.add(alert_id)
            if not _truthy(alert.get("acknowledged") or alert.get("operator_ack")):
                digest_unacked += 1
        declared_unacked = int(
            snapshot.get("unacked_critical_count")
            or snapshot.get("unacked_error_count")
            or 0
        )
        if declared_unacked > named_alert_count:
            evidence_mismatches.append(
                f"digest 声明 {declared_unacked} 个未 ACK 告警，但只有 "
                f"{named_alert_count} 个具名 critical/error 告警"
            )
    for snapshot in bundle.get("quality_snapshots") or ():
        summary = snapshot.get("summary") or snapshot
        count = int(
            summary.get("error_count")
            or (summary.get("by_severity") or {}).get("error")
            or 0
        )
        quality_errors += count
        if count and not _truthy(snapshot.get("acknowledged") or snapshot.get("operator_ack")):
            quality_unacked += count
        named_error_count = 0
        for issue in snapshot.get("issues") or snapshot.get("alerts") or ():
            if str(issue.get("severity") or "").casefold() != "error":
                continue
            named_error_count += 1
            alert_id = _alert_id(issue)
            if alert_id is None:
                evidence_mismatches.append("quality error 告警缺少 alert_id")
            else:
                required_alert_ids.add(alert_id)
        if count > named_error_count:
            evidence_mismatches.append(
                f"quality 声明 {count} 个 error，但只有 {named_error_count} 个具名 error 告警"
            )

    explicit_required = bundle.get("required_ack_alert_ids")
    if explicit_required is not None:
        try:
            if isinstance(explicit_required, (str, bytes)):
                raise TypeError("必须是告警 ID 列表，不能是单个字符串")
            supplied_ids = {_required_alert_id(item) for item in explicit_required}
        except (TypeError, ValueError) as exc:
            evidence_mismatches.append(f"required_ack_alert_ids 无效：{exc}")
        else:
            if required_alert_ids and supplied_ids != required_alert_ids:
                evidence_mismatches.append(
                    "required_ack_alert_ids 与快照中的 critical/error 告警 ID 不匹配"
                )
            required_alert_ids.update(supplied_ids)

    required = tuple(sorted(required_alert_ids))
    resolved_ack = (
        ack_readiness
        if ack_readiness is not None
        else bundle.get("ack_readiness")
    )
    resolved_ledger = (
        ack_ledger_path
        if ack_ledger_path is not None
        else bundle.get("ack_ledger_path")
    )
    resolved_roots = (
        ack_allowed_roots
        if ack_allowed_roots is not None
        else bundle.get("ack_allowed_roots")
    )
    ack_state = _resolve_ack_state(
        required,
        evidence_mismatches,
        ack_ledger_path=resolved_ledger,
        ack_allowed_roots=resolved_roots,
        ack_readiness=resolved_ack,
    )
    return {
        "digest_unacked": digest_unacked,
        "quality_errors": quality_errors,
        "quality_unacked": quality_unacked,
        **ack_state,
    }


def _resolve_ack_state(
    required_alert_ids: tuple[str, ...],
    evidence_mismatches: Sequence[str],
    *,
    ack_ledger_path: str | Path | None,
    ack_allowed_roots: Sequence[str | Path] | None,
    ack_readiness: AckReadiness | Mapping[str, Any] | None,
) -> dict[str, Any]:
    mismatches = list(evidence_mismatches)
    if not required_alert_ids and not mismatches:
        return {
            "ready": True,
            "source": "not_required",
            "required_alert_ids": (),
            "acknowledged_alert_ids": (),
            "missing_alert_ids": (),
            "unresolved_alert_ids": (),
            "latest_decisions": {},
            "integrity_error": None,
            "evidence_mismatches": (),
        }

    if ack_readiness is not None and ack_ledger_path is not None:
        mismatches.append("同时提供 ACK 账本和评估结果，来源不唯一")
    source = "evaluation" if ack_readiness is not None else "ledger"
    report: AckReadiness | Mapping[str, Any] | None = ack_readiness
    integrity_error: str | None = None
    if report is None and ack_ledger_path is not None:
        if not ack_allowed_roots:
            integrity_error = "ACK 账本缺少 ack_allowed_roots"
        else:
            report = evaluate_ack_readiness(
                ack_ledger_path,
                allowed_roots=ack_allowed_roots,
                required_alert_ids=required_alert_ids,
            )
    elif report is None:
        source = "missing"
        integrity_error = "critical/error 告警缺少 ACK 账本或评估结果"

    values = report.as_dict() if isinstance(report, AckReadiness) else dict(report or {})
    reported_required = _alert_id_tuple(values.get("required_alert_ids"))
    acknowledged = _alert_id_tuple(values.get("acknowledged_alert_ids"))
    missing = _alert_id_tuple(values.get("missing_alert_ids"))
    unresolved = _alert_id_tuple(values.get("unresolved_alert_ids"))
    latest_raw = values.get("latest_decisions")
    latest = (
        {
            _required_alert_id(key): str(value).strip().casefold()
            for key, value in latest_raw.items()
        }
        if isinstance(latest_raw, Mapping)
        else {}
    )
    report_integrity = values.get("integrity_error")
    if report_integrity:
        integrity_error = str(report_integrity)
    if report is not None and reported_required != required_alert_ids:
        mismatches.append("ACK 评估 required_alert_ids 与 readiness 告警 ID 不匹配")
    unexpected = (set(acknowledged) | set(missing) | set(unresolved) | set(latest)) - set(
        required_alert_ids
    )
    if unexpected:
        mismatches.append("ACK 评估包含 readiness 未要求的告警 ID")

    latest_non_ack = tuple(
        alert_id
        for alert_id in required_alert_ids
        if latest.get(alert_id) not in {None, "acknowledge"}
    )
    unresolved = tuple(sorted(set(unresolved) | set(latest_non_ack)))
    missing = tuple(
        sorted(
            set(missing)
            | {
                alert_id
                for alert_id in required_alert_ids
                if alert_id not in latest
            }
        )
    )
    acknowledged = tuple(
        alert_id
        for alert_id in required_alert_ids
        if latest.get(alert_id) == "acknowledge"
    )
    ready = bool(
        report is not None
        and values.get("ready") is True
        and not integrity_error
        and not mismatches
        and not missing
        and not unresolved
        and acknowledged == required_alert_ids
    )
    return {
        "ready": ready,
        "source": source,
        "required_alert_ids": required_alert_ids,
        "acknowledged_alert_ids": acknowledged,
        "missing_alert_ids": missing,
        "unresolved_alert_ids": unresolved,
        "latest_decisions": {
            alert_id: latest[alert_id]
            for alert_id in required_alert_ids
            if alert_id in latest
        },
        "integrity_error": integrity_error,
        "evidence_mismatches": tuple(dict.fromkeys(mismatches)),
    }


def _alert_id(value: Mapping[str, Any]) -> str | None:
    raw = value.get("alert_id")
    if raw in (None, ""):
        raw = value.get("id")
    try:
        return _required_alert_id(raw)
    except (TypeError, ValueError):
        return None


def _required_alert_id(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("alert ID 必须是字符串")
    text = value.strip()
    if not text or any(character in text for character in ("\r", "\n", "\x00")):
        raise ValueError("alert ID 不能为空或包含控制字符")
    return text


def _alert_id_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        return ()
    try:
        return tuple(sorted({_required_alert_id(item) for item in value}))
    except (TypeError, ValueError):
        return ()


def _ack_failure_reason(
    alerts: Mapping[str, Any],
    *,
    prefix: str = "",
) -> str:
    if alerts["integrity_error"]:
        return f"{prefix}critical/error ACK 账本或评估损坏"
    if alerts["evidence_mismatches"]:
        return f"{prefix}critical/error 告警与 ACK 证据 ID 不匹配"
    if alerts["unresolved_alert_ids"]:
        return f"{prefix}critical/error 告警最新决定不是 acknowledge"
    return f"{prefix}critical/error 告警缺少 ACK"


def _snapshot_coverage(bundle: Mapping[str, Any]) -> dict[str, set[str]]:
    coverage = {"digest": set(), "quality": set()}
    for key, kind in (
        ("digest_snapshots", "digest"),
        ("quality_snapshots", "quality"),
    ):
        for row in bundle.get(key) or ():
            phase = str(row.get("phase") or row.get("checkpoint") or "").strip().casefold()
            if phase in {"start", "begin", "initial"}:
                coverage[kind].add("start")
            elif phase in {"mid", "middle", "midpoint", "12h"}:
                coverage[kind].add("mid")
            elif phase in {"end", "finish", "final"}:
                coverage[kind].add("end")
    coverage["combined"] = coverage["digest"] | coverage["quality"]
    return coverage


def _active_leases(bundle: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    leases = [
        row
        for row in bundle.get("leases") or ()
        if row.get("active") is not False and not _truthy(row.get("released"))
    ]
    declared = int(bundle.get("active_lease_count") or 0)
    leases.extend({"declared_active_lease": index + 1} for index in range(max(0, declared - len(leases))))
    return leases


def _running_tasks(bundle: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    tasks = [
        row
        for row in bundle.get("tasks") or ()
        if str(row.get("status") or "").casefold() in ACTIVE_TASK_STATUSES
    ]
    declared = int(bundle.get("running_task_count") or 0)
    tasks.extend({"declared_running_task": index + 1} for index in range(max(0, declared - len(tasks))))
    return tasks


def _sqlite_lock_count(bundle: Mapping[str, Any], rounds: Sequence[Mapping[str, Any]]) -> int:
    count = int(bundle.get("sqlite_lock_error_count") or 0)
    count += sum(_contains_sqlite_lock(row.get("sqlite_error")) for row in rounds)
    for event in bundle.get("sqlite_events") or ():
        if _contains_sqlite_lock(event):
            count += 1
    return count


def _span_hours(rounds: Sequence[Mapping[str, Any]]) -> float:
    points: list[datetime] = []
    for row in rounds:
        start = row.get("started_at") or row.get("scheduled_at")
        end = row.get("finished_at") or row.get("started_at")
        if start:
            points.append(start)
        if end:
            points.append(end)
    if len(points) < 2:
        return 0.0
    return round((max(points) - min(points)).total_seconds() / 3600, 3)


def _max_start_delay(rounds: Sequence[Mapping[str, Any]]) -> float | None:
    delays = [
        (row["started_at"] - row["scheduled_at"]).total_seconds()
        for row in rounds
        if row.get("scheduled_at") and row.get("started_at")
    ]
    return max(delays) if delays else None


def _cooldown_duplicates(rounds: Sequence[Mapping[str, Any]]) -> list[str]:
    by_keyword: dict[str, list[datetime]] = {}
    duplicates: set[str] = set()
    for row in rounds:
        keyword = str(row.get("keyword") or "").strip().casefold()
        at = row.get("started_at")
        if not keyword or not at or _truthy(row.get("manual_repeat_authorized")):
            continue
        previous = by_keyword.setdefault(keyword, [])
        if any(abs((at - seen).total_seconds()) < 24 * 3600 for seen in previous):
            duplicates.add(keyword)
        previous.append(at)
    return sorted(duplicates)


def _explicit_bool(bundle: Mapping[str, Any], key: str) -> bool | None:
    if key not in bundle:
        offline = bundle.get("offline") or {}
        if key not in offline:
            return None
        return _truthy(offline.get(key))
    return _truthy(bundle.get(key))


def _has_metrics(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(item not in (None, "", False) for item in value.values())
    return bool(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "ok", "passed", "success", "completed"}
    return bool(value)


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone() if value.tzinfo is None else value
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone() if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value) if value not in (None, "") else None


def _contains_sqlite_lock(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False, default=str).casefold()
    return any(marker in text for marker in SQLITE_LOCK_MARKERS)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql)]
