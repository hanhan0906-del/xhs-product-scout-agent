from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .remediation_approval import (
    RemediationApprovalManifest,
    read_approval_manifest,
)
from .scheduler_evidence import (
    SchedulerEvidenceReport,
    evaluate_scheduler_evidence,
    read_scheduler_evidence,
)
from .soak_ack import AckReadiness, evaluate_ack_readiness, read_soak_acks
from .soak_baseline import (
    SoakBaselineManifest,
    read_baseline_manifest,
    validate_baseline_manifest,
)
from .soak_readiness import SoakReadinessReport


SCHEMA_VERSION = 1
MANIFEST_KIND = "pre_soak_evidence_bundle"
DEFAULT_MAX_APPROVAL_AGE = timedelta(hours=24)
SOURCE_NAMES = (
    "baseline",
    "ack",
    "scheduler",
    "remediation_approval",
    "readiness",
)
SENSITIVE_FIELD_MARKERS = (
    "credential",
    "credentials",
    "cookie",
    "cookies",
    "password",
    "passwd",
    "secret",
    "token",
    "tokens",
)
AUTHORIZATION_FIELD_MARKERS = (
    "authorizes_execution",
    "execution_authorized",
    "pre_soak_start_authorized",
    "soak_24h_start_authorized",
    "scheduler_start_authorized",
)
SAFETY_FIELDS = {
    "execution_authorized",
    "pre_soak_start_authorized",
    "soak_24h_start_authorized",
    "scheduler_start_authorized",
    "statement",
}
BUNDLE_FIELDS = {
    "schema_version",
    "manifest_kind",
    "bundle_id",
    "status",
    "assembled_at",
    "sources",
    "gaps",
    "safety",
    "manifest_hash",
}


class SoakEvidenceBundleError(ValueError):
    """Raised when caller input is unsafe or a stored bundle is malformed."""


class SoakEvidenceBundlePathError(SoakEvidenceBundleError):
    """Raised when a caller-supplied path escapes the explicit allowed roots."""


class SoakEvidenceBundleSensitiveFieldError(SoakEvidenceBundleError):
    """Raised when an input contains a credential-like field."""


class SoakEvidenceBundleIntegrityError(SoakEvidenceBundleError):
    """Raised when a stored bundle does not match its integrity hash."""


@dataclass(frozen=True)
class EvidenceSource:
    name: str
    source_kind: str
    status: str
    source_hash: str | None
    times: tuple[str, ...]
    gaps: tuple[str, ...]
    details: Mapping[str, Any]

    @property
    def valid(self) -> bool:
        return self.status == "valid"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["times"] = list(self.times)
        value["gaps"] = list(self.gaps)
        value["details"] = _jsonable(self.details)
        return value


@dataclass(frozen=True)
class SoakEvidenceBundle:
    schema_version: int
    manifest_kind: str
    bundle_id: str
    status: str
    assembled_at: str | None
    sources: Mapping[str, EvidenceSource]
    gaps: tuple[str, ...]
    safety: Mapping[str, Any]
    manifest_hash: str

    @property
    def authorizes_execution(self) -> bool:
        return False

    @property
    def authorizes_soak(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_kind": self.manifest_kind,
            "bundle_id": self.bundle_id,
            "status": self.status,
            "assembled_at": self.assembled_at,
            "sources": {
                name: source.as_dict()
                for name, source in sorted(self.sources.items())
            },
            "gaps": list(self.gaps),
            "safety": dict(self.safety),
            "manifest_hash": self.manifest_hash,
        }

    def to_json(self) -> str:
        return _canonical_json(self.as_dict()) + "\n"


