from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
DECISIONS = {"acknowledge", "reject", "defer"}
ALERT_KINDS = {"quality", "digest", "critical"}
SENSITIVE_FIELD_MARKERS = (
    "credential",
    "credentials",
    "cookie",
    "cookies",
    "password",
    "passwd",
    "secret",
    "token",
)
RECORD_FIELDS = {
    "schema_version",
    "sequence",
    "record_id",
    "alert_id",
    "alert_kind",
    "actor",
    "decided_at",
    "decision",
    "evidence_path",
    "note",
    "previous_hash",
    "record_hash",
}


class SoakAckError(ValueError):
    """Base class for rejected ACK records or unreadable ACK ledgers."""


class SoakAckConflictError(SoakAckError):
    """Raised when a record id is reused with different content."""


class SoakAckIntegrityError(SoakAckError):
    """Raised when an existing append-only ledger cannot be verified."""


@dataclass(frozen=True)
class SoakAckRecord:
    schema_version: int
    sequence: int
    record_id: str
    alert_id: str
    alert_kind: str
    actor: str
    decided_at: str
    decision: str
    evidence_path: str
    note: str
    previous_hash: str | None
    record_hash: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AckReadiness:
    ready: bool
    required_alert_ids: tuple[str, ...]
    acknowledged_alert_ids: tuple[str, ...]
    missing_alert_ids: tuple[str, ...]
    unresolved_alert_ids: tuple[str, ...]
    latest_decisions: Mapping[str, str]
    integrity_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "required_alert_ids": list(self.required_alert_ids),
            "acknowledged_alert_ids": list(self.acknowledged_alert_ids),
            "missing_alert_ids": list(self.missing_alert_ids),
            "unresolved_alert_ids": list(self.unresolved_alert_ids),
            "latest_decisions": dict(self.latest_decisions),
            "integrity_error": self.integrity_error,
        }


def append_soak_ack(
    ledger_path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
    record_id: str,
    alert_id: str,
    alert_kind: str,
    actor: str,
    decision: str,
    evidence_path: str | Path,
    note: str = "",
    decided_at: datetime | str | None = None,
) -> SoakAckRecord:
    """Append one explicit operator decision to a local hash-chained JSONL ledger.

    The caller must supply every allowed project root. The ledger and evidence
    must resolve inside one of those roots; evidence must already exist.
    """

    roots = _resolve_allowed_roots(allowed_roots)
    ledger = _resolve_output_path(ledger_path, roots)
    evidence = _resolve_existing_path(evidence_path, roots)
    supplied_at = decided_at is not None
    normalized = {
        "record_id": _required_text(record_id, "record_id"),
        "alert_id": _required_text(alert_id, "alert_id"),
        "alert_kind": _choice(alert_kind, ALERT_KINDS, "alert_kind"),
        "actor": _required_text(actor, "actor"),
        "decided_at": _normalize_datetime(decided_at),
        "decision": _choice(decision, DECISIONS, "decision"),
        "evidence_path": str(evidence),
        "note": _text(note, "note"),
    }
    _reject_sensitive_fields(normalized)

    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ledger.with_name(f"{ledger.name}.lock")
    lock_fd = _acquire_lock(lock_path)
    try:
        existing = read_soak_acks(ledger, allowed_roots=roots)
        duplicate = next(
            (row for row in existing if row.record_id == normalized["record_id"]),
            None,
        )
        if duplicate is not None:
            if _matches_duplicate(duplicate, normalized, supplied_at=supplied_at):
                return duplicate
            raise SoakAckConflictError(
                f"record_id {normalized['record_id']!r} already has different content"
            )

        payload = {
            "schema_version": SCHEMA_VERSION,
            "sequence": len(existing) + 1,
            **normalized,
            "previous_hash": existing[-1].record_hash if existing else None,
        }
        payload["record_hash"] = _record_hash(payload)
        record = _record_from_mapping(payload)
        line = _canonical_json(record.as_dict()) + "\n"
        with ledger.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return record
    finally:
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)


