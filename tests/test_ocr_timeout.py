from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import pickle
import threading
import time

import pytest

import xhs_scout.ocr as ocr_module
from xhs_scout.ocr import (
    OcrTimeoutError,
    _BoundedResultCache,
    _OcrWorkerSupervisor,
    _ocr_worker_loop,
)


def _fake_stage(connection, stage: str, job_id: str | None) -> None:
    connection.send(
        {
            "kind": "stage",
            "stage": stage,
            "job_id": job_id,
            "worker_pid": os.getpid(),
            "worker_monotonic": time.monotonic(),
            "wall_time": "fake",
            "data": {},
        }
    )


def _scripted_worker(connection) -> None:
    count = 0
    engine_ready = False
    _fake_stage(connection, "worker_started", None)
    try:
        while True:
            command = connection.recv()
            if command.get("kind") == "shutdown":
                return
            if command.get("kind") != "ocr":
                continue
            job_id = command["job_id"]
            path = Path(command["path"])
            if not engine_ready:
                for stage in (
                    "import_started",
                    "import_done",
                    "engine_init_started",
                    "engine_init_done",
                ):
                    _fake_stage(connection, stage, job_id)
                engine_ready = True
            else:
                _fake_stage(connection, "engine_reused", job_id)

            _fake_stage(connection, "inference_started", job_id)
            if path.name.startswith("block"):
                while True:
                    time.sleep(1)
            if path.name.startswith("delay"):
                time.sleep(0.1)
            count += 1
            result = (
                f"{os.getpid()}:{count}:{path.name}",
                [{"box": [], "text": path.name, "confidence": 1.0}],
            )
            _fake_stage(connection, "inference_done", job_id)
            _fake_stage(connection, "serialize_started", job_id)
            payload = pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL)
            _fake_stage(connection, "serialize_done", job_id)
            connection.send(
                {
                    "kind": "result",
                    "job_id": job_id,
                    "worker_pid": os.getpid(),
                    "payload": payload,
                }
            )
    except EOFError:
        return
    finally:
        connection.close()


class _NamedComponent:
    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, *args, **_kwargs):
        if self.name == "load":
            return Path(args[0]).name
        if self.name == "detect":
            return [args[0]], 0.01
        if self.name == "classify":
            return args[0], [["0", 1.0]], 0.01
        images = args[0]
        if any(str(image).startswith("block") for image in images):
            while True:
                time.sleep(1)
        return [(str(image), 0.9) for image in images], 0.01


class _RecognitionBlockingRapidOCR:
    def __init__(self) -> None:
        self.load_img = _NamedComponent("load")
        self.text_det = _NamedComponent("detect")
        self.text_cls = _NamedComponent("classify")
        self.text_rec = _NamedComponent("recognize")

    def __call__(self, path: str):
        image = self.load_img(path)
        boxes, detection_elapsed = self.text_det(image)
        images, _, classification_elapsed = self.text_cls(boxes)
        recognized, recognition_elapsed = self.text_rec(images, False)
        return (
            [
                ([0, 0, 1, 1], text, confidence)
                for text, confidence in recognized
            ],
            [
                detection_elapsed,
                classification_elapsed,
                recognition_elapsed,
            ],
        )


def _recognition_blocking_worker(connection) -> None:
    ocr_module._ocr_worker_loop_impl(
        connection,
        instrument_components=True,
        rapidocr_loader=lambda: _RecognitionBlockingRapidOCR,
    )


def _collect_result(connection, job_id: str) -> tuple[list[dict], tuple[str, list[dict]]]:
    messages: list[dict] = []
    while True:
        assert connection.poll(2.0), f"worker did not answer job {job_id}"
        message = connection.recv()
        messages.append(message)
        if message.get("kind") == "result" and message.get("job_id") == job_id:
            return messages, pickle.loads(message["payload"])