def build_soak_evidence_bundle(
    *,
    baseline: SoakBaselineManifest | Mapping[str, Any] | str | Path | None,
    ack: AckReadiness | Mapping[str, Any] | str | Path | None,
    scheduler_evidence: SchedulerEvidenceReport
    | Mapping[str, Any]
    | str
    | Path
    | None,
    scheduler_expected: Mapping[str, int | Sequence[str]] | None,
    remediation_approval: RemediationApprovalManifest
    | Mapping[str, Any]
    | str
    | Path
    | None,
    readiness: SoakReadinessReport | Mapping[str, Any] | str | Path | None,
    allowed_roots: Sequence[str | Path] = (),
    ack_required_alert_ids: Iterable[str] | None = None,
    assembled_at: datetime | str | None = None,
    max_approval_age: timedelta = DEFAULT_MAX_APPROVAL_AGE,
    current_remediation_plan_hash: str | None = None,
) -> SoakEvidenceBundle:
    """Aggregate already-created offline evidence without probing live state.

    File inputs must resolve inside ``allowed_roots``. When ``assembled_at`` is
    explicit, approval timestamps are checked against it and
    ``max_approval_age`` (24 hours by default). Callers should provide
    ``current_remediation_plan_hash``; legacy omission remains callable but is
    conservatively ``not_ready`` because plan drift cannot be verified. Missing
    or damaged sources produce an incomplete bundle instead of permission to
    continue. Unsafe paths and sensitive fields are rejected. The result is
    evidence only and every execution, scheduler, pre-soak, and 24-hour-soak
    authorization remains false.
    """

    roots = _resolve_allowed_roots(allowed_roots)
    explicit_assembled_at = _explicit_datetime(
        assembled_at, "assembled_at"
    )
    approval_age_limit = _positive_timedelta(
        max_approval_age, "max_approval_age"
    )
    current_plan_hash = (
        None
        if current_remediation_plan_hash is None
        else _hash_text(
            current_remediation_plan_hash,
            "current_remediation_plan_hash",
        )
    )
    readiness_source, readiness_payload = _load_readiness(readiness, roots)
    derived_alert_ids = _required_alert_ids(
        ack_required_alert_ids, readiness_payload
    )

    sources = {
        "baseline": _load_baseline(baseline, roots),
        "ack": _load_ack(ack, roots, derived_alert_ids),
        "scheduler": _load_scheduler(
            scheduler_evidence, roots, scheduler_expected
        ),
        "remediation_approval": _load_approval(
            remediation_approval,
            roots,
            assembled_at=explicit_assembled_at,
            max_approval_age=approval_age_limit,
            current_plan_hash=current_plan_hash,
        ),
        "readiness": readiness_source,
    }
    gaps = tuple(
        sorted(
            {
                f"{name}: {gap}"
                for name, source in sources.items()
                for gap in source.gaps
            }
        )
    )
    if any(source.status in {"missing", "invalid"} for source in sources.values()):
        status = "incomplete"
    elif gaps:
        status = "not_ready"
    else:
        status = "evidence_complete"

    time_value = (
        explicit_assembled_at.isoformat(timespec="seconds")
        if explicit_assembled_at is not None
        else None
    )
    if time_value is None:
        all_times = [
            item
            for source in sources.values()
            for item in source.times
        ]
        time_value = max(all_times, default=None)

    safety = {
        "execution_authorized": False,
        "pre_soak_start_authorized": False,
        "soak_24h_start_authorized": False,
        "scheduler_start_authorized": False,
        "statement": (
            "This deterministic offline bundle records evidence only and never "
            "authorizes execution, collection, scheduler start, pre-soak, or "
            "24-hour soak."
        ),
    }
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "manifest_kind": MANIFEST_KIND,
        "status": status,
        "assembled_at": time_value,
        "sources": {
            name: source.as_dict()
            for name, source in sorted(sources.items())
        },
        "gaps": list(gaps),
        "safety": safety,
    }
    content_hash = _sha256(unsigned)
    bundle_id = f"pre-soak-evidence-{content_hash[:16]}"
    signed = {"bundle_id": bundle_id, **unsigned}
    manifest_hash = _sha256(signed)
    return SoakEvidenceBundle(
        schema_version=SCHEMA_VERSION,
        manifest_kind=MANIFEST_KIND,
        bundle_id=bundle_id,
        status=status,
        assembled_at=time_value,
        sources=sources,
        gaps=gaps,
        safety=safety,
        manifest_hash=manifest_hash,
    )


