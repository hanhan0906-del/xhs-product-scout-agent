from __future__ import annotations

import atexit
from collections import OrderedDict
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import importlib
import json
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import pickle
import tempfile
import threading
import time
import traceback
from typing import Any, Callable
import uuid


OCR_TIMEOUT_SECONDS = 60.0
OCR_CACHE_MAX_ENTRIES = 32
OCR_CACHE_MAX_BYTES = 8 * 1024 * 1024
OCR_CACHE_TTL_SECONDS = 5 * 60.0
OCR_DIAGNOSTICS_DIR_ENV = "XHS_SCOUT_OCR_DIAGNOSTICS_DIR"

_HASH_CHUNK_BYTES = 1024 * 1024
_PROCESS_JOIN_SECONDS = 2.0
_LIFECYCLE_STAGES = {
    "worker_started",
    "import_started",
    "import_done",
    "engine_init_started",
    "engine_init_done",
}


class OcrTimeoutError(TimeoutError):
    """RapidOCR did not finish before the supervised process deadline."""

    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}
        self.image_sha256 = self.diagnostics.get("image_sha256")
        self.worker_pid = self.diagnostics.get("worker_pid")
        self.last_stage = self.diagnostics.get("last_stage")
        self.stage_durations = self.diagnostics.get("stage_durations", {})
        self.exitcode = self.diagnostics.get(
            "exitcode_after_termination",
            self.diagnostics.get("worker_exitcode"),
        )
        self.evidence_path = self.diagnostics.get("evidence_path")


class OcrWorkerError(RuntimeError):
    """The supervised OCR worker failed before returning a result."""

    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}
        self.evidence_path = self.diagnostics.get("evidence_path")


def _load_rapidocr_class():
    module = importlib.import_module("rapidocr_onnxruntime")
    return module.RapidOCR


@lru_cache(maxsize=1)
def _engine():
    """Compatibility helper for direct in-process callers and focused tests."""

    return _load_rapidocr_class()()


def _extract_text_with_engine(engine, path: str) -> tuple[str, list[dict]]:
    result, _ = engine(str(path))
    if not result:
        return "", []
    lines = []
    details = []
    for box, text, confidence in result:
        lines.append(text)
        details.append({"box": box, "text": text, "confidence": float(confidence)})
    return "\n".join(lines), details


def _extract_text_in_worker(path: str) -> tuple[str, list[dict]]:
    return _extract_text_with_engine(_engine(), path)


class _EngineStageHookContext:
    def __init__(self, emit: Callable[..., None]) -> None:
        self._emit = emit
        self.job_id: str | None = None

    def emit(self, stage: str, **data: Any) -> None:
        self._emit(stage, self.job_id, **data)