def test_production_worker_emits_stages_and_reuses_one_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counters = {"init": 0, "inference": 0}

    class FakeComponent:
        def __init__(self, function) -> None:
            self.function = function

        def __call__(self, *args, **kwargs):
            return self.function(*args, **kwargs)

    class FakeRapidOCR:
        def __init__(self) -> None:
            counters["init"] += 1
            self.load_img = FakeComponent(lambda path: Path(path).name)
            self.text_det = FakeComponent(lambda image: ([image], 0.01))
            self.text_cls = FakeComponent(
                lambda images: (images, [["0", 1.0]], 0.01)
            )
            self.text_rec = FakeComponent(
                lambda images, _return_word_box: (
                    [(str(image), 0.9) for image in images],
                    0.01,
                )
            )

        def __call__(self, path: str):
            counters["inference"] += 1
            image = self.load_img(path)
            boxes, detection_elapsed = self.text_det(image)
            images, _, classification_elapsed = self.text_cls(boxes)
            recognized, recognition_elapsed = self.text_rec(images, False)
            result = [
                ([0, 0, 1, 1], text, confidence)
                for text, confidence in recognized
            ]
            return result, [
                detection_elapsed,
                classification_elapsed,
                recognition_elapsed,
            ]

    monkeypatch.setattr(
        ocr_module,
        "_load_rapidocr_class",
        lambda: FakeRapidOCR,
    )
    parent_connection, child_connection = multiprocessing.Pipe(duplex=True)
    worker = threading.Thread(
        target=_ocr_worker_loop,
        args=(child_connection,),
        daemon=True,
    )
    worker.start()
    first_message = parent_connection.recv()
    assert first_message["stage"] == "worker_started"

    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    parent_connection.send({"kind": "ocr", "job_id": "job-1", "path": str(first_path)})
    first_messages, first_result = _collect_result(parent_connection, "job-1")
    parent_connection.send({"kind": "ocr", "job_id": "job-2", "path": str(second_path)})
    second_messages, second_result = _collect_result(parent_connection, "job-2")
    parent_connection.send({"kind": "shutdown"})
    worker.join(timeout=2.0)
    parent_connection.close()

    first_stages = [
        first_message["stage"],
        *[
            message["stage"]
            for message in first_messages
            if message.get("kind") == "stage"
        ],
    ]
    assert first_stages == [
        "worker_started",
        "import_started",
        "import_done",
        "engine_init_started",
        "engine_init_done",
        "engine_hooks_installed",
        "inference_started",
        "image_load_started",
        "image_load_done",
        "detection_started",
        "detection_done",
        "classification_started",
        "classification_done",
        "recognition_started",
        "recognition_done",
        "inference_done",
        "serialize_started",
        "serialize_done",
    ]
    assert [
        message["stage"]
        for message in second_messages
        if message.get("kind") == "stage"
    ] == [
        "engine_reused",
        "inference_started",
        "image_load_started",
        "image_load_done",
        "detection_started",
        "detection_done",
        "classification_started",
        "classification_done",
        "recognition_started",
        "recognition_done",
        "inference_done",
        "serialize_started",
        "serialize_done",
    ]
    assert first_result[0] == "first.png"
    assert second_result[0] == "second.png"
    assert counters == {"init": 1, "inference": 2}
    assert not worker.is_alive()


def test_timeout_terminates_worker_persists_evidence_and_rebuilds(
    tmp_path: Path,
) -> None:
    diagnostics_dir = tmp_path / "diagnostics"
    supervisor = _OcrWorkerSupervisor(
        worker_target=_recognition_blocking_worker,
        diagnostics_dir=diagnostics_dir,
    )
    blocked_path = tmp_path / "block.png"
    blocked_path.write_bytes(b"blocked-image")
    started_at = time.monotonic()

    try:
        with pytest.raises(OcrTimeoutError) as captured:
            supervisor.extract(blocked_path, timeout_seconds=2.0)

        error = captured.value
        assert time.monotonic() - started_at < 6.0
        assert error.image_sha256 == hashlib.sha256(b"blocked-image").hexdigest()
        assert isinstance(error.worker_pid, int)
        assert error.last_stage == "recognition_started"
        assert error.stage_durations["import_seconds"] >= 0
        assert error.stage_durations["engine_init_seconds"] >= 0
        assert error.stage_durations["image_load_seconds"] >= 0
        assert error.stage_durations["detection_seconds"] >= 0
        assert error.stage_durations["classification_seconds"] >= 0
        assert "recognition_seconds" not in error.stage_durations
        assert error.stage_durations["last_stage_elapsed_seconds"] > 0
        assert error.exitcode is not None
        assert error.evidence_path is not None
        assert Path(error.evidence_path).is_file()
        assert supervisor.worker_pid is None

        evidence = json.loads(Path(error.evidence_path).read_text(encoding="utf-8"))
        assert evidence["image_sha256"] == error.image_sha256
        assert evidence["worker_pid"] == error.worker_pid
        assert evidence["last_stage"] == "recognition_started"
        assert evidence["terminate_sent"] is True
        assert evidence["worker_still_alive"] is False
        assert evidence["exitcode_after_termination"] is not None
        assert evidence["evidence_path"] == error.evidence_path
        assert [event["stage"] for event in evidence["stage_events"]] == [
            "job_dispatched",
            "worker_started",
            "import_started",
            "import_done",
            "engine_init_started",
            "engine_init_done",
            "engine_hooks_installed",
            "inference_started",
            "image_load_started",
            "image_load_done",
            "detection_started",
            "detection_done",
            "classification_started",
            "classification_done",
            "recognition_started",
        ]

        replacement_path = tmp_path / "replacement.png"
        replacement_path.write_bytes(b"replacement-image")
        replacement_text, _ = supervisor.extract(
            replacement_path,
            timeout_seconds=3.0,
        )
        replacement_pid = supervisor.worker_pid
        assert replacement_text == "replacement.png"
        assert replacement_pid is not None
        assert replacement_pid != error.worker_pid
        assert supervisor.worker_pid == replacement_pid
    finally:
        supervisor.shutdown()

    assert supervisor.worker_pid is None


