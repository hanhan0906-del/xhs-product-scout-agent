from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
MANIFEST_KIND = "pre_soak_offline_baseline"
REQUIRED_RUN_PARAMETERS = frozenset(
    {"interval_seconds", "max_keywords", "max_products_per_keyword"}
)
REQUIRED_PORTS = frozenset({"8793", "8765"})
SENSITIVE_FIELD_MARKERS = frozenset(
    {
        "credential",
        "credentials",
        "cookie",
        "cookies",
        "password",
        "passwd",
        "secret",
        "token",
        "tokens",
    }
)
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "manifest_kind",
        "baseline_id",
        "status",
        "sources",
        "safety",
        "manifest_hash",
    }
)
SAFETY_FIELDS = frozenset(
    {
        "baseline_complete",
        "pre_soak_start_authorized",
        "soak_24h_start_authorized",
        "scheduler_start_authorized",
        "statement",
    }
)


class SoakBaselineError(ValueError):
    """Raised when an offline baseline input is incomplete or unsafe."""


class SoakBaselineIntegrityError(SoakBaselineError):
    """Raised when a stored baseline or an observed file was changed."""


@dataclass(frozen=True)
class BaselineFile:
    category: str
    path: str
    size_bytes: int
    sha256: str
    source: str = "observed"


@dataclass(frozen=True)
class SoakBaselineManifest:
    schema_version: int
    manifest_kind: str
    baseline_id: str
    status: str
    sources: Mapping[str, Any]
    safety: Mapping[str, Any]
    manifest_hash: str

    @property
    def baseline_complete(self) -> bool:
        return bool(self.safety["baseline_complete"])

    @property
    def authorizes_start(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    def to_json(self) -> str:
        return _canonical_json(self.as_dict()) + "\n"


def build_baseline_manifest(
    *,
    project_root: str | Path,
    code_files: Sequence[str | Path],
    config_files: Sequence[str | Path],
    database_statistics: Mapping[str, Any],
    run_parameters: Mapping[str, Any],
    port_owners: Mapping[str | int, Any],
    disk_summary: Mapping[str, Any],
    log_summary: Mapping[str, Any],
    operator: str,
    stop_entry: Mapping[str, Any],
) -> SoakBaselineManifest:
    """Build a deterministic, offline-only pre-soak baseline manifest.

    Only the explicitly listed code/config files are opened. Database, port,
    disk, log, operator, and stop-entry facts are caller supplied and are never
    probed by this module. A valid baseline is evidence only: it never
    authorizes pre-soak, a 24-hour soak, a scheduler, or any external action.
    """

    root = _resolve_project_root(project_root)
    observed_files = _observe_files(root, code_files, config_files)
    database = _required_mapping(database_statistics, "database_statistics")
    parameters = _required_mapping(run_parameters, "run_parameters")
    owners = _normalize_port_owners(port_owners)
    disk = _required_mapping(disk_summary, "disk_summary")
    logs = _required_mapping(log_summary, "log_summary")
    operator_value = _required_text(operator, "operator")
    stop = _required_mapping(stop_entry, "stop_entry")

    _reject_sensitive_fields(database, path="database_statistics")
    _reject_sensitive_fields(parameters, path="run_parameters")
    _reject_sensitive_fields(owners, path="port_owners")
    _reject_sensitive_fields(disk, path="disk_summary")
    _reject_sensitive_fields(logs, path="log_summary")
    _reject_sensitive_fields(stop, path="stop_entry")
    _validate_database(database)
    _validate_run_parameters(parameters)
    _validate_stop_entry(stop)

    file_dicts = [asdict(item) for item in observed_files]
    observed = {
        "project_root": str(root),
        "files": file_dicts,
        "file_set_sha256": _sha256(file_dicts),
    }
    caller_supplied = {
        "database_statistics": database,
        "run_parameters": parameters,
        "port_owners": owners,
        "disk_summary": disk,
        "log_summary": logs,
        "operator": operator_value,
        "stop_entry": stop,
    }
    sources = {
        "observed": observed,
        "caller_supplied": caller_supplied,
    }
    safety = {
        "baseline_complete": True,
        "pre_soak_start_authorized": False,
        "soak_24h_start_authorized": False,
        "scheduler_start_authorized": False,
        "statement": (
            "This offline baseline records evidence only and does not authorize "
            "pre-soak, 24-hour soak, scheduler start, collection, or external action."
        ),
    }
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "manifest_kind": MANIFEST_KIND,
        "status": "complete",
        "sources": sources,
        "safety": safety,
    }
    content_hash = _sha256(unsigned)
    baseline_id = f"pre-soak-baseline-{content_hash[:16]}"
    signed = {"baseline_id": baseline_id, **unsigned}
    manifest_hash = _sha256(signed)
    return SoakBaselineManifest(
        schema_version=SCHEMA_VERSION,
        manifest_kind=MANIFEST_KIND,
        baseline_id=baseline_id,
        status="complete",
        sources=sources,
        safety=safety,
        manifest_hash=manifest_hash,
    )