def read_soak_acks(
    ledger_path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
) -> tuple[SoakAckRecord, ...]:
    """Read and fully verify a ledger in deterministic physical sequence."""

    roots = _resolve_allowed_roots(allowed_roots)
    ledger = _resolve_output_path(ledger_path, roots)
    if not ledger.exists():
        return ()
    if not ledger.is_file():
        raise SoakAckIntegrityError("ACK ledger is not a regular file")

    raw = ledger.read_text(encoding="utf-8")
    if not raw:
        return ()
    if not raw.endswith("\n"):
        raise SoakAckIntegrityError("ACK ledger has a truncated final line")

    records: list[SoakAckRecord] = []
    seen_record_ids: set[str] = set()
    previous_hash: str | None = None
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise SoakAckIntegrityError(f"blank line at ledger line {line_number}")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SoakAckIntegrityError(
                f"invalid JSON at ledger line {line_number}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise SoakAckIntegrityError(
                f"ledger line {line_number} must contain a JSON object"
            )
        _reject_sensitive_fields(payload, integrity=True)
        unknown = set(payload) - RECORD_FIELDS
        missing = RECORD_FIELDS - set(payload)
        if unknown or missing:
            raise SoakAckIntegrityError(
                f"ledger line {line_number} has invalid fields; "
                f"missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        record = _record_from_mapping(payload, integrity=True)
        if record.sequence != line_number:
            raise SoakAckIntegrityError(
                f"ledger line {line_number} has non-contiguous sequence"
            )
        if record.record_id in seen_record_ids:
            raise SoakAckIntegrityError(
                f"duplicate record_id {record.record_id!r} in ledger"
            )
        if record.previous_hash != previous_hash:
            raise SoakAckIntegrityError(
                f"ledger line {line_number} breaks the previous-hash chain"
            )
        if _record_hash(payload) != record.record_hash:
            raise SoakAckIntegrityError(
                f"ledger line {line_number} has an invalid record hash"
            )
        _resolve_existing_path(record.evidence_path, roots)
        records.append(record)
        seen_record_ids.add(record.record_id)
        previous_hash = record.record_hash
    return tuple(records)


def evaluate_ack_readiness(
    ledger_path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
    required_alert_ids: Iterable[str],
) -> AckReadiness:
    """Fail closed unless every required alert's latest decision acknowledges it."""

    required = tuple(sorted({_required_text(item, "alert_id") for item in required_alert_ids}))
    if not required:
        return AckReadiness(
            ready=False,
            required_alert_ids=(),
            acknowledged_alert_ids=(),
            missing_alert_ids=(),
            unresolved_alert_ids=(),
            latest_decisions={},
            integrity_error="no required alert ids were supplied",
        )
    try:
        records = read_soak_acks(ledger_path, allowed_roots=allowed_roots)
    except (OSError, SoakAckError) as exc:
        return AckReadiness(
            ready=False,
            required_alert_ids=required,
            acknowledged_alert_ids=(),
            missing_alert_ids=required,
            unresolved_alert_ids=(),
            latest_decisions={},
            integrity_error=str(exc),
        )

    latest = {
        record.alert_id: record.decision
        for record in records
        if record.alert_id in required
    }
    missing = tuple(item for item in required if item not in latest)
    acknowledged = tuple(
        item for item in required if latest.get(item) == "acknowledge"
    )
    unresolved = tuple(
        item
        for item in required
        if item in latest and latest[item] != "acknowledge"
    )
    return AckReadiness(
        ready=not missing and not unresolved,
        required_alert_ids=required,
        acknowledged_alert_ids=acknowledged,
        missing_alert_ids=missing,
        unresolved_alert_ids=unresolved,
        latest_decisions={item: latest[item] for item in required if item in latest},
    )


def _record_from_mapping(
    payload: Mapping[str, Any],
    *,
    integrity: bool = False,
) -> SoakAckRecord:
    error_type = SoakAckIntegrityError if integrity else SoakAckError
    try:
        schema_version = int(payload["schema_version"])
        sequence = int(payload["sequence"])
        if schema_version != SCHEMA_VERSION or sequence < 1:
            raise ValueError
        previous_hash = payload["previous_hash"]
        if previous_hash is not None:
            previous_hash = _hash_text(previous_hash, "previous_hash")
        record_hash = _hash_text(payload["record_hash"], "record_hash")
        return SoakAckRecord(
            schema_version=schema_version,
            sequence=sequence,
            record_id=_required_text(payload["record_id"], "record_id"),
            alert_id=_required_text(payload["alert_id"], "alert_id"),
            alert_kind=_choice(payload["alert_kind"], ALERT_KINDS, "alert_kind"),
            actor=_required_text(payload["actor"], "actor"),
            decided_at=_normalize_datetime(payload["decided_at"]),
            decision=_choice(payload["decision"], DECISIONS, "decision"),
            evidence_path=_required_text(payload["evidence_path"], "evidence_path"),
            note=_text(payload["note"], "note"),
            previous_hash=previous_hash,
            record_hash=record_hash,
        )
    except (KeyError, TypeError, ValueError, SoakAckError) as exc:
        raise error_type(f"invalid ACK record: {exc}") from exc


def _matches_duplicate(
    existing: SoakAckRecord,
    supplied: Mapping[str, Any],
    *,
    supplied_at: bool,
) -> bool:
    fields = (
        "record_id",
        "alert_id",
        "alert_kind",
        "actor",
        "decision",
        "evidence_path",
        "note",
    )
    if any(getattr(existing, field) != supplied[field] for field in fields):
        return False
    return not supplied_at or existing.decided_at == supplied["decided_at"]


def _resolve_allowed_roots(
    allowed_roots: Sequence[str | Path],
) -> tuple[Path, ...]:
    if not allowed_roots:
        raise SoakAckError("allowed_roots must contain at least one explicit root")
    roots: list[Path] = []
    for root in allowed_roots:
        try:
            resolved = Path(root).resolve(strict=True)
        except OSError as exc:
            raise SoakAckError(f"allowed root does not exist: {root}") from exc
        if not resolved.is_dir():
            raise SoakAckError(f"allowed root is not a directory: {resolved}")
        roots.append(resolved)
    return tuple(dict.fromkeys(roots))


def _resolve_output_path(path: str | Path, roots: Sequence[Path]) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        if len(roots) != 1:
            raise SoakAckError("relative ledger path requires exactly one allowed root")
        candidate = roots[0] / candidate
    resolved = candidate.resolve(strict=False)
    _require_within_roots(resolved, roots, "ledger_path")
    return resolved


def _resolve_existing_path(path: str | Path, roots: Sequence[Path]) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        if len(roots) != 1:
            raise SoakAckError("relative evidence path requires exactly one allowed root")
        candidate = roots[0] / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SoakAckError(f"evidence path does not exist: {candidate}") from exc
    _require_within_roots(resolved, roots, "evidence_path")
    return resolved


def _require_within_roots(path: Path, roots: Sequence[Path], label: str) -> None:
    for root in roots:
        try:
            path.relative_to(root)
            return
        except ValueError:
            continue
    raise SoakAckError(f"{label} resolves outside allowed roots: {path}")


def _acquire_lock(lock_path: Path) -> int:
    try:
        return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SoakAckConflictError(
            f"ACK ledger is locked by another writer: {lock_path}"
        ) from exc


def _normalize_datetime(value: datetime | str | None) -> str:
    if value is None:
        parsed = datetime.now().astimezone()
    elif isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise SoakAckError("decided_at must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SoakAckError("decided_at must include a timezone offset")
    return parsed.isoformat(timespec="seconds")


def _record_hash(payload: Mapping[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "record_hash"}
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _required_text(value: Any, label: str) -> str:
    text = _text(value, label).strip()
    if not text:
        raise SoakAckError(f"{label} must not be empty")
    if any(character in text for character in ("\r", "\n", "\x00")):
        raise SoakAckError(f"{label} contains forbidden control characters")
    return text


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise SoakAckError(f"{label} must be a string")
    if "\x00" in value:
        raise SoakAckError(f"{label} contains a forbidden null byte")
    return value


def _choice(value: Any, allowed: set[str], label: str) -> str:
    text = _required_text(value, label).casefold()
    if text not in allowed:
        raise SoakAckError(f"{label} must be one of {sorted(allowed)}")
    return text


def _hash_text(value: Any, label: str) -> str:
    text = _required_text(value, label).casefold()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise SoakAckError(f"{label} must be a SHA-256 hex digest")
    return text


def _reject_sensitive_fields(
    value: Any,
    *,
    integrity: bool = False,
    path: str = "record",
) -> None:
    error_type = SoakAckIntegrityError if integrity else SoakAckError
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