class _StageCallableProxy:
    """Transparent callable proxy that only brackets an existing component."""

    __slots__ = ("_target", "_stage_prefix", "_context")

    def __init__(
        self,
        target,
        *,
        stage_prefix: str,
        context: _EngineStageHookContext,
    ) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_stage_prefix", stage_prefix)
        object.__setattr__(self, "_context", context)

    def __call__(self, *args, **kwargs):
        prefix = object.__getattribute__(self, "_stage_prefix")
        context = object.__getattribute__(self, "_context")
        target = object.__getattribute__(self, "_target")
        context.emit(f"{prefix}_started")
        try:
            result = target(*args, **kwargs)
        except BaseException as exc:
            context.emit(
                f"{prefix}_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        context.emit(f"{prefix}_done")
        return result

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_target"), name)

    def __setattr__(self, name: str, value) -> None:
        if name in self.__slots__:
            object.__setattr__(self, name, value)
            return
        setattr(object.__getattribute__(self, "_target"), name, value)


def _install_engine_stage_hooks(
    engine,
    context: _EngineStageHookContext,
) -> tuple[str, ...]:
    components = (
        ("load_img", "image_load"),
        ("text_det", "detection"),
        ("text_cls", "classification"),
        ("text_rec", "recognition"),
    )
    installed: list[str] = []
    for attribute, stage_prefix in components:
        target = getattr(engine, attribute, None)
        if target is None or not callable(target):
            raise RuntimeError(
                f"RapidOCR component is unavailable or not callable: {attribute}"
            )
        if isinstance(target, _StageCallableProxy):
            raise RuntimeError(f"RapidOCR component was already instrumented: {attribute}")
        setattr(
            engine,
            attribute,
            _StageCallableProxy(
                target,
                stage_prefix=stage_prefix,
                context=context,
            ),
        )
        installed.append(attribute)
    return tuple(installed)


def _ocr_worker_loop_impl(
    connection: Connection,
    *,
    instrument_components: bool,
    rapidocr_loader: Callable[[], Any] | None = None,
) -> None:
    """Own one RapidOCR engine and execute serialized jobs until supervised exit."""

    worker_pid = os.getpid()
    engine = None
    rapidocr_class = None
    hook_context: _EngineStageHookContext | None = None
    last_stage = "worker_started"

    def emit(stage: str, job_id: str | None, **data: Any) -> None:
        nonlocal last_stage
        last_stage = stage
        connection.send(
            {
                "kind": "stage",
                "stage": stage,
                "job_id": job_id,
                "worker_pid": worker_pid,
                "worker_monotonic": time.monotonic(),
                "wall_time": datetime.now(timezone.utc).isoformat(),
                "data": data,
            }
        )

    try:
        emit("worker_started", None)
        while True:
            try:
                command = connection.recv()
            except EOFError:
                break
            if not isinstance(command, dict):
                continue
            if command.get("kind") == "shutdown":
                break
            if command.get("kind") != "ocr":
                continue

            job_id = str(command.get("job_id") or "")
            image_path = str(command.get("path") or "")
            try:
                if engine is None:
                    emit("import_started", job_id)
                    loader = rapidocr_loader or _load_rapidocr_class
                    rapidocr_class = loader()
                    emit("import_done", job_id)
                    emit("engine_init_started", job_id)
                    engine = rapidocr_class()
                    emit("engine_init_done", job_id)
                    if instrument_components:
                        hook_context = _EngineStageHookContext(emit)
                        hook_context.job_id = job_id
                        installed = _install_engine_stage_hooks(engine, hook_context)
                        emit(
                            "engine_hooks_installed",
                            job_id,
                            components=list(installed),
                        )
                else:
                    emit("engine_reused", job_id)

                if hook_context is not None:
                    hook_context.job_id = job_id

                emit("inference_started", job_id)
                result = _extract_text_with_engine(engine, image_path)
                emit(
                    "inference_done",
                    job_id,
                    line_count=len(result[1]),
                )
                emit("serialize_started", job_id)
                payload = pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL)
                emit("serialize_done", job_id, payload_bytes=len(payload))
                connection.send(
                    {
                        "kind": "result",
                        "job_id": job_id,
                        "worker_pid": worker_pid,
                        "payload": payload,
                    }
                )
            except BaseException as exc:
                try:
                    connection.send(
                        {
                            "kind": "error",
                            "job_id": job_id,
                            "worker_pid": worker_pid,
                            "last_stage": last_stage,
                            "error": {
                                "type": type(exc).__name__,
                                "message": str(exc),
                                "traceback": traceback.format_exc(),
                            },
                        }
                    )
                except (BrokenPipeError, EOFError, OSError):
                    break
    finally:
        connection.close()


def _ocr_worker_loop(connection: Connection) -> None:
    _ocr_worker_loop_impl(connection, instrument_components=True)


@dataclass(frozen=True)
class _CacheEntry:
    payload: bytes
    expires_at: float

    @property
    def size(self) -> int:
        return len(self.payload)