def validate_soak_evidence_bundle(
    value: SoakEvidenceBundle | Mapping[str, Any],
) -> SoakEvidenceBundle:
    """Verify a bundle's schema, deterministic identifiers, and safety bits."""

    payload = value.as_dict() if isinstance(value, SoakEvidenceBundle) else value
    if not isinstance(payload, Mapping):
        raise SoakEvidenceBundleIntegrityError("bundle must be a JSON object")
    _reject_sensitive_fields(payload)
    if set(payload) != BUNDLE_FIELDS:
        raise SoakEvidenceBundleIntegrityError(
            "bundle fields are incomplete or unknown"
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SoakEvidenceBundleIntegrityError("unsupported bundle schema")
    if payload.get("manifest_kind") != MANIFEST_KIND:
        raise SoakEvidenceBundleIntegrityError("unexpected bundle kind")
    if payload.get("status") not in {
        "incomplete",
        "not_ready",
        "evidence_complete",
    }:
        raise SoakEvidenceBundleIntegrityError("invalid bundle status")
    safety = payload.get("safety")
    if not isinstance(safety, Mapping) or set(safety) != SAFETY_FIELDS:
        raise SoakEvidenceBundleIntegrityError("invalid bundle safety fields")
    if any(safety.get(field) is not False for field in SAFETY_FIELDS if field != "statement"):
        raise SoakEvidenceBundleIntegrityError(
            "bundle safety declaration must never authorize an action"
        )

    parsed_sources = _parse_stored_sources(payload.get("sources"))
    gaps = _text_tuple(payload.get("gaps"), "gaps")
    unsigned = dict(payload)
    supplied_hash = _hash_text(unsigned.pop("manifest_hash"), "manifest_hash")
    if supplied_hash != _sha256(unsigned):
        raise SoakEvidenceBundleIntegrityError(
            "bundle manifest hash does not match"
        )
    content = dict(unsigned)
    supplied_id = _required_text(content.pop("bundle_id"), "bundle_id")
    expected_id = f"pre-soak-evidence-{_sha256(content)[:16]}"
    if supplied_id != expected_id:
        raise SoakEvidenceBundleIntegrityError(
            "bundle_id does not match bundle content"
        )
    return SoakEvidenceBundle(
        schema_version=SCHEMA_VERSION,
        manifest_kind=MANIFEST_KIND,
        bundle_id=supplied_id,
        status=str(payload["status"]),
        assembled_at=_normalise_datetime(payload.get("assembled_at")),
        sources=parsed_sources,
        gaps=gaps,
        safety=dict(safety),
        manifest_hash=supplied_hash,
    )


def write_soak_evidence_bundle(
    path: str | Path,
    bundle: SoakEvidenceBundle,
    *,
    allowed_roots: Sequence[str | Path],
) -> Path:
    """Write canonical JSON only inside an explicit caller-owned root."""

    roots = _resolve_allowed_roots(allowed_roots)
    target = _resolve_output_path(path, roots)
    verified = validate_soak_evidence_bundle(bundle)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(verified.to_json(), encoding="utf-8", newline="\n")
    return target


def read_soak_evidence_bundle(
    path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
) -> SoakEvidenceBundle:
    """Read canonical JSON and fail closed on traversal, damage, or tampering."""

    roots = _resolve_allowed_roots(allowed_roots)
    source = _resolve_existing_path(path, roots)
    try:
        payload = json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, ValueError) as exc:
        raise SoakEvidenceBundleIntegrityError(
            "cannot read evidence bundle"
        ) from exc
    return validate_soak_evidence_bundle(payload)


def _load_baseline(
    value: SoakBaselineManifest | Mapping[str, Any] | str | Path | None,
    roots: tuple[Path, ...],
) -> EvidenceSource:
    if value is None:
        return _missing_source("baseline")
    try:
        if _is_path(value):
            path = _resolve_existing_path(value, roots)
            manifest = read_baseline_manifest(
                path, allowed_roots=roots, verify_files=False
            )
            observed_root = Path(
                manifest.sources["observed"]["project_root"]
            ).expanduser().resolve(strict=False)
            _require_within_roots(observed_root, roots)
            manifest = validate_baseline_manifest(
                manifest, verify_files=True
            )
            source_hash = _hash_file(path)
            source_kind = "file"
        else:
            payload = _object_mapping(value, "baseline")
            _reject_sensitive_fields(payload)
            manifest = validate_baseline_manifest(payload, verify_files=False)
            source_hash = _sha256(payload)
            source_kind = "object"
        gaps = []
        if not manifest.baseline_complete:
            gaps.append("baseline is not complete")
        if _has_true_authorization(manifest.as_dict()):
            gaps.append("baseline contains a true authorization field")
        return EvidenceSource(
            name="baseline",
            source_kind=source_kind,
            status="valid" if not gaps else "invalid",
            source_hash=source_hash,
            times=(),
            gaps=tuple(gaps),
            details={
                "baseline_id": manifest.baseline_id,
                "manifest_hash": manifest.manifest_hash,
                "baseline_complete": manifest.baseline_complete,
            },
        )
    except SoakEvidenceBundlePathError:
        raise
    except SoakEvidenceBundleSensitiveFieldError:
        raise
    except Exception:
        return _invalid_source("baseline", "source could not be verified")