def test_long_lived_worker_hash_cache_is_cross_path_bounded_and_invalidatable(
    tmp_path: Path,
) -> None:
    supervisor = _OcrWorkerSupervisor(
        worker_target=_scripted_worker,
        diagnostics_dir=tmp_path / "diagnostics",
        cache_max_entries=1,
        cache_max_bytes=1024 * 1024,
        cache_ttl_seconds=60,
    )
    first_path = tmp_path / "first.png"
    same_bytes_path = tmp_path / "same-bytes.png"
    other_path = tmp_path / "other.png"
    first_path.write_bytes(b"same-image")
    same_bytes_path.write_bytes(b"same-image")
    other_path.write_bytes(b"other-image")

    try:
        first_text, _ = supervisor.extract(first_path, timeout_seconds=3.0)
        cached_text, _ = supervisor.extract(same_bytes_path, timeout_seconds=3.0)
        other_text, _ = supervisor.extract(other_path, timeout_seconds=3.0)
        evicted_text, _ = supervisor.extract(same_bytes_path, timeout_seconds=3.0)

        first_pid, first_count, _ = first_text.split(":", 2)
        other_pid, other_count, _ = other_text.split(":", 2)
        evicted_pid, evicted_count, evicted_name = evicted_text.split(":", 2)
        assert cached_text == first_text
        assert {first_pid, other_pid, evicted_pid} == {str(supervisor.worker_pid)}
        assert [int(first_count), int(other_count), int(evicted_count)] == [1, 2, 3]
        assert evicted_name == "same-bytes.png"
        assert supervisor.cache_info()["entries"] == 1
        assert supervisor.cache_info()["bytes"] <= supervisor.cache_info()["max_bytes"]

        supervisor.clear_cache(hashlib.sha256(b"same-image").hexdigest())
        assert supervisor.cache_info()["entries"] == 0
    finally:
        supervisor.shutdown()


def test_cache_byte_limit_and_ttl_are_hard_bounds() -> None:
    cache = _BoundedResultCache(max_entries=2, max_bytes=5, ttl_seconds=10)
    assert cache.put("too-large", b"123456", now=0) is False
    assert cache.info()["entries"] == 0
    assert cache.put("a", b"12", now=0) is True
    assert cache.put("b", b"345", now=0) is True
    assert cache.info()["bytes"] == 5
    assert cache.put("c", b"6", now=0) is True
    assert cache.get("a", now=0) is None
    assert cache.info()["entries"] == 2
    assert cache.get("b", now=11) is None
    assert cache.info()["entries"] == 0


def test_concurrent_callers_are_serialized_through_one_spawn_worker(
    tmp_path: Path,
) -> None:
    supervisor = _OcrWorkerSupervisor(
        worker_target=_scripted_worker,
        diagnostics_dir=tmp_path / "diagnostics",
    )
    paths = [tmp_path / "delay-one.png", tmp_path / "delay-two.png"]
    paths[0].write_bytes(b"one")
    paths[1].write_bytes(b"two")

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda path: supervisor.extract(path, timeout_seconds=4.0)[0],
                    paths,
                )
            )
        pids = {result.split(":", 1)[0] for result in results}
        counts = {int(result.split(":", 2)[1]) for result in results}
        assert pids == {str(supervisor.worker_pid)}
        assert counts == {1, 2}
        assert supervisor.start_method == "spawn"
    finally:
        supervisor.shutdown()
