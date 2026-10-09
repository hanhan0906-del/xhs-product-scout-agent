from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
STAGES = {"G2", "G4"}
EVIDENCE_SOURCES = {"simulated", "real"}
RESULTS = {"completed", "busy", "skipped", "blocked", "failed"}
LEASE_STATES = {"released", "active", "not_acquired", "lost", "taken_over"}
DB_STATUSES = {"ok", "busy", "error", "not_checked"}
DESIRED_STATES = {"running", "paused", "stopped"}
HTTP_KEYS = {"api_status", "monitor_status", "candidates_csv"}
RECORD_FIELDS = {
    "schema_version",
    "sequence",
    "record_id",
    "stage",
    "soak_id",
    "due_point_id",
    "evidence_source",
    "scheduled_at",
    "started_at",
    "finished_at",
    "start_delay_seconds",
    "duration_seconds",
    "result",
    "run_id",
    "task_id",
    "product_id",
    "observation_id",
    "keyword",
    "keyword_source",
    "portfolio_cursor_before",
    "portfolio_cursor_after",
    "portfolio_selected",
    "portfolio_deferred_reason",
    "risk_stop_reason",
    "last_block_reason",
    "last_skip_reason",
    "run_lease_owner",
    "task_lease_owner",
    "lease_state",
    "desired_state",
    "scheduler_running",
    "scheduler_thread_alive",
    "scheduler_worker_state",
    "db_status",
    "sqlite_error",
    "db_evidence_path",
    "http_status",
    "http_evidence_path",
    "evidence_paths",
    "operator_ack_refs",
    "previous_hash",
    "record_hash",
}
INPUT_FIELDS = RECORD_FIELDS - {
    "schema_version",
    "sequence",
    "previous_hash",
    "record_hash",
}
SENSITIVE_FIELD_MARKERS = {
    "credential",
    "credentials",
    "cookie",
    "cookies",
    "password",
    "passwd",
    "secret",
    "token",
}


class SchedulerEvidenceError(ValueError):
    """Base class for rejected scheduler evidence."""


class SchedulerEvidenceConflictError(SchedulerEvidenceError):
    """Raised when an append conflicts with an existing immutable record."""


class SchedulerEvidenceIntegrityError(SchedulerEvidenceError):
    """Raised when an existing evidence ledger cannot be verified."""


@dataclass(frozen=True)
class SchedulerEvidenceRecord:
    schema_version: int
    sequence: int
    record_id: str
    stage: str
    soak_id: str
    due_point_id: str
    evidence_source: str
    scheduled_at: str
    started_at: str
    finished_at: str
    start_delay_seconds: float
    duration_seconds: float
    result: str
    run_id: str | None
    task_id: str | int | None
    product_id: str | int | None
    observation_id: str | int | None
    keyword: str | None
    keyword_source: str | None
    portfolio_cursor_before: str | int | None
    portfolio_cursor_after: str | int | None
    portfolio_selected: tuple[str, ...]
    portfolio_deferred_reason: str | None
    risk_stop_reason: str | None
    last_block_reason: str | None
    last_skip_reason: str | None
    run_lease_owner: str | None
    task_lease_owner: str | None
    lease_state: str
    desired_state: str
    scheduler_running: bool
    scheduler_thread_alive: bool
    scheduler_worker_state: str
    db_status: str
    sqlite_error: str | None
    db_evidence_path: str
    http_status: Mapping[str, int | None]
    http_evidence_path: str
    evidence_paths: tuple[str, ...]
    operator_ack_refs: tuple[str, ...]
    previous_hash: str | None
    record_hash: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["portfolio_selected"] = list(self.portfolio_selected)
        value["evidence_paths"] = list(self.evidence_paths)
        value["operator_ack_refs"] = list(self.operator_ack_refs)
        value["http_status"] = dict(self.http_status)
        return value


@dataclass(frozen=True)
class StageEvidenceSummary:
    stage: str
    ready_for_gate_evaluation: bool
    expected_due_point_count: int
    recorded_due_point_count: int
    real_due_point_count: int
    simulated_due_point_count: int
    result_counts: Mapping[str, int]
    missing_due_point_ids: tuple[str, ...]
    unexpected_due_point_ids: tuple[str, ...]
    duplicate_due_point_ids: tuple[str, ...]
    max_start_delay_seconds: float | None
    max_duration_seconds: float | None
    risk_count: int
    blocked_count: int
    missing_ack_count: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["result_counts"] = dict(self.result_counts)
        return value