def _load_ack(
    value: AckReadiness | Mapping[str, Any] | str | Path | None,
    roots: tuple[Path, ...],
    required_alert_ids: tuple[str, ...],
) -> EvidenceSource:
    if value is None:
        return _missing_source("ack")
    try:
        times: tuple[str, ...] = ()
        if _is_path(value):
            path = _resolve_existing_path(value, roots)
            records = read_soak_acks(path, allowed_roots=roots)
            result = evaluate_ack_readiness(
                path,
                allowed_roots=roots,
                required_alert_ids=required_alert_ids,
            )
            payload = result.as_dict()
            source_hash = _hash_file(path)
            source_kind = "file"
            times = tuple(sorted({record.decided_at for record in records}))
        else:
            payload = _object_mapping(value, "ack")
            _reject_sensitive_fields(payload)
            source_hash = _sha256(payload)
            source_kind = "object"
        ready = payload.get("ready") is True
        missing = _text_tuple(payload.get("missing_alert_ids", ()), "missing_alert_ids")
        unresolved = _text_tuple(
            payload.get("unresolved_alert_ids", ()), "unresolved_alert_ids"
        )
        integrity_error = payload.get("integrity_error")
        gaps = []
        if not required_alert_ids:
            gaps.append("required alert ids are missing")
        if integrity_error:
            gaps.append("ACK integrity is not verified")
        if missing:
            gaps.append(f"{len(missing)} required alert ACK(s) are missing")
        if unresolved:
            gaps.append(f"{len(unresolved)} alert ACK(s) are unresolved")
        if not ready:
            gaps.append("ACK readiness is false")
        return EvidenceSource(
            name="ack",
            source_kind=source_kind,
            status="valid",
            source_hash=source_hash,
            times=times,
            gaps=tuple(sorted(set(gaps))),
            details={
                "ready": ready,
                "required_alert_count": len(required_alert_ids),
                "missing_alert_count": len(missing),
                "unresolved_alert_count": len(unresolved),
                "integrity_ok": not bool(integrity_error),
            },
        )
    except SoakEvidenceBundlePathError:
        raise
    except SoakEvidenceBundleSensitiveFieldError:
        raise
    except Exception:
        return _invalid_source("ack", "source could not be verified")


def _load_scheduler(
    value: SchedulerEvidenceReport | Mapping[str, Any] | str | Path | None,
    roots: tuple[Path, ...],
    expected: Mapping[str, int | Sequence[str]] | None,
) -> EvidenceSource:
    if value is None:
        return _missing_source("scheduler")
    try:
        expected_payload = _normalise_scheduler_expected(expected)
        times: tuple[str, ...] = ()
        if _is_path(value):
            path = _resolve_existing_path(value, roots)
            records = read_scheduler_evidence(path, allowed_roots=roots)
            report = evaluate_scheduler_evidence(
                path,
                allowed_roots=roots,
                expected_due_points=expected_payload,
            )
            payload = report.as_dict()
            source_hash = _hash_file(path)
            source_kind = "file"
            times = tuple(
                sorted(
                    {
                        item
                        for record in records
                        for item in (
                            record.scheduled_at,
                            record.started_at,
                            record.finished_at,
                        )
                    }
                )
            )
        else:
            payload = _object_mapping(value, "scheduler_evidence")
            _reject_sensitive_fields(payload)
            source_hash = _sha256(payload)
            source_kind = "object"
        integrity_ok = payload.get("ledger_integrity_ok") is True
        ready = payload.get("ready") is True
        stages = payload.get("stages")
        if not isinstance(stages, Mapping):
            raise SoakEvidenceBundleError("scheduler stages must be an object")
        gaps = []
        if not expected_payload:
            gaps.append("scheduler expected due points are missing")
        if not integrity_ok:
            gaps.append("scheduler evidence integrity is not verified")
        if not ready:
            gaps.append("scheduler evidence readiness is false")
        for stage, expectation in expected_payload.items():
            summary = stages.get(stage)
            if not isinstance(summary, Mapping):
                gaps.append(f"scheduler stage {stage} is missing")
                continue
            expected_count = (
                expectation if isinstance(expectation, int) else len(expectation)
            )
            if summary.get("expected_due_point_count") != expected_count:
                gaps.append(f"scheduler stage {stage} expected count mismatches")
            if summary.get("ready_for_gate_evaluation") is not True:
                gaps.append(f"scheduler stage {stage} is not gate-ready")
        return EvidenceSource(
            name="scheduler",
            source_kind=source_kind,
            status="valid",
            source_hash=source_hash,
            times=times,
            gaps=tuple(sorted(set(gaps))),
            details={
                "ready": ready,
                "integrity_ok": integrity_ok,
                "record_count": _non_negative_int(
                    payload.get("record_count", 0), "record_count"
                ),
                "expected_hash": _sha256(expected_payload),
                "expected_stages": sorted(expected_payload),
            },
        )
    except SoakEvidenceBundlePathError:
        raise
    except SoakEvidenceBundleSensitiveFieldError:
        raise
    except Exception:
        return _invalid_source("scheduler", "source could not be verified")