class _BoundedResultCache:
    def __init__(
        self,
        *,
        max_entries: int,
        max_bytes: int,
        ttl_seconds: float,
    ) -> None:
        self.max_entries = max(0, int(max_entries))
        self.max_bytes = max(0, int(max_bytes))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._total_bytes = 0

    def _remove(self, image_sha256: str) -> None:
        entry = self._entries.pop(image_sha256, None)
        if entry is not None:
            self._total_bytes -= entry.size

    def _prune_expired(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if entry.expires_at <= now
        ]
        for key in expired:
            self._remove(key)

    def get(self, image_sha256: str, *, now: float) -> bytes | None:
        self._prune_expired(now)
        entry = self._entries.pop(image_sha256, None)
        if entry is None:
            return None
        self._entries[image_sha256] = entry
        return entry.payload

    def put(self, image_sha256: str, payload: bytes, *, now: float) -> bool:
        self._prune_expired(now)
        self._remove(image_sha256)
        if (
            self.max_entries <= 0
            or self.max_bytes <= 0
            or self.ttl_seconds <= 0
            or len(payload) > self.max_bytes
        ):
            return False
        self._entries[image_sha256] = _CacheEntry(
            payload=payload,
            expires_at=now + self.ttl_seconds,
        )
        self._total_bytes += len(payload)
        while (
            len(self._entries) > self.max_entries
            or self._total_bytes > self.max_bytes
        ):
            _, evicted = self._entries.popitem(last=False)
            self._total_bytes -= evicted.size
        return image_sha256 in self._entries

    def clear(self, image_sha256: str | None = None) -> None:
        if image_sha256 is None:
            self._entries.clear()
            self._total_bytes = 0
            return
        self._remove(image_sha256)

    def info(self) -> dict[str, int | float]:
        return {
            "entries": len(self._entries),
            "bytes": self._total_bytes,
            "max_entries": self.max_entries,
            "max_bytes": self.max_bytes,
            "ttl_seconds": self.ttl_seconds,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_durations(
    events: list[dict[str, Any]],
    *,
    call_started: float,
    finished_at: float,
) -> dict[str, float]:
    def last_time(stage: str) -> float | None:
        for event in reversed(events):
            if event.get("stage") == stage:
                value = event.get("worker_monotonic")
                if isinstance(value, (int, float)):
                    return float(value)
        return None

    durations: dict[str, float] = {
        "total_seconds": round(max(0.0, finished_at - call_started), 6)
    }
    for label, started_name, done_name in (
        ("import_seconds", "import_started", "import_done"),
        ("engine_init_seconds", "engine_init_started", "engine_init_done"),
        ("inference_seconds", "inference_started", "inference_done"),
        ("image_load_seconds", "image_load_started", "image_load_done"),
        ("detection_seconds", "detection_started", "detection_done"),
        (
            "classification_seconds",
            "classification_started",
            "classification_done",
        ),
        ("recognition_seconds", "recognition_started", "recognition_done"),
        ("serialization_seconds", "serialize_started", "serialize_done"),
    ):
        started = last_time(started_name)
        done = last_time(done_name)
        if started is not None and done is not None and done >= started:
            durations[label] = round(done - started, 6)

    if events:
        received_at = events[-1].get("received_monotonic")
        if isinstance(received_at, (int, float)):
            durations["last_stage_elapsed_seconds"] = round(
                max(0.0, finished_at - float(received_at)),
                6,
            )
    return durations


def _diagnostic_roots(
    image_path: Path,
    configured_dir: Path | None,
) -> list[Path]:
    candidates: list[Path] = []
    configured = configured_dir or (
        Path(value) if (value := os.environ.get(OCR_DIAGNOSTICS_DIR_ENV)) else None
    )
    if configured is not None:
        candidates.append(configured.expanduser())
    candidates.append(image_path.parent / ".ocr-diagnostics")
    candidates.append(Path(tempfile.gettempdir()) / "xhs-scout-ocr-diagnostics")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _persist_diagnostics(
    diagnostics: dict[str, Any],
    *,
    image_path: Path,
    configured_dir: Path | None,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    kind = str(diagnostics.get("kind") or "failure").replace("_", "-")
    image_sha256 = str(diagnostics.get("image_sha256") or "unknown")
    job_id = str(diagnostics.get("job_id") or "no-job")
    filename = f"ocr-{kind}-{timestamp}-{image_sha256[:12]}-{job_id[:12]}.json"
    serialized_at = datetime.now(timezone.utc).isoformat()

    for root in _diagnostic_roots(image_path, configured_dir):
        temporary: Path | None = None
        try:
            root.mkdir(parents=True, exist_ok=True)
            target = root / filename
            temporary = root / f".{filename}.{os.getpid()}.tmp"
            persisted = {
                **diagnostics,
                "evidence_path": str(target),
                "persisted_at": serialized_at,
                "persistence_fallback_errors": list(errors),
            }
            temporary.write_text(
                json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, target)
            return str(target), errors
        except Exception as exc:
            errors.append(f"{root}: {type(exc).__name__}: {exc}")
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
    return None, errors


WorkerTarget = Callable[[Connection], None]


def _safe_process_pid(process: multiprocessing.Process | None) -> int | None:
    if process is None:
        return None
    try:
        return process.pid
    except ValueError:
        return None


def _safe_process_exitcode(process: multiprocessing.Process | None) -> int | None:
    if process is None:
        return None
    try:
        return process.exitcode
    except ValueError:
        return None


class _OcrWorkerSupervisor:
    """Serialize OCR calls through one reusable, forcibly replaceable worker."""

    def __init__(
        self,
        *,
        worker_target: WorkerTarget = _ocr_worker_loop,
        diagnostics_dir: Path | None = None,
        cache_max_entries: int = OCR_CACHE_MAX_ENTRIES,
        cache_max_bytes: int = OCR_CACHE_MAX_BYTES,
        cache_ttl_seconds: float = OCR_CACHE_TTL_SECONDS,
    ) -> None:
        self._context = multiprocessing.get_context("spawn")
        self._worker_target = worker_target
        self._diagnostics_dir = diagnostics_dir
        self._lock = threading.Lock()
        self._process: multiprocessing.Process | None = None
        self._connection: Connection | None = None
        self._worker_lifecycle_events: list[dict[str, Any]] = []
        self._last_worker_diagnostics: dict[str, Any] | None = None
        self._cache = _BoundedResultCache(
            max_entries=cache_max_entries,
            max_bytes=cache_max_bytes,
            ttl_seconds=cache_ttl_seconds,
        )

    @property
    def worker_pid(self) -> int | None:
        return _safe_process_pid(self._process)

    @property
    def start_method(self) -> str:
        return self._context.get_start_method()

    def cache_info(self) -> dict[str, int | float]:
        with self._lock:
            return self._cache.info()

    def last_worker_diagnostics(self) -> dict[str, Any] | None:
        with self._lock:
            return copy.deepcopy(self._last_worker_diagnostics)

    def clear_cache(self, image_sha256: str | None = None) -> None:
        with self._lock:
            self._cache.clear(image_sha256)

    def _ensure_worker_locked(self) -> None:
        if (
            self._process is not None
            and self._connection is not None
            and self._process.is_alive()
        ):
            return
        if self._process is not None or self._connection is not None:
            stopped = self._stop_worker_locked(graceful=False)
            if stopped["worker_still_alive"]:
                raise RuntimeError("previous OCR worker could not be terminated")

        parent_connection, child_connection = self._context.Pipe(duplex=True)
        process = self._context.Process(
            target=self._worker_target,
            args=(child_connection,),
            name="xhs-scout-rapidocr",
            daemon=True,
        )
        try:
            process.start()
        except BaseException:
            parent_connection.close()
            child_connection.close()
            if process.is_alive():
                process.terminate()
                process.join(timeout=_PROCESS_JOIN_SECONDS)
            raise
        child_connection.close()
        self._process = process
        self._connection = parent_connection
        self._worker_lifecycle_events = []
        self._last_worker_diagnostics = None

    def _stop_worker_locked(self, *, graceful: bool) -> dict[str, Any]:
        process = self._process
        connection = self._connection
        outcome: dict[str, Any] = {
            "graceful_requested": graceful,
            "terminate_sent": False,
            "kill_sent": False,
            "exitcode_before_termination": _safe_process_exitcode(process),
            "exitcode_after_termination": None,
            "worker_still_alive": False,
            "termination_errors": [],
        }
        if process is None:
            if connection is not None:
                connection.close()
            self._connection = None
            self._worker_lifecycle_events = []
            return outcome

        if graceful and process.is_alive() and connection is not None:
            try:
                connection.send({"kind": "shutdown"})
            except (BrokenPipeError, EOFError, OSError):
                pass
            process.join(timeout=0.5)
        elif not process.is_alive():
            process.join(timeout=0.1)

        if process.is_alive():
            outcome["terminate_sent"] = True
            try:
                process.terminate()
            except (OSError, ValueError) as exc:
                outcome["termination_errors"].append(
                    f"terminate:{type(exc).__name__}:{exc}"
                )
            process.join(timeout=_PROCESS_JOIN_SECONDS)
        if process.is_alive():
            outcome["kill_sent"] = True
            try:
                process.kill()
            except (OSError, ValueError) as exc:
                outcome["termination_errors"].append(
                    f"kill:{type(exc).__name__}:{exc}"
                )
            process.join(timeout=_PROCESS_JOIN_SECONDS)

        still_alive = process.is_alive()
        outcome["worker_still_alive"] = still_alive
        outcome["exitcode_after_termination"] = _safe_process_exitcode(process)
        if connection is not None:
            connection.close()
        if not still_alive:
            try:
                process.close()
            except ValueError:
                pass
            self._process = None
        else:
            self._process = process
        self._connection = None
        self._worker_lifecycle_events = []
        return outcome

    def _record_stage(
        self,
        message: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        event = {
            "stage": message.get("stage"),
            "job_id": message.get("job_id"),
            "worker_pid": message.get("worker_pid"),
            "worker_monotonic": message.get("worker_monotonic"),
            "wall_time": message.get("wall_time"),
            "data": message.get("data") or {},
            "received_monotonic": time.monotonic(),
        }
        events.append(event)
        if event["stage"] in _LIFECYCLE_STAGES:
            self._worker_lifecycle_events.append(event)

    @staticmethod
    def _record_parent_stage(
        *,
        stage: str,
        job_id: str,
        worker_pid: int | None,
        events: list[dict[str, Any]],
    ) -> None:
        now = time.monotonic()
        events.append(
            {
                "stage": stage,
                "job_id": job_id,
                "worker_pid": worker_pid,
                "worker_monotonic": now,
                "wall_time": datetime.now(timezone.utc).isoformat(),
                "data": {"source": "parent_supervisor"},
                "received_monotonic": now,
            }
        )

    def _base_diagnostics(
        self,
        *,
        kind: str,
        reason: str,
        image_path: Path,
        image_sha256: str,
        image_size: int,
        timeout_seconds: float,
        job_id: str | None,
        worker_pid: int | None,
        events: list[dict[str, Any]],
        call_started: float,
        finished_at: float,
    ) -> dict[str, Any]:
        last_stage = events[-1]["stage"] if events else "worker_not_started"
        public_events = [
            {
                key: value
                for key, value in event.items()
                if key != "received_monotonic"
            }
            for event in events
        ]
        return {
            "schema_version": 1,
            "kind": kind,
            "reason": reason,
            "image_path": str(image_path),
            "image_sha256": image_sha256,
            "image_size_bytes": image_size,
            "timeout_seconds": timeout_seconds,
            "job_id": job_id,
            "parent_pid": os.getpid(),
            "parent_thread": threading.current_thread().name,
            "worker_pid": worker_pid,
            "worker_exitcode": _safe_process_exitcode(self._process),
            "start_method": self.start_method,
            "last_stage": last_stage,
            "stage_durations": _stage_durations(
                events,
                call_started=call_started,
                finished_at=finished_at,
            ),
            "stage_events": public_events,
            "cache": self._cache.info(),
        }

    def _persist_and_attach(
        self,
        diagnostics: dict[str, Any],
        *,
        image_path: Path,
        diagnostics_dir: Path | None,
    ) -> dict[str, Any]:
        evidence_path, persistence_errors = _persist_diagnostics(
            diagnostics,
            image_path=image_path,
            configured_dir=diagnostics_dir or self._diagnostics_dir,
        )
        diagnostics["evidence_path"] = evidence_path
        diagnostics["persistence_errors"] = persistence_errors
        return diagnostics

    def _raise_timeout_locked(
        self,
        *,
        reason: str,
        image_path: Path,
        image_sha256: str,
        image_size: int,
        timeout_seconds: float,
        job_id: str | None,
        worker_pid: int | None,
        events: list[dict[str, Any]],
        call_started: float,
        diagnostics_dir: Path | None,
        terminate_worker: bool,
    ) -> None:
        finished_at = time.monotonic()
        diagnostics = self._base_diagnostics(
            kind="timeout",
            reason=reason,
            image_path=image_path,
            image_sha256=image_sha256,
            image_size=image_size,
            timeout_seconds=timeout_seconds,
            job_id=job_id,
            worker_pid=worker_pid,
            events=events,
            call_started=call_started,
            finished_at=finished_at,
        )
        if terminate_worker:
            diagnostics.update(self._stop_worker_locked(graceful=False))
        diagnostics = self._persist_and_attach(
            diagnostics,
            image_path=image_path,
            diagnostics_dir=diagnostics_dir,
        )
        message = (
            f"RapidOCR timed out after {timeout_seconds:g} seconds: {image_path}; "
            f"sha256={image_sha256}; worker_pid={worker_pid}; "
            f"last_stage={diagnostics['last_stage']}; "
            f"exitcode={diagnostics.get('exitcode_after_termination')}; "
            f"evidence={diagnostics.get('evidence_path')}"
        )
        raise OcrTimeoutError(message, diagnostics=diagnostics)

    def _raise_worker_error_locked(
        self,
        *,
        reason: str,
        worker_error: dict[str, Any] | None,
        image_path: Path,
        image_sha256: str,
        image_size: int,
        timeout_seconds: float,
        job_id: str,
        worker_pid: int | None,
        events: list[dict[str, Any]],
        call_started: float,
        diagnostics_dir: Path | None,
    ) -> None:
        diagnostics = self._base_diagnostics(
            kind="worker_error",
            reason=reason,
            image_path=image_path,
            image_sha256=image_sha256,
            image_size=image_size,
            timeout_seconds=timeout_seconds,
            job_id=job_id,
            worker_pid=worker_pid,
            events=events,
            call_started=call_started,
            finished_at=time.monotonic(),
        )
        diagnostics["worker_error"] = worker_error
        diagnostics.update(self._stop_worker_locked(graceful=False))
        diagnostics = self._persist_and_attach(
            diagnostics,
            image_path=image_path,
            diagnostics_dir=diagnostics_dir,
        )
        worker_error = worker_error or {}
        detail = (
            f"{worker_error.get('type')}: {worker_error.get('message')}"
            if worker_error
            else reason
        )
        raise OcrWorkerError(
            f"RapidOCR worker failed: {detail}; evidence={diagnostics.get('evidence_path')}",
            diagnostics=diagnostics,
        )

    def extract(
        self,
        path: Path,
        *,
        timeout_seconds: float,
        diagnostics_dir: Path | None = None,
    ) -> tuple[str, list[dict]]:
        timeout_seconds = max(0.01, float(timeout_seconds))
        image_path = Path(path).resolve()
        call_started = time.monotonic()
        deadline = call_started + timeout_seconds
        image_sha256 = _sha256_file(image_path)
        image_size = image_path.stat().st_size

        remaining = deadline - time.monotonic()
        acquired = remaining > 0 and self._lock.acquire(timeout=remaining)
        if not acquired:
            diagnostics = self._base_diagnostics(
                kind="timeout",
                reason="timed out waiting for the serialized OCR supervisor lock",
                image_path=image_path,
                image_sha256=image_sha256,
                image_size=image_size,
                timeout_seconds=timeout_seconds,
                job_id=None,
                worker_pid=self.worker_pid,
                events=[],
                call_started=call_started,
                finished_at=time.monotonic(),
            )
            diagnostics["last_stage"] = "waiting_for_supervisor_lock"
            diagnostics = self._persist_and_attach(
                diagnostics,
                image_path=image_path,
                diagnostics_dir=diagnostics_dir,
            )
            raise OcrTimeoutError(
                f"RapidOCR timed out after {timeout_seconds:g} seconds waiting for "
                f"the OCR supervisor lock: {image_path}; sha256={image_sha256}; "
                f"worker_pid={diagnostics.get('worker_pid')}; "
                f"last_stage=waiting_for_supervisor_lock; "
                f"evidence={diagnostics.get('evidence_path')}",
                diagnostics=diagnostics,
            )

        try:
            cached = self._cache.get(image_sha256, now=time.monotonic())
            if cached is not None:
                return pickle.loads(cached)

            self._ensure_worker_locked()
            process = self._process
            connection = self._connection
            if process is None or connection is None:
                raise RuntimeError("OCR worker was not created")

            worker_pid = process.pid
            job_id = uuid.uuid4().hex
            events = list(self._worker_lifecycle_events)
            if time.monotonic() >= deadline:
                self._raise_timeout_locked(
                    reason="deadline elapsed while starting the OCR worker",
                    image_path=image_path,
                    image_sha256=image_sha256,
                    image_size=image_size,
                    timeout_seconds=timeout_seconds,
                    job_id=job_id,
                    worker_pid=worker_pid,
                    events=events,
                    call_started=call_started,
                    diagnostics_dir=diagnostics_dir,
                    terminate_worker=True,
                )

            try:
                connection.send(
                    {
                        "kind": "ocr",
                        "job_id": job_id,
                        "path": str(image_path),
                        "image_sha256": image_sha256,
                    }
                )
                self._record_parent_stage(
                    stage="job_dispatched",
                    job_id=job_id,
                    worker_pid=worker_pid,
                    events=events,
                )
            except (BrokenPipeError, EOFError, OSError) as exc:
                self._raise_worker_error_locked(
                    reason="could not dispatch OCR job to worker",
                    worker_error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                    image_path=image_path,
                    image_sha256=image_sha256,
                    image_size=image_size,
                    timeout_seconds=timeout_seconds,
                    job_id=job_id,
                    worker_pid=worker_pid,
                    events=events,
                    call_started=call_started,
                    diagnostics_dir=diagnostics_dir,
                )

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._raise_timeout_locked(
                        reason="worker did not return a final result before the deadline",
                        image_path=image_path,
                        image_sha256=image_sha256,
                        image_size=image_size,
                        timeout_seconds=timeout_seconds,
                        job_id=job_id,
                        worker_pid=worker_pid,
                        events=events,
                        call_started=call_started,
                        diagnostics_dir=diagnostics_dir,
                        terminate_worker=True,
                    )

                if connection.poll(min(remaining, 0.25)):
                    try:
                        message = connection.recv()
                    except (EOFError, OSError) as exc:
                        self._raise_worker_error_locked(
                            reason="OCR worker connection closed before a result",
                            worker_error={
                                "type": type(exc).__name__,
                                "message": str(exc),
                                "traceback": traceback.format_exc(),
                            },
                            image_path=image_path,
                            image_sha256=image_sha256,
                            image_size=image_size,
                            timeout_seconds=timeout_seconds,
                            job_id=job_id,
                            worker_pid=worker_pid,
                            events=events,
                            call_started=call_started,
                            diagnostics_dir=diagnostics_dir,
                        )
                    if not isinstance(message, dict):
                        continue
                    kind = message.get("kind")
                    if kind == "stage":
                        self._record_stage(message, events)
                        continue
                    if message.get("job_id") != job_id:
                        continue
                    if kind == "result":
                        payload = message.get("payload")
                        if not isinstance(payload, bytes):
                            self._raise_worker_error_locked(
                                reason="OCR worker returned an invalid result payload",
                                worker_error=None,
                                image_path=image_path,
                                image_sha256=image_sha256,
                                image_size=image_size,
                                timeout_seconds=timeout_seconds,
                                job_id=job_id,
                                worker_pid=worker_pid,
                                events=events,
                                call_started=call_started,
                                diagnostics_dir=diagnostics_dir,
                            )
                        result = pickle.loads(payload)
                        cache_stored = self._cache.put(
                            image_sha256,
                            payload,
                            now=time.monotonic(),
                        )
                        success_diagnostics = self._base_diagnostics(
                            kind="success",
                            reason="worker returned a valid OCR result",
                            image_path=image_path,
                            image_sha256=image_sha256,
                            image_size=image_size,
                            timeout_seconds=timeout_seconds,
                            job_id=job_id,
                            worker_pid=worker_pid,
                            events=events,
                            call_started=call_started,
                            finished_at=time.monotonic(),
                        )
                        success_diagnostics["cache_stored"] = cache_stored
                        self._last_worker_diagnostics = success_diagnostics
                        return result
                    if kind == "error":
                        self._raise_worker_error_locked(
                            reason="OCR worker reported an exception",
                            worker_error=message.get("error"),
                            image_path=image_path,
                            image_sha256=image_sha256,
                            image_size=image_size,
                            timeout_seconds=timeout_seconds,
                            job_id=job_id,
                            worker_pid=worker_pid,
                            events=events,
                            call_started=call_started,
                            diagnostics_dir=diagnostics_dir,
                        )
                    continue

                if not process.is_alive():
                    self._raise_worker_error_locked(
                        reason="OCR worker exited without returning a result",
                        worker_error=None,
                        image_path=image_path,
                        image_sha256=image_sha256,
                        image_size=image_size,
                        timeout_seconds=timeout_seconds,
                        job_id=job_id,
                        worker_pid=worker_pid,
                        events=events,
                        call_started=call_started,
                        diagnostics_dir=diagnostics_dir,
                    )
        finally:
            self._lock.release()

    def shutdown(self) -> None:
        acquired = self._lock.acquire(timeout=_PROCESS_JOIN_SECONDS)
        if not acquired:
            return
        try:
            self._stop_worker_locked(graceful=True)
        finally:
            self._lock.release()


_OCR_SUPERVISOR = _OcrWorkerSupervisor()


def _run_ocr_in_process(
    path: Path,
    *,
    timeout_seconds: float,
    worker_target: WorkerTarget | None = None,
    diagnostics_dir: Path | None = None,
) -> tuple[str, list[dict]]:
    if worker_target is None:
        return _OCR_SUPERVISOR.extract(
            path,
            timeout_seconds=timeout_seconds,
            diagnostics_dir=diagnostics_dir,
        )

    temporary_supervisor = _OcrWorkerSupervisor(
        worker_target=worker_target,
        diagnostics_dir=diagnostics_dir,
    )
    try:
        return temporary_supervisor.extract(
            path,
            timeout_seconds=timeout_seconds,
            diagnostics_dir=diagnostics_dir,
        )
    finally:
        temporary_supervisor.shutdown()


def clear_ocr_cache(image_sha256: str | None = None) -> None:
    """Invalidate one SHA256 entry or the entire bounded in-memory OCR cache.

    Entries also expire after ``OCR_CACHE_TTL_SECONDS``, are evicted by LRU entry
    and byte limits, and disappear when the owning service process restarts.
    """

    _OCR_SUPERVISOR.clear_cache(image_sha256)


def _shutdown_ocr_runtime() -> None:
    _OCR_SUPERVISOR.shutdown()


atexit.register(_shutdown_ocr_runtime)


def extract_text(
    path: Path,
    *,
    timeout_seconds: float = OCR_TIMEOUT_SECONDS,
    diagnostics_dir: Path | None = None,
) -> tuple[str, list[dict]]:
    return _run_ocr_in_process(
        path,
        timeout_seconds=timeout_seconds,
        diagnostics_dir=diagnostics_dir,
    )
