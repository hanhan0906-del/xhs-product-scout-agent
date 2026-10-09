from __future__ import annotations

import os
from pathlib import Path
import time

import pytest

import xhs_scout.ocr as ocr_module
from xhs_scout.ocr import OcrTimeoutError, _OcrWorkerSupervisor


def _configured_images() -> list[Path]:
    configured = os.environ.get("XHS_SCOUT_OCR_SMOKE_IMAGES")
    if configured:
        return [Path(value) for value in configured.split(os.pathsep) if value]
    single = os.environ.get("XHS_SCOUT_OCR_SMOKE_IMAGE")
    return [Path(single)] if single else []


def _unhooked_real_worker(connection) -> None:
    ocr_module._ocr_worker_loop_impl(
        connection,
        instrument_components=False,
    )


@pytest.mark.skipif(
    not _configured_images(),
    reason="set XHS_SCOUT_OCR_SMOKE_IMAGES for an explicit offline RapidOCR smoke run",
)
def test_real_rapidocr_spawn_worker_samples_and_hash_cache(tmp_path: Path) -> None:
    samples: list[tuple[Path, Path]] = []
    for index, source in enumerate(_configured_images(), start=1):
        first_path = tmp_path / f"sample-{index}.png"
        same_bytes_path = tmp_path / f"sample-{index}-same-bytes.png"
        image_bytes = source.read_bytes()
        first_path.write_bytes(image_bytes)
        same_bytes_path.write_bytes(image_bytes)
        samples.append((first_path, same_bytes_path))

    baseline_supervisor = _OcrWorkerSupervisor(
        worker_target=_unhooked_real_worker,
        diagnostics_dir=tmp_path / "baseline-diagnostics",
    )
    baseline_results = []
    try:
        for first_path, _ in samples:
            baseline_results.append(
                baseline_supervisor.extract(first_path, timeout_seconds=90.0)
            )
    finally:
        baseline_supervisor.shutdown()

    supervisor = _OcrWorkerSupervisor(diagnostics_dir=tmp_path / "diagnostics")

    try:
        worker_pid = None
        for index, (first_path, same_bytes_path) in enumerate(samples):
            try:
                first_result = supervisor.extract(first_path, timeout_seconds=90.0)
            except OcrTimeoutError as exc:
                assert exc.last_stage
                assert exc.evidence_path
                assert Path(exc.evidence_path).is_file()
                raise
            worker_pid = worker_pid or supervisor.worker_pid
            cached_started = time.monotonic()
            cached_result = supervisor.extract(same_bytes_path, timeout_seconds=5.0)
            cached_elapsed = time.monotonic() - cached_started

            assert isinstance(first_result[0], str)
            assert isinstance(first_result[1], list)
            assert first_result[1]
            assert first_result == baseline_results[index]
            assert cached_result == first_result
            assert cached_elapsed < 1.0
            assert supervisor.worker_pid == worker_pid

            diagnostics = supervisor.last_worker_diagnostics()
            assert diagnostics is not None
            job_id = diagnostics["job_id"]
            component_stages = [
                event["stage"]
                for event in diagnostics["stage_events"]
                if event["job_id"] == job_id
                and event["stage"]
                in {
                    "image_load_started",
                    "image_load_done",
                    "detection_started",
                    "detection_done",
                    "classification_started",
                    "classification_done",
                    "recognition_started",
                    "recognition_done",
                }
            ]
            assert component_stages == [
                "image_load_started",
                "image_load_done",
                "detection_started",
                "detection_done",
                "classification_started",
                "classification_done",
                "recognition_started",
                "recognition_done",
            ]
            for duration_name in (
                "image_load_seconds",
                "detection_seconds",
                "classification_seconds",
                "recognition_seconds",
            ):
                assert diagnostics["stage_durations"][duration_name] >= 0
    finally:
        supervisor.shutdown()