def _load_approval(
    value: RemediationApprovalManifest
    | Mapping[str, Any]
    | str
    | Path
    | None,
    roots: tuple[Path, ...],
    *,
    assembled_at: datetime | None,
    max_approval_age: timedelta,
    current_plan_hash: str | None,
) -> EvidenceSource:
    if value is None:
        return _missing_source("remediation_approval")
    try:
        if _is_path(value):
            path = _resolve_existing_path(value, roots)
            manifest = read_approval_manifest(path)
            payload = manifest.as_dict()
            source_hash = _hash_file(path)
            source_kind = "file"
        else:
            payload = _object_mapping(value, "remediation_approval")
            _reject_sensitive_fields(payload)
            manifest = _validate_approval_mapping(payload)
            source_hash = _sha256(payload)
            source_kind = "object"
        gaps = []
        invalid_time = False
        source_generated_at = _parse_aware_datetime(
            manifest.source_generated_at
        )
        reviewed_at = _parse_aware_datetime(manifest.reviewed_at)
        if source_generated_at is None:
            invalid_time = True
            gaps.append("remediation source_generated_at is missing or invalid")
        if reviewed_at is None:
            invalid_time = True
            gaps.append("remediation reviewed_at is missing or invalid")
        if (
            source_generated_at is not None
            and reviewed_at is not None
            and reviewed_at < source_generated_at
        ):
            invalid_time = True
            gaps.append("remediation approval predates its source plan")
        if assembled_at is not None and reviewed_at is not None:
            if reviewed_at > assembled_at:
                gaps.append(
                    "remediation approval reviewed_at is in the future "
                    "relative to assembled_at"
                )
            elif assembled_at - reviewed_at > max_approval_age:
                gaps.append(
                    "remediation approval is expired because its age exceeds "
                    f"max_approval_age={int(max_approval_age.total_seconds())}s"
                )
        if (
            assembled_at is not None
            and source_generated_at is not None
            and source_generated_at > assembled_at
        ):
            gaps.append(
                "remediation source plan time is in the future relative "
                "to assembled_at"
            )
        if current_plan_hash is None:
            gaps.append(
                "current remediation plan hash is missing; plan drift "
                "cannot be verified"
            )
        elif current_plan_hash != manifest.source_plan_hash:
            gaps.append(
                "remediation plan drift detected: current plan hash does "
                "not match approval source_plan_hash"
            )
        if not manifest.valid:
            gaps.append("remediation approval contains issues")
        if not manifest.planned_approved:
            gaps.append("remediation plan is not approved")
        if manifest.execution_status != "not_executed":
            gaps.append("remediation execution status is unsafe")
        if manifest.authorizes_execution:
            gaps.append("remediation approval authorizes execution")
        return EvidenceSource(
            name="remediation_approval",
            source_kind=source_kind,
            status=(
                "invalid"
                if manifest.authorizes_execution or invalid_time
                else "valid"
            ),
            source_hash=source_hash,
            times=tuple(
                sorted(
                    {
                        item
                        for item in (
                            manifest.source_generated_at,
                            manifest.reviewed_at,
                        )
                        if _normalise_datetime(item) is not None
                    }
                )
            ),
            gaps=tuple(gaps),
            details={
                "manifest_id": manifest.manifest_id,
                "manifest_hash": manifest.manifest_hash,
                "plan_approval_status": manifest.plan_approval_status,
                "execution_status": manifest.execution_status,
                "authorizes_execution": False,
                "issue_count": len(manifest.issues),
                "source_plan_hash": manifest.source_plan_hash,
                "current_plan_hash": current_plan_hash,
                "plan_hash_matches": (
                    current_plan_hash == manifest.source_plan_hash
                    if current_plan_hash is not None
                    else False
                ),
                "freshness_checked": assembled_at is not None,
                "max_approval_age_seconds": int(
                    max_approval_age.total_seconds()
                ),
            },
        )
    except SoakEvidenceBundlePathError:
        raise
    except SoakEvidenceBundleSensitiveFieldError:
        raise
    except Exception:
        return _invalid_source(
            "remediation_approval", "source could not be verified"
        )