def validate_baseline_manifest(
    value: SoakBaselineManifest | Mapping[str, Any],
    *,
    verify_files: bool = True,
) -> SoakBaselineManifest:
    """Fail closed on schema/hash changes and optionally re-hash observed files."""

    payload = value.as_dict() if isinstance(value, SoakBaselineManifest) else value
    if not isinstance(payload, Mapping):
        raise SoakBaselineIntegrityError("baseline manifest must be a JSON object")
    _reject_sensitive_fields(payload, integrity=True, path="manifest")
    if set(payload) != MANIFEST_FIELDS:
        raise SoakBaselineIntegrityError(
            "baseline manifest fields are incomplete or unknown"
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SoakBaselineIntegrityError("unsupported baseline manifest schema")
    if payload.get("manifest_kind") != MANIFEST_KIND:
        raise SoakBaselineIntegrityError("unexpected baseline manifest kind")
    if payload.get("status") != "complete":
        raise SoakBaselineIntegrityError("baseline manifest is not complete")
    supplied_hash = _hash_text(payload.get("manifest_hash"), "manifest_hash")
    hashed = dict(payload)
    hashed.pop("manifest_hash")
    if supplied_hash != _sha256(hashed):
        raise SoakBaselineIntegrityError(
            "baseline manifest integrity hash does not match"
        )
    sources = payload.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != {
        "observed",
        "caller_supplied",
    }:
        raise SoakBaselineIntegrityError(
            "sources must distinguish observed and caller_supplied"
        )
    observed = sources["observed"]
    supplied = sources["caller_supplied"]
    if not isinstance(observed, Mapping) or set(observed) != {
        "project_root",
        "files",
        "file_set_sha256",
    }:
        raise SoakBaselineIntegrityError("observed source fields are invalid")
    if not isinstance(supplied, Mapping) or set(supplied) != {
        "database_statistics",
        "run_parameters",
        "port_owners",
        "disk_summary",
        "log_summary",
        "operator",
        "stop_entry",
    }:
        raise SoakBaselineIntegrityError("caller_supplied source fields are invalid")

    safety = payload.get("safety")
    if not isinstance(safety, Mapping) or set(safety) != SAFETY_FIELDS:
        raise SoakBaselineIntegrityError("baseline safety fields are invalid")
    if (
        safety.get("baseline_complete") is not True
        or safety.get("pre_soak_start_authorized") is not False
        or safety.get("soak_24h_start_authorized") is not False
        or safety.get("scheduler_start_authorized") is not False
    ):
        raise SoakBaselineIntegrityError(
            "baseline safety declaration must never authorize a start"
        )
    expected_id = f"pre-soak-baseline-{_sha256(_unsigned_content(payload))[:16]}"
    if payload.get("baseline_id") != expected_id:
        raise SoakBaselineIntegrityError("baseline_id does not match manifest content")

    try:
        root = _resolve_project_root(observed["project_root"])
        files = _parse_stored_files(observed["files"])
        expected_file_set_hash = _hash_text(
            observed["file_set_sha256"], "observed.file_set_sha256"
        )
        if expected_file_set_hash != _sha256([asdict(item) for item in files]):
            raise SoakBaselineIntegrityError("observed file-set hash does not match")
        database = _required_mapping(
            supplied["database_statistics"], "database_statistics"
        )
        parameters = _required_mapping(supplied["run_parameters"], "run_parameters")
        _validate_database(database, integrity=True)
        _validate_run_parameters(parameters, integrity=True)
        _normalize_port_owners(supplied["port_owners"], integrity=True)
        _required_mapping(supplied["disk_summary"], "disk_summary", integrity=True)
        _required_mapping(supplied["log_summary"], "log_summary", integrity=True)
        _required_text(supplied["operator"], "operator", integrity=True)
        stop = _required_mapping(supplied["stop_entry"], "stop_entry", integrity=True)
        _validate_stop_entry(stop, integrity=True)
        if verify_files:
            _verify_observed_files(root, files)
    except SoakBaselineIntegrityError:
        raise
    except SoakBaselineError as exc:
        raise SoakBaselineIntegrityError(str(exc)) from exc

    return SoakBaselineManifest(
        schema_version=SCHEMA_VERSION,
        manifest_kind=MANIFEST_KIND,
        baseline_id=str(payload["baseline_id"]),
        status="complete",
        sources=_jsonable(sources),
        safety=_jsonable(safety),
        manifest_hash=supplied_hash,
    )


def write_baseline_manifest(
    path: str | Path,
    manifest: SoakBaselineManifest,
    *,
    allowed_roots: Sequence[str | Path],
) -> Path:
    """Write canonical JSON only within an explicit allowed root."""

    roots = _resolve_allowed_roots(allowed_roots)
    target = _resolve_output_path(path, roots)
    validate_baseline_manifest(manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.to_json(), encoding="utf-8", newline="\n")
    return target


def read_baseline_manifest(
    path: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
    verify_files: bool = True,
) -> SoakBaselineManifest:
    """Read canonical JSON and reject tampering, unsafe paths, or stale files."""

    roots = _resolve_allowed_roots(allowed_roots)
    source = _resolve_existing_path(path, roots, "manifest_path")
    try:
        payload = json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, ValueError) as exc:
        raise SoakBaselineIntegrityError(
            f"cannot read baseline manifest: {exc}"
        ) from exc
    return validate_baseline_manifest(payload, verify_files=verify_files)