@dataclass(frozen=True)
class SchedulerEvidenceReport:
    ready: bool
    ledger_integrity_ok: bool
    record_count: int
    stages: Mapping[str, StageEvidenceSummary]
    integrity_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "ledger_integrity_ok": self.ledger_integrity_ok,
            "record_count": self.record_count,
            "stages": {
                stage: summary.as_dict()
                for stage, summary in sorted(self.stages.items())
            },
            "integrity_error": self.integrity_error,
        }


def append_scheduler_evidence(
    ledger_path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
    evidence: Mapping[str, Any],
) -> SchedulerEvidenceRecord:
    """Append one immutable scheduler due-point record to a local JSONL ledger."""

    roots = _resolve_allowed_roots(allowed_roots)
    ledger = _resolve_output_path(ledger_path, roots)
    supplied = dict(evidence)
    unknown = set(supplied) - INPUT_FIELDS
    missing = INPUT_FIELDS - set(supplied)
    if unknown or missing:
        raise SchedulerEvidenceError(
            "evidence has invalid fields; "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    _reject_sensitive_fields(supplied)
    normalized = _normalise_payload(supplied, roots=roots)

    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ledger.with_name(f"{ledger.name}.lock")
    lock_fd = _acquire_lock(lock_path)
    try:
        existing = read_scheduler_evidence(ledger, allowed_roots=roots)
        duplicate = next(
            (row for row in existing if row.record_id == normalized["record_id"]),
            None,
        )
        if duplicate is not None:
            if _same_input(duplicate, normalized):
                return duplicate
            raise SchedulerEvidenceConflictError(
                f"record_id {normalized['record_id']!r} already has different content"
            )
        if any(row.due_point_id == normalized["due_point_id"] for row in existing):
            raise SchedulerEvidenceConflictError(
                f"due_point_id {normalized['due_point_id']!r} already exists"
            )

        payload = {
            "schema_version": SCHEMA_VERSION,
            "sequence": len(existing) + 1,
            **normalized,
            "previous_hash": existing[-1].record_hash if existing else None,
        }
        payload["record_hash"] = _record_hash(payload)
        record = _record_from_mapping(payload, roots=roots)
        with ledger.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(record.as_dict()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record
    finally:
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)


def read_scheduler_evidence(
    ledger_path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
) -> tuple[SchedulerEvidenceRecord, ...]:
    """Read and verify a ledger in deterministic physical sequence."""

    roots = _resolve_allowed_roots(allowed_roots)
    ledger = _resolve_output_path(ledger_path, roots)
    if not ledger.exists():
        return ()
    if not ledger.is_file():
        raise SchedulerEvidenceIntegrityError(
            "scheduler evidence ledger is not a regular file"
        )
    raw = ledger.read_text(encoding="utf-8")
    if not raw:
        return ()
    if not raw.endswith("\n"):
        raise SchedulerEvidenceIntegrityError(
            "scheduler evidence ledger has a truncated final line"
        )

    records: list[SchedulerEvidenceRecord] = []
    seen_record_ids: set[str] = set()
    seen_due_points: set[str] = set()
    previous_hash: str | None = None
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise SchedulerEvidenceIntegrityError(
                f"blank line at ledger line {line_number}"
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SchedulerEvidenceIntegrityError(
                f"invalid JSON at ledger line {line_number}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise SchedulerEvidenceIntegrityError(
                f"ledger line {line_number} must contain a JSON object"
            )
        _reject_sensitive_fields(payload, integrity=True)
        unknown = set(payload) - RECORD_FIELDS
        missing = RECORD_FIELDS - set(payload)
        if unknown or missing:
            raise SchedulerEvidenceIntegrityError(
                f"ledger line {line_number} has invalid fields; "
                f"missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        record = _record_from_mapping(payload, roots=roots, integrity=True)
        if record.sequence != line_number:
            raise SchedulerEvidenceIntegrityError(
                f"ledger line {line_number} has non-contiguous sequence"
            )
        if record.record_id in seen_record_ids:
            raise SchedulerEvidenceIntegrityError(
                f"duplicate record_id {record.record_id!r} in ledger"
            )
        if record.due_point_id in seen_due_points:
            raise SchedulerEvidenceIntegrityError(
                f"duplicate due_point_id {record.due_point_id!r} in ledger"
            )
        if record.previous_hash != previous_hash:
            raise SchedulerEvidenceIntegrityError(
                f"ledger line {line_number} breaks the previous-hash chain"
            )
        if _record_hash(payload) != record.record_hash:
            raise SchedulerEvidenceIntegrityError(
                f"ledger line {line_number} has an invalid record hash"
            )
        records.append(record)
        seen_record_ids.add(record.record_id)
        seen_due_points.add(record.due_point_id)
        previous_hash = record.record_hash
    return tuple(records)


def evaluate_scheduler_evidence(
    ledger_path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
    expected_due_points: Mapping[str, int | Sequence[str]],
    max_start_delay_seconds: float = 900,
) -> SchedulerEvidenceReport:
    """Fail closed and summarise G2/G4 due-point coverage deterministically."""

    expected = _normalise_expected_due_points(expected_due_points)
    if max_start_delay_seconds < 0:
        raise SchedulerEvidenceError("max_start_delay_seconds must be non-negative")
    try:
        records = read_scheduler_evidence(
            ledger_path,
            allowed_roots=allowed_roots,
        )
    except (OSError, SchedulerEvidenceError) as exc:
        empty = {
            stage: _integrity_failure_summary(stage, identifiers)
            for stage, identifiers in expected.items()
        }
        return SchedulerEvidenceReport(
            ready=False,
            ledger_integrity_ok=False,
            record_count=0,
            stages=empty,
            integrity_error=str(exc),
        )

    stages = {
        stage: _summarise_stage(
            stage,
            [record for record in records if record.stage == stage],
            identifiers,
            max_start_delay_seconds=max_start_delay_seconds,
        )
        for stage, identifiers in expected.items()
    }
    return SchedulerEvidenceReport(
        ready=bool(stages)
        and all(summary.ready_for_gate_evaluation for summary in stages.values()),
        ledger_integrity_ok=True,
        record_count=len(records),
        stages=stages,
    )


def _summarise_stage(
    stage: str,
    records: Sequence[SchedulerEvidenceRecord],
    expected: tuple[str, ...] | int,
    *,
    max_start_delay_seconds: float,
) -> StageEvidenceSummary:
    due_ids = [record.due_point_id for record in records]
    duplicates = tuple(
        sorted({due_id for due_id in due_ids if due_ids.count(due_id) > 1})
    )
    if isinstance(expected, int):
        expected_count = expected
        missing_ids: tuple[str, ...] = ()
        unexpected_ids: tuple[str, ...] = ()
        count_missing = max(0, expected - len(records))
    else:
        expected_set = set(expected)
        actual_set = set(due_ids)
        expected_count = len(expected)
        missing_ids = tuple(sorted(expected_set - actual_set))
        unexpected_ids = tuple(sorted(actual_set - expected_set))
        count_missing = len(missing_ids)

    result_counts = {result: 0 for result in sorted(RESULTS)}
    for record in records:
        result_counts[record.result] += 1
    risk_count = sum(bool(record.risk_stop_reason) for record in records)
    blocked_count = sum(record.result == "blocked" or bool(record.last_block_reason) for record in records)
    missing_ack_count = sum(
        bool(
            record.risk_stop_reason
            or record.last_block_reason
            or record.sqlite_error
            or record.db_status in {"busy", "error"}
            or any(status not in (200, None) for status in record.http_status.values())
        )
        and not record.operator_ack_refs
        for record in records
    )
    reasons: list[str] = []
    if count_missing:
        reasons.append(f"missing {count_missing} expected due point(s)")
    if unexpected_ids:
        reasons.append(f"unexpected due point ids: {', '.join(unexpected_ids)}")
    if duplicates:
        reasons.append(f"duplicate due point ids: {', '.join(duplicates)}")
    simulated = sum(record.evidence_source == "simulated" for record in records)
    if simulated:
        reasons.append(f"{simulated} simulated due point(s) are not admissible")
    if any(record.start_delay_seconds > max_start_delay_seconds for record in records):
        reasons.append(
            f"start delay exceeds {max_start_delay_seconds:g} seconds"
        )
    if risk_count:
        reasons.append(f"{risk_count} due point(s) contain risk")
    if blocked_count:
        reasons.append(f"{blocked_count} due point(s) are blocked")
    if missing_ack_count:
        reasons.append(
            f"{missing_ack_count} exceptional due point(s) lack operator ACK references"
        )
    if any(record.lease_state in {"active", "lost"} for record in records):
        reasons.append("lease state is active or lost")
    if any(
        record.db_status != "ok" or bool(record.sqlite_error)
        for record in records
    ):
        reasons.append("DB evidence is not healthy")
    if any(
        set(record.http_status) != HTTP_KEYS
        or any(status != 200 for status in record.http_status.values())
        for record in records
    ):
        reasons.append("HTTP evidence is incomplete or unhealthy")
    if any(
        not record.scheduler_running
        or not record.scheduler_thread_alive
        or record.desired_state != "running"
        for record in records
    ):
        reasons.append("scheduler/thread state is not consistently running")

    return StageEvidenceSummary(
        stage=stage,
        ready_for_gate_evaluation=not reasons
        and len(records) == expected_count
        and expected_count > 0,
        expected_due_point_count=expected_count,
        recorded_due_point_count=len(records),
        real_due_point_count=sum(record.evidence_source == "real" for record in records),
        simulated_due_point_count=simulated,
        result_counts=result_counts,
        missing_due_point_ids=missing_ids,
        unexpected_due_point_ids=unexpected_ids,
        duplicate_due_point_ids=duplicates,
        max_start_delay_seconds=max(
            (record.start_delay_seconds for record in records),
            default=None,
        ),
        max_duration_seconds=max(
            (record.duration_seconds for record in records),
            default=None,
        ),
        risk_count=risk_count,
        blocked_count=blocked_count,
        missing_ack_count=missing_ack_count,
        reasons=tuple(reasons),
    )


def _integrity_failure_summary(
    stage: str,
    expected: tuple[str, ...] | int,
) -> StageEvidenceSummary:
    expected_count = expected if isinstance(expected, int) else len(expected)
    missing = () if isinstance(expected, int) else expected
    return StageEvidenceSummary(
        stage=stage,
        ready_for_gate_evaluation=False,
        expected_due_point_count=expected_count,
        recorded_due_point_count=0,
        real_due_point_count=0,
        simulated_due_point_count=0,
        result_counts={result: 0 for result in sorted(RESULTS)},
        missing_due_point_ids=missing,
        unexpected_due_point_ids=(),
        duplicate_due_point_ids=(),
        max_start_delay_seconds=None,
        max_duration_seconds=None,
        risk_count=0,
        blocked_count=0,
        missing_ack_count=0,
        reasons=("ledger integrity could not be verified",),
    )


def _record_from_mapping(
    payload: Mapping[str, Any],
    *,
    roots: Sequence[Path],
    integrity: bool = False,
) -> SchedulerEvidenceRecord:
    error_type = (
        SchedulerEvidenceIntegrityError if integrity else SchedulerEvidenceError
    )
    try:
        schema_version = _strict_int(payload["schema_version"], "schema_version")
        sequence = _strict_int(payload["sequence"], "sequence")
        if schema_version != SCHEMA_VERSION or sequence < 1:
            raise SchedulerEvidenceError(
                "schema_version or sequence is invalid"
            )
        normalized = _normalise_payload(payload, roots=roots)
        previous_hash = payload["previous_hash"]
        if previous_hash is not None:
            previous_hash = _hash_text(previous_hash, "previous_hash")
        return SchedulerEvidenceRecord(
            schema_version=schema_version,
            sequence=sequence,
            **normalized,
            previous_hash=previous_hash,
            record_hash=_hash_text(payload["record_hash"], "record_hash"),
        )
    except (KeyError, TypeError, ValueError, SchedulerEvidenceError) as exc:
        raise error_type(f"invalid scheduler evidence record: {exc}") from exc


def _normalise_payload(
    payload: Mapping[str, Any],
    *,
    roots: Sequence[Path],
) -> dict[str, Any]:
    scheduled = _datetime(payload["scheduled_at"], "scheduled_at")
    started = _datetime(payload["started_at"], "started_at")
    finished = _datetime(payload["finished_at"], "finished_at")
    if started < scheduled:
        raise SchedulerEvidenceError("started_at must not precede scheduled_at")
    if finished < started:
        raise SchedulerEvidenceError("finished_at must not precede started_at")
    delay = _non_negative_number(
        payload["start_delay_seconds"],
        "start_delay_seconds",
    )
    duration = _non_negative_number(
        payload["duration_seconds"],
        "duration_seconds",
    )
    actual_delay = (started - scheduled).total_seconds()
    actual_duration = (finished - started).total_seconds()
    if abs(delay - actual_delay) > 0.001:
        raise SchedulerEvidenceError(
            "start_delay_seconds does not match scheduled_at/started_at"
        )
    if abs(duration - actual_duration) > 0.001:
        raise SchedulerEvidenceError(
            "duration_seconds does not match started_at/finished_at"
        )

    result = _choice(payload["result"], RESULTS, "result")
    run_id = _optional_text(payload["run_id"], "run_id")
    task_id = _optional_identifier(payload["task_id"], "task_id")
    product_id = _optional_identifier(payload["product_id"], "product_id")
    observation_id = _optional_identifier(
        payload["observation_id"],
        "observation_id",
    )
    keyword = _optional_text(payload["keyword"], "keyword")
    keyword_source = _optional_text(payload["keyword_source"], "keyword_source")
    selected = _text_tuple(payload["portfolio_selected"], "portfolio_selected")
    risk = _optional_text(payload["risk_stop_reason"], "risk_stop_reason")
    block = _optional_text(payload["last_block_reason"], "last_block_reason")
    skip = _optional_text(payload["last_skip_reason"], "last_skip_reason")
    if result == "completed":
        required_values = {
            "run_id": run_id,
            "task_id": task_id,
            "product_id": product_id,
            "observation_id": observation_id,
            "keyword": keyword,
            "keyword_source": keyword_source,
        }
        missing = [name for name, value in required_values.items() if value is None]
        if missing:
            raise SchedulerEvidenceError(
                f"completed result is missing {', '.join(missing)}"
            )
    if result == "skipped" and not skip:
        raise SchedulerEvidenceError(
            "skipped result requires last_skip_reason"
        )
    if result == "blocked" and not (block or risk):
        raise SchedulerEvidenceError(
            "blocked result requires last_block_reason or risk_stop_reason"
        )

    http_status = _http_status(payload["http_status"])
    evidence_paths = _path_tuple(
        payload["evidence_paths"],
        roots,
        "evidence_paths",
    )
    if not evidence_paths:
        raise SchedulerEvidenceError("evidence_paths must not be empty")
    return {
        "record_id": _required_text(payload["record_id"], "record_id"),
        "stage": _choice(payload["stage"], STAGES, "stage").upper(),
        "soak_id": _required_text(payload["soak_id"], "soak_id"),
        "due_point_id": _required_text(payload["due_point_id"], "due_point_id"),
        "evidence_source": _choice(
            payload["evidence_source"],
            EVIDENCE_SOURCES,
            "evidence_source",
        ),
        "scheduled_at": scheduled.isoformat(timespec="seconds"),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "start_delay_seconds": delay,
        "duration_seconds": duration,
        "result": result,
        "run_id": run_id,
        "task_id": task_id,
        "product_id": product_id,
        "observation_id": observation_id,
        "keyword": keyword,
        "keyword_source": keyword_source,
        "portfolio_cursor_before": _optional_identifier(
            payload["portfolio_cursor_before"],
            "portfolio_cursor_before",
        ),
        "portfolio_cursor_after": _optional_identifier(
            payload["portfolio_cursor_after"],
            "portfolio_cursor_after",
        ),
        "portfolio_selected": selected,
        "portfolio_deferred_reason": _optional_text(
            payload["portfolio_deferred_reason"],
            "portfolio_deferred_reason",
        ),
        "risk_stop_reason": risk,
        "last_block_reason": block,
        "last_skip_reason": skip,
        "run_lease_owner": _optional_text(
            payload["run_lease_owner"],
            "run_lease_owner",
        ),
        "task_lease_owner": _optional_text(
            payload["task_lease_owner"],
            "task_lease_owner",
        ),
        "lease_state": _choice(
            payload["lease_state"],
            LEASE_STATES,
            "lease_state",
        ),
        "desired_state": _choice(
            payload["desired_state"],
            DESIRED_STATES,
            "desired_state",
        ),
        "scheduler_running": _strict_bool(
            payload["scheduler_running"],
            "scheduler_running",
        ),
        "scheduler_thread_alive": _strict_bool(
            payload["scheduler_thread_alive"],
            "scheduler_thread_alive",
        ),
        "scheduler_worker_state": _required_text(
            payload["scheduler_worker_state"],
            "scheduler_worker_state",
        ),
        "db_status": _choice(payload["db_status"], DB_STATUSES, "db_status"),
        "sqlite_error": _optional_text(payload["sqlite_error"], "sqlite_error"),
        "db_evidence_path": str(
            _resolve_existing_path(
                payload["db_evidence_path"],
                roots,
                "db_evidence_path",
            )
        ),
        "http_status": http_status,
        "http_evidence_path": str(
            _resolve_existing_path(
                payload["http_evidence_path"],
                roots,
                "http_evidence_path",
            )
        ),
        "evidence_paths": evidence_paths,
        "operator_ack_refs": _text_tuple(
            payload["operator_ack_refs"],
            "operator_ack_refs",
        ),
    }


def _same_input(
    record: SchedulerEvidenceRecord,
    normalized: Mapping[str, Any],
) -> bool:
    existing = record.as_dict()
    return all(existing[key] == _jsonable(normalized[key]) for key in INPUT_FIELDS)


def _normalise_expected_due_points(
    expected: Mapping[str, int | Sequence[str]],
) -> dict[str, tuple[str, ...] | int]:
    if not isinstance(expected, Mapping) or not expected:
        raise SchedulerEvidenceError(
            "expected_due_points must contain at least one G2/G4 stage"
        )
    result: dict[str, tuple[str, ...] | int] = {}
    for raw_stage, value in expected.items():
        stage = _choice(raw_stage, STAGES, "expected stage").upper()
        if isinstance(value, bool):
            raise SchedulerEvidenceError(
                f"expected due points for {stage} must not be bool"
            )
        if isinstance(value, int):
            if value < 1:
                raise SchedulerEvidenceError(
                    f"expected due point count for {stage} must be positive"
                )
            result[stage] = value
            continue
        identifiers = tuple(
            sorted(
                {
                    _required_text(item, f"{stage} due_point_id")
                    for item in value
                }
            )
        )
        if not identifiers:
            raise SchedulerEvidenceError(
                f"expected due point ids for {stage} must not be empty"
            )
        result[stage] = identifiers
    return dict(sorted(result.items()))


def _resolve_allowed_roots(
    allowed_roots: Sequence[str | Path],
) -> tuple[Path, ...]:
    if not allowed_roots:
        raise SchedulerEvidenceError(
            "allowed_roots must contain at least one explicit root"
        )
    roots: list[Path] = []
    for root in allowed_roots:
        try:
            resolved = Path(root).resolve(strict=True)
        except OSError as exc:
            raise SchedulerEvidenceError(
                f"allowed root does not exist: {root}"
            ) from exc
        if not resolved.is_dir():
            raise SchedulerEvidenceError(
                f"allowed root is not a directory: {resolved}"
            )
        roots.append(resolved)
    return tuple(dict.fromkeys(roots))


def _resolve_output_path(path: str | Path, roots: Sequence[Path]) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        if len(roots) != 1:
            raise SchedulerEvidenceError(
                "relative ledger path requires exactly one allowed root"
            )
        candidate = roots[0] / candidate
    resolved = candidate.resolve(strict=False)
    _require_within_roots(resolved, roots, "ledger_path")
    return resolved


def _resolve_existing_path(
    path: Any,
    roots: Sequence[Path],
    label: str,
) -> Path:
    if isinstance(path, os.PathLike):
        text = os.fspath(path)
    else:
        text = _required_text(path, label)
    candidate = Path(text)
    if not candidate.is_absolute():
        if len(roots) != 1:
            raise SchedulerEvidenceError(
                f"relative {label} requires exactly one allowed root"
            )
        candidate = roots[0] / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SchedulerEvidenceError(f"{label} does not exist: {candidate}") from exc
    _require_within_roots(resolved, roots, label)
    return resolved


def _require_within_roots(
    path: Path,
    roots: Sequence[Path],
    label: str,
) -> None:
    for root in roots:
        try:
            path.relative_to(root)
            return
        except ValueError:
            continue
    raise SchedulerEvidenceError(f"{label} resolves outside allowed roots: {path}")


def _path_tuple(
    value: Any,
    roots: Sequence[Path],
    label: str,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SchedulerEvidenceError(f"{label} must be a list")
    return tuple(
        str(_resolve_existing_path(item, roots, f"{label}[{index}]"))
        for index, item in enumerate(value)
    )


def _http_status(value: Any) -> dict[str, int | None]:
    if not isinstance(value, Mapping):
        raise SchedulerEvidenceError("http_status must be an object")
    if set(value) != HTTP_KEYS:
        raise SchedulerEvidenceError(
            "http_status must contain exactly "
            + ", ".join(sorted(HTTP_KEYS))
        )
    result: dict[str, int | None] = {}
    for key in sorted(HTTP_KEYS):
        status = value[key]
        if status is None:
            result[key] = None
        else:
            parsed = _strict_int(status, f"http_status.{key}")
            if parsed < 100 or parsed > 599:
                raise SchedulerEvidenceError(
                    f"http_status.{key} must be 100..599 or null"
                )
            result[key] = parsed
    return result


def _acquire_lock(lock_path: Path) -> int:
    try:
        return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SchedulerEvidenceConflictError(
            f"scheduler evidence ledger is locked: {lock_path}"
        ) from exc


def _datetime(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(
                _required_text(value, label).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise SchedulerEvidenceError(
                f"{label} must be an ISO-8601 datetime"
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SchedulerEvidenceError(f"{label} must include a timezone offset")
    return parsed


def _required_text(value: Any, label: str) -> str:
    text = _text(value, label).strip()
    if not text:
        raise SchedulerEvidenceError(f"{label} must not be empty")
    if any(character in text for character in ("\r", "\n", "\x00")):
        raise SchedulerEvidenceError(
            f"{label} contains forbidden control characters"
        )
    return text


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise SchedulerEvidenceError(f"{label} must be a string")
    if "\x00" in value:
        raise SchedulerEvidenceError(f"{label} contains a forbidden null byte")
    return value


def _text_tuple(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SchedulerEvidenceError(f"{label} must be a list")
    return tuple(
        _required_text(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    )


def _optional_identifier(value: Any, label: str) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SchedulerEvidenceError(f"{label} must be a string, integer, or null")
    if isinstance(value, int):
        if value < 0:
            raise SchedulerEvidenceError(f"{label} must not be negative")
        return value
    return _required_text(value, label)


def _choice(value: Any, allowed: set[str], label: str) -> str:
    text = _required_text(value, label).casefold()
    lookup = {item.casefold(): item for item in allowed}
    if text not in lookup:
        raise SchedulerEvidenceError(f"{label} must be one of {sorted(allowed)}")
    return lookup[text]


def _strict_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise SchedulerEvidenceError(f"{label} must be a boolean")
    return value


def _strict_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchedulerEvidenceError(f"{label} must be an integer")
    return value


def _non_negative_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchedulerEvidenceError(f"{label} must be a number")
    parsed = float(value)
    if parsed < 0 or parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise SchedulerEvidenceError(f"{label} must be a finite non-negative number")
    return parsed


def _hash_text(value: Any, label: str) -> str:
    text = _required_text(value, label).casefold()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise SchedulerEvidenceError(f"{label} must be a SHA-256 hex digest")
    return text


def _record_hash(payload: Mapping[str, Any]) -> str:
    content = {
        key: _jsonable(value)
        for key, value in payload.items()
        if key != "record_hash"
    }
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _jsonable(item)
            for key, item in sorted(value.items())
        }
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _reject_sensitive_fields(
    value: Any,
    *,
    integrity: bool = False,
    path: str = "record",
) -> None:
    error_type = (
        SchedulerEvidenceIntegrityError
        if integrity
        else SchedulerEvidenceError
    )
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            tokens = {token for token in normalized.split("_") if token}
            if tokens.intersection(SENSITIVE_FIELD_MARKERS):
                raise error_type(f"sensitive field is forbidden: {path}.{key}")
            _reject_sensitive_fields(
                item,
                integrity=integrity,
                path=f"{path}.{key}",
            )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_fields(
                item,
                integrity=integrity,
                path=f"{path}[{index}]",
            )