def _load_readiness(
    value: SoakReadinessReport | Mapping[str, Any] | str | Path | None,
    roots: tuple[Path, ...],
) -> tuple[EvidenceSource, Mapping[str, Any] | None]:
    if value is None:
        return _missing_source("readiness"), None
    try:
        if _is_path(value):
            path = _resolve_existing_path(value, roots)
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_json_constant,
            )
            source_hash = _hash_file(path)
            source_kind = "file"
        else:
            payload = _object_mapping(value, "readiness")
            source_hash = _sha256(payload)
            source_kind = "object"
        _reject_sensitive_fields(payload)
        if not isinstance(payload.get("summary"), Mapping):
            raise SoakEvidenceBundleError("readiness summary must be an object")
        if not isinstance(payload.get("gates"), Mapping):
            raise SoakEvidenceBundleError("readiness gates must be an object")
        target = _choice(
            payload.get("target"),
            {"pre_soak", "24h_soak", "expansion"},
            "readiness.target",
        )
        if not isinstance(payload.get("ready_for_pre_soak"), bool):
            raise SoakEvidenceBundleError(
                "readiness.ready_for_pre_soak must be boolean"
            )
        if not isinstance(payload.get("ready_for_24h_soak"), bool):
            raise SoakEvidenceBundleError(
                "readiness.ready_for_24h_soak must be boolean"
            )
        gate_statuses = {}
        for name in ("G0", "G1", "G2", "G3", "G4"):
            gate = payload["gates"].get(name)
            if not isinstance(gate, Mapping):
                raise SoakEvidenceBundleError(
                    f"readiness gate {name} must be an object"
                )
            gate_statuses[name] = _choice(
                gate.get("status"),
                {
                    "passed",
                    "failed",
                    "insufficient_evidence",
                    "not_reached",
                    "eligible_for_evaluation",
                },
                f"readiness.gates.{name}.status",
            )
        ready_pre = payload["ready_for_pre_soak"]
        ready_24h = payload["ready_for_24h_soak"]
        expected_ready_pre = all(
            gate_statuses[name] == "passed"
            for name in ("G0", "G1", "G2", "G3")
        )
        expected_ready_24h = all(
            gate_statuses[name] == "passed"
            for name in ("G0", "G1", "G2", "G3", "G4")
        )
        gaps = []
        readiness_inconsistent = False
        if ready_pre != expected_ready_pre:
            readiness_inconsistent = True
            gaps.append(
                "ready_for_pre_soak contradicts G0-G3 gate statuses"
            )
        if ready_24h != expected_ready_24h:
            readiness_inconsistent = True
            gaps.append(
                "ready_for_24h_soak contradicts G0-G4 gate statuses"
            )
        if target == "pre_soak" and not ready_pre:
            gaps.append("readiness report is not ready for pre-soak evaluation")
        if target in {"24h_soak", "expansion"} and not ready_24h:
            gaps.append("readiness report is not ready for 24-hour soak evaluation")
        if _has_true_authorization(payload):
            gaps.append("readiness contains a true authorization field")
        generated_at = _normalise_datetime(payload.get("generated_at"))
        if generated_at is None:
            gaps.append("readiness generated_at is missing or invalid")
        return (
            EvidenceSource(
                name="readiness",
                source_kind=source_kind,
                status=(
                    "invalid"
                    if _has_true_authorization(payload)
                    or readiness_inconsistent
                    else "valid"
                ),
                source_hash=source_hash,
                times=(generated_at,) if generated_at else (),
                gaps=tuple(gaps),
                details={
                    "target": target,
                    "evidence_kind": str(payload.get("evidence_kind", "")),
                    "ready_for_pre_soak": ready_pre,
                    "ready_for_24h_soak": ready_24h,
                    "gate_statuses": gate_statuses,
                },
            ),
            payload,
        )
    except SoakEvidenceBundlePathError:
        raise
    except SoakEvidenceBundleSensitiveFieldError:
        raise
    except Exception:
        return (
            _invalid_source("readiness", "source could not be verified"),
            None,
        )