def _observe_files(
    root: Path,
    code_files: Sequence[str | Path],
    config_files: Sequence[str | Path],
) -> tuple[BaselineFile, ...]:
    if isinstance(code_files, (str, bytes)) or not code_files:
        raise SoakBaselineError("code_files must contain at least one explicit file")
    if isinstance(config_files, (str, bytes)) or not config_files:
        raise SoakBaselineError("config_files must contain at least one explicit file")
    observed: list[BaselineFile] = []
    seen: set[str] = set()
    for category, paths in (("code", code_files), ("config", config_files)):
        for index, supplied in enumerate(paths):
            resolved = _resolve_project_file(
                root, supplied, f"{category}_files[{index}]"
            )
            relative = resolved.relative_to(root).as_posix()
            if relative in seen:
                raise SoakBaselineError(f"duplicate baseline file: {relative}")
            seen.add(relative)
            observed.append(
                BaselineFile(
                    category=category,
                    path=relative,
                    size_bytes=resolved.stat().st_size,
                    sha256=_hash_file(resolved),
                )
            )
    return tuple(sorted(observed, key=lambda item: (item.category, item.path)))


def _parse_stored_files(value: Any) -> tuple[BaselineFile, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise SoakBaselineIntegrityError("observed.files must be a non-empty list")
    files: list[BaselineFile] = []
    seen: set[str] = set()
    categories: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {
            "category",
            "path",
            "size_bytes",
            "sha256",
            "source",
        }:
            raise SoakBaselineIntegrityError(
                f"observed.files[{index}] fields are invalid"
            )
        category = item["category"]
        if category not in {"code", "config"}:
            raise SoakBaselineIntegrityError("stored file category is invalid")
        relative = _required_text(
            item["path"], f"observed.files[{index}].path", integrity=True
        )
        path_value = Path(relative)
        if path_value.is_absolute() or ".." in path_value.parts:
            raise SoakBaselineIntegrityError("stored file path must be project-relative")
        size = item["size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SoakBaselineIntegrityError("stored file size is invalid")
        if item["source"] != "observed":
            raise SoakBaselineIntegrityError("stored file source must be observed")
        if relative in seen:
            raise SoakBaselineIntegrityError("stored file paths must be unique")
        seen.add(relative)
        categories.add(category)
        files.append(
            BaselineFile(
                category=category,
                path=relative,
                size_bytes=size,
                sha256=_hash_text(
                    item["sha256"], f"observed.files[{index}].sha256"
                ),
            )
        )
    if categories != {"code", "config"}:
        raise SoakBaselineIntegrityError("both code and config files are required")
    ordered = tuple(sorted(files, key=lambda item: (item.category, item.path)))
    if list(files) != list(ordered):
        raise SoakBaselineIntegrityError("observed files are not deterministically sorted")
    return ordered


def _verify_observed_files(root: Path, files: Sequence[BaselineFile]) -> None:
    for item in files:
        path = _resolve_project_file(root, item.path, f"observed file {item.path}")
        if path.stat().st_size != item.size_bytes or _hash_file(path) != item.sha256:
            raise SoakBaselineIntegrityError(
                f"observed file changed after baseline: {item.path}"
            )


def _resolve_project_root(project_root: str | Path) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
    except OSError as exc:
        raise SoakBaselineError(
            f"project_root does not exist: {project_root}"
        ) from exc
    if not root.is_dir():
        raise SoakBaselineError(f"project_root is not a directory: {root}")
    return root


def _resolve_project_file(root: Path, value: str | Path, label: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SoakBaselineError(f"{label} does not exist: {candidate}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SoakBaselineError(
            f"{label} resolves outside project_root: {resolved}"
        ) from exc
    if not resolved.is_file():
        raise SoakBaselineError(f"{label} is not a file: {resolved}")
    return resolved


def _normalize_port_owners(
    value: Any, *, integrity: bool = False
) -> dict[str, Any]:
    error_type = SoakBaselineIntegrityError if integrity else SoakBaselineError
    if not isinstance(value, Mapping):
        raise error_type("port_owners must be an object")
    normalized = {str(key): _jsonable(item) for key, item in value.items()}
    if set(normalized) != REQUIRED_PORTS:
        raise error_type("port_owners must contain exactly 8793 and 8765")
    for port in sorted(REQUIRED_PORTS):
        summary = normalized[port]
        if not isinstance(summary, Mapping) or not summary:
            raise error_type(f"port_owners.{port} must be a non-empty object")
        _required_text(
            summary.get("owner"), f"port_owners.{port}.owner", integrity=integrity
        )
    return {port: normalized[port] for port in sorted(normalized)}


def _validate_database(value: Mapping[str, Any], *, integrity: bool = False) -> None:
    error_type = SoakBaselineIntegrityError if integrity else SoakBaselineError
    if "quick_check" not in value:
        raise error_type("database_statistics.quick_check is required")
    if str(value["quick_check"]).strip().casefold() != "ok":
        raise error_type("database_statistics.quick_check must be ok")


def _validate_run_parameters(
    value: Mapping[str, Any], *, integrity: bool = False
) -> None:
    error_type = SoakBaselineIntegrityError if integrity else SoakBaselineError
    missing = REQUIRED_RUN_PARAMETERS - set(value)
    if missing:
        raise error_type(
            "run_parameters missing required fields: " + ", ".join(sorted(missing))
        )
    for key in sorted(REQUIRED_RUN_PARAMETERS):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise error_type(f"run_parameters.{key} must be a positive integer")
    if value["max_keywords"] != 1 or value["max_products_per_keyword"] != 1:
        raise error_type("pre-soak baseline requires the fixed 1 keyword x 1 product budget")


def _validate_stop_entry(value: Mapping[str, Any], *, integrity: bool = False) -> None:
    error_type = SoakBaselineIntegrityError if integrity else SoakBaselineError
    if not any(key in value for key in ("command", "path", "procedure")):
        raise error_type("stop_entry requires command, path, or procedure")
    for key in ("command", "path", "procedure"):
        if key in value:
            _required_text(
                value[key], f"stop_entry.{key}", integrity=integrity
            )


def _required_mapping(
    value: Any, label: str, *, integrity: bool = False
) -> dict[str, Any]:
    error_type = SoakBaselineIntegrityError if integrity else SoakBaselineError
    if not isinstance(value, Mapping) or not value:
        raise error_type(f"{label} must be a non-empty object")
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise error_type(f"{label} keys must be non-empty strings")
        normalized[key] = _jsonable(item, integrity=integrity)
    return dict(sorted(normalized.items()))


def _required_text(
    value: Any, label: str, *, integrity: bool = False
) -> str:
    error_type = SoakBaselineIntegrityError if integrity else SoakBaselineError
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{label} must be a non-empty string")
    text = value.strip()
    if any(character in text for character in ("\r", "\n", "\x00")):
        raise error_type(f"{label} contains forbidden control characters")
    return text


def _jsonable(value: Any, *, integrity: bool = False) -> Any:
    error_type = SoakBaselineIntegrityError if integrity else SoakBaselineError
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise error_type("non-finite JSON numbers are forbidden")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise error_type("JSON object keys must be strings")
            result[key] = _jsonable(item, integrity=integrity)
        return {key: result[key] for key in sorted(result)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, integrity=integrity) for item in value]
    raise error_type(f"value is not JSON serializable: {type(value).__name__}")


def _reject_sensitive_fields(
    value: Any,
    *,
    integrity: bool = False,
    path: str,
) -> None:
    error_type = SoakBaselineIntegrityError if integrity else SoakBaselineError
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            tokens = {token for token in normalized.split("_") if token}
            if tokens.intersection(SENSITIVE_FIELD_MARKERS):
                raise error_type(f"sensitive field is forbidden: {path}.{key}")
            _reject_sensitive_fields(
                item, integrity=integrity, path=f"{path}.{key}"
            )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_fields(
                item, integrity=integrity, path=f"{path}[{index}]"
            )


def _resolve_allowed_roots(
    allowed_roots: Sequence[str | Path],
) -> tuple[Path, ...]:
    if not allowed_roots:
        raise SoakBaselineError(
            "allowed_roots must contain at least one explicit root"
        )
    roots = tuple(dict.fromkeys(_resolve_project_root(root) for root in allowed_roots))
    return roots


def _resolve_output_path(path: str | Path, roots: Sequence[Path]) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        if len(roots) != 1:
            raise SoakBaselineError(
                "relative manifest path requires exactly one allowed root"
            )
        candidate = roots[0] / candidate
    resolved = candidate.resolve(strict=False)
    _require_within_roots(resolved, roots, "manifest_path")
    return resolved


def _resolve_existing_path(
    path: str | Path, roots: Sequence[Path], label: str
) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        if len(roots) != 1:
            raise SoakBaselineError(
                f"relative {label} requires exactly one allowed root"
            )
        candidate = roots[0] / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SoakBaselineError(f"{label} does not exist: {candidate}") from exc
    _require_within_roots(resolved, roots, label)
    if not resolved.is_file():
        raise SoakBaselineError(f"{label} is not a file: {resolved}")
    return resolved


def _require_within_roots(
    path: Path, roots: Sequence[Path], label: str
) -> None:
    for root in roots:
        try:
            path.relative_to(root)
            return
        except ValueError:
            continue
    raise SoakBaselineError(f"{label} resolves outside allowed roots: {path}")


def _unsigned_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload["schema_version"],
        "manifest_kind": payload["manifest_kind"],
        "status": payload["status"],
        "sources": payload["sources"],
        "safety": payload["safety"],
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise SoakBaselineIntegrityError(f"{label} must be a SHA-256 hex digest")
    text = value.casefold()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise SoakBaselineIntegrityError(f"{label} must be a SHA-256 hex digest")
    return text


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")