def _validate_approval_mapping(
    payload: Mapping[str, Any],
) -> RemediationApprovalManifest:
    required = {
        "schema_version",
        "manifest_id",
        "source_plan_hash",
        "source_generated_at",
        "reviewed_at",
        "reviewer",
        "requested_decision",
        "plan_approval_status",
        "execution_status",
        "authorizes_execution",
        "policy",
        "selected_batches",
        "issues",
        "manifest_hash",
    }
    if set(payload) != required:
        raise SoakEvidenceBundleError("approval fields are incomplete or unknown")
    hashed = dict(payload)
    supplied_hash = _hash_text(hashed.pop("manifest_hash"), "manifest_hash")
    if supplied_hash != _sha256(hashed):
        raise SoakEvidenceBundleIntegrityError(
            "approval manifest hash does not match"
        )
    # The existing reader is the authoritative structural validator. Recreate
    # its immutable object without writing a temporary file.
    from .remediation_approval import (
        ApprovalIssue,
        ApprovalPolicy,
        SelectedBatch,
        SelectedItem,
    )

    policy = payload["policy"]
    manifest = RemediationApprovalManifest(
        schema_version=int(payload["schema_version"]),
        manifest_id=str(payload["manifest_id"]),
        source_plan_hash=str(payload["source_plan_hash"]),
        source_generated_at=str(payload["source_generated_at"]),
        reviewed_at=str(payload["reviewed_at"]),
        reviewer=str(payload["reviewer"]),
        requested_decision=str(payload["requested_decision"]),
        plan_approval_status=str(payload["plan_approval_status"]),
        execution_status=str(payload["execution_status"]),
        authorizes_execution=payload["authorizes_execution"] is True,
        policy=ApprovalPolicy(
            per_batch_limit=int(policy["per_batch_limit"]),
            hourly_visit_limit=int(policy["hourly_visit_limit"]),
            quarantine_product_ids=frozenset(
                int(item) for item in policy["quarantine_product_ids"]
            ),
            low_follower_stop_product_ids=frozenset(
                int(item) for item in policy["low_follower_stop_product_ids"]
            ),
        ),
        selected_batches=tuple(
            SelectedBatch(
                batch_id=str(batch["batch_id"]),
                stage=str(batch["stage"]),
                hour_window=int(batch["hour_window"]),
                items=tuple(
                    SelectedItem(
                        product_id=int(item["product_id"]),
                        status=str(item["status"]),
                        stage=str(item["stage"]),
                        actions=tuple(str(item) for item in item["actions"]),
                        required_before=tuple(
                            str(item) for item in item["required_before"]
                        ),
                    )
                    for item in batch["items"]
                ),
            )
            for batch in payload["selected_batches"]
        ),
        issues=tuple(
            ApprovalIssue(
                code=str(item["code"]),
                path=str(item["path"]),
                message=str(item["message"]),
            )
            for item in payload["issues"]
        ),
        manifest_hash=supplied_hash,
    )
    if manifest.schema_version != 1:
        raise SoakEvidenceBundleError("unsupported approval schema")
    if manifest.execution_status != "not_executed":
        raise SoakEvidenceBundleError("approval execution status is unsafe")
    return manifest


def _required_alert_ids(
    explicit: Iterable[str] | None,
    readiness: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if explicit is not None:
        return tuple(sorted({_required_text(item, "alert_id") for item in explicit}))
    if readiness is None:
        return ()
    summary = readiness.get("summary")
    if not isinstance(summary, Mapping):
        return ()
    value = summary.get("ack_required_alert_ids", ())
    try:
        return tuple(sorted(set(_text_tuple(value, "ack_required_alert_ids"))))
    except SoakEvidenceBundleError:
        return ()


def _normalise_scheduler_expected(
    value: Mapping[str, int | Sequence[str]] | None,
) -> dict[str, int | list[str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SoakEvidenceBundleError("scheduler_expected must be an object")
    result: dict[str, int | list[str]] = {}
    for raw_stage, raw_expected in sorted(value.items()):
        stage = _choice(raw_stage, {"G2", "G4"}, "scheduler stage")
        if isinstance(raw_expected, bool):
            raise SoakEvidenceBundleError("scheduler expected count is invalid")
        if isinstance(raw_expected, int):
            if raw_expected <= 0:
                raise SoakEvidenceBundleError(
                    "scheduler expected count must be positive"
                )
            result[stage] = raw_expected
            continue
        if isinstance(raw_expected, (str, bytes)) or not isinstance(
            raw_expected, Sequence
        ):
            raise SoakEvidenceBundleError(
                "scheduler expected ids must be a sequence"
            )
        identifiers = sorted(
            {_required_text(item, "due_point_id") for item in raw_expected}
        )
        if not identifiers:
            raise SoakEvidenceBundleError(
                "scheduler expected ids must not be empty"
            )
        result[stage] = identifiers
    return result


def _parse_stored_sources(value: Any) -> dict[str, EvidenceSource]:
    if not isinstance(value, Mapping) or set(value) != set(SOURCE_NAMES):
        raise SoakEvidenceBundleIntegrityError("invalid bundle sources")
    result: dict[str, EvidenceSource] = {}
    expected_fields = {
        "name",
        "source_kind",
        "status",
        "source_hash",
        "times",
        "gaps",
        "details",
    }
    for name in SOURCE_NAMES:
        payload = value[name]
        if not isinstance(payload, Mapping) or set(payload) != expected_fields:
            raise SoakEvidenceBundleIntegrityError(
                f"invalid stored source {name}"
            )
        if payload.get("name") != name:
            raise SoakEvidenceBundleIntegrityError(
                f"stored source name mismatch for {name}"
            )
        if payload.get("source_kind") not in {"object", "file", "missing"}:
            raise SoakEvidenceBundleIntegrityError(
                f"invalid source kind for {name}"
            )
        if payload.get("status") not in {"valid", "invalid", "missing"}:
            raise SoakEvidenceBundleIntegrityError(
                f"invalid source status for {name}"
            )
        details = payload.get("details")
        if not isinstance(details, Mapping):
            raise SoakEvidenceBundleIntegrityError(
                f"invalid source details for {name}"
            )
        source_hash = payload.get("source_hash")
        if source_hash is not None:
            source_hash = _hash_text(source_hash, f"{name}.source_hash")
        result[name] = EvidenceSource(
            name=name,
            source_kind=str(payload["source_kind"]),
            status=str(payload["status"]),
            source_hash=source_hash,
            times=_text_tuple(payload.get("times"), f"{name}.times"),
            gaps=_text_tuple(payload.get("gaps"), f"{name}.gaps"),
            details=_jsonable(details),
        )
    return result


def _missing_source(name: str) -> EvidenceSource:
    return EvidenceSource(
        name=name,
        source_kind="missing",
        status="missing",
        source_hash=None,
        times=(),
        gaps=("source is missing",),
        details={},
    )


def _invalid_source(name: str, gap: str) -> EvidenceSource:
    return EvidenceSource(
        name=name,
        source_kind="missing",
        status="invalid",
        source_hash=None,
        times=(),
        gaps=(gap,),
        details={},
    )


def _object_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if hasattr(value, "as_dict") and callable(value.as_dict):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise SoakEvidenceBundleError(f"{label} must be an object or safe path")
    return _jsonable(value)


def _has_true_authorization(value: Any) -> bool:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            if any(marker in key for marker in AUTHORIZATION_FIELD_MARKERS):
                if child is not False:
                    return True
            if _has_true_authorization(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_true_authorization(item) for item in value)
    return False


def _reject_sensitive_fields(value: Any, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            if any(marker in key for marker in SENSITIVE_FIELD_MARKERS):
                raise SoakEvidenceBundleSensitiveFieldError(
                    f"sensitive field is not allowed at {path}.{raw_key}"
                )
            _reject_sensitive_fields(child, f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive_fields(child, f"{path}[{index}]")


def _resolve_allowed_roots(
    allowed_roots: Sequence[str | Path],
) -> tuple[Path, ...]:
    roots = []
    for value in allowed_roots:
        path = Path(value).expanduser().resolve(strict=False)
        if not path.exists() or not path.is_dir():
            raise SoakEvidenceBundlePathError(
                "allowed root must be an existing directory"
            )
        if path not in roots:
            roots.append(path)
    return tuple(roots)


def _resolve_existing_path(
    path: str | Path,
    roots: Sequence[Path],
) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    _require_within_roots(candidate, roots)
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError("evidence source does not exist")
    return candidate.resolve(strict=True)


def _resolve_output_path(path: str | Path, roots: Sequence[Path]) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    _require_within_roots(candidate, roots)
    return candidate


def _require_within_roots(path: Path, roots: Sequence[Path]) -> None:
    if not roots:
        raise SoakEvidenceBundlePathError(
            "file inputs require at least one explicit allowed root"
        )
    if not any(_is_relative_to(path, root) for root in roots):
        raise SoakEvidenceBundlePathError(
            "path resolves outside the explicit allowed roots"
        )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_path(value: Any) -> bool:
    return isinstance(value, (str, Path))


def _normalise_datetime(value: datetime | str | None) -> str | None:
    parsed = _parse_aware_datetime(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="seconds")


def _parse_aware_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _explicit_datetime(
    value: datetime | str | None,
    label: str,
) -> datetime | None:
    if value is None:
        return None
    parsed = _parse_aware_datetime(value)
    if parsed is None:
        raise SoakEvidenceBundleError(
            f"{label} must be an offset-aware ISO-8601 datetime"
        )
    return parsed


def _positive_timedelta(value: Any, label: str) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise SoakEvidenceBundleError(
            f"{label} must be a positive datetime.timedelta"
        )
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SoakEvidenceBundleError(f"{label} must be non-empty text")
    return value.strip()


def _text_tuple(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise SoakEvidenceBundleError(f"{label} must be a list")
    return tuple(_required_text(item, label) for item in value)


def _choice(value: Any, allowed: set[str], label: str) -> str:
    text = _required_text(value, label)
    if text not in allowed:
        raise SoakEvidenceBundleError(f"{label} is invalid")
    return text


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SoakEvidenceBundleError(f"{label} must be a non-negative integer")
    return value


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_text(value: Any, label: str) -> str:
    text = _required_text(value, label).lower()
    if len(text) != 64 or any(item not in "0123456789abcdef" for item in text):
        raise SoakEvidenceBundleError(f"{label} must be a SHA-256 hex digest")
    return text


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SoakEvidenceBundleError(
        f"unsupported value type: {type(value).__name__}"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")
