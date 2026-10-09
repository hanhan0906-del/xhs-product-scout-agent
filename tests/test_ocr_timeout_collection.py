import json
from pathlib import Path

import pytest

import xhs_scout.db as db_module
import xhs_scout.monitor as monitor_module
from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    record_ocr_timeout_hard_stop,
    record_note_observation,
    set_monitor_desired_state,
)
from xhs_scout.ocr import OcrTimeoutError
from xhs_scout.run_control import acquire_monitor_lease
from xhs_scout.ui_automation import Bounds, UiTarget
from xhs_scout.workflow import capture_current_page_for_task, start_task


TIMEOUT_MESSAGE = "RapidOCR timed out after 60 seconds: current.png"


class _CaptureDevice:
    def tap(self, _x, _y):
        return None

    def force_stop(self, _package, *, timeout):
        return timeout

    def window_focus(self):
        return (
            "mCurrentFocus=Window{abc u0 "
            "com.xingin.xhs/com.xingin.goods.detail.GoodsDetailActivityV2}"
        )

    def screenshot(self, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"timeout screenshot")
        return destination

    def ui_dump(self):
        return (
            '<hierarchy><node text="客服"/><node text="购物车"/>'
            '<node text="加入购物车"/></hierarchy>'
        )


def _offline_report(settings, limit=20):
    return {
        "report_path": str(settings.reports_dir / "offline-ocr-timeout.md"),
        "count": 0,
        "limit": limit,
    }


def _one_task(settings, keyword="OCR timeout"):
    with connect(settings.db_path) as conn:
        enqueue(conn, [keyword], source="test")
        return conn.execute(
            "SELECT id FROM search_tasks WHERE keyword=?", (keyword,)
        ).fetchone()[0]


def test_workflow_ocr_timeout_preserves_evidence_refunds_attempt_and_writes_no_product(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings)
    monkeypatch.setattr(
        "xhs_scout.ingest.extract_text",
        lambda _path: (_ for _ in ()).throw(OcrTimeoutError(TIMEOUT_MESSAGE)),
    )

    output = capture_current_page_for_task(
        settings,
        _CaptureDevice(),
        task_id,
        capture_metrics=False,
        run_id="workflow-ocr-timeout",
    )

    assert output["reason_code"] == "ocr_timeout"
    assert output["hard_stop"] is True
    assert output["task_result"] is None
    assert output["ocr_timeout"]["run_id"] == "workflow-ocr-timeout"
    assert output["ocr_timeout"]["task_id"] == task_id
    screenshot = output["ocr_timeout"]["evidence"]["screenshot"]
    xml_path = output["ocr_timeout"]["evidence"]["xml"]
    assert screenshot and xml_path
    assert Path(screenshot).exists()
    assert "加入购物车" in Path(xml_path).read_text(encoding="utf-8")

    with connect(settings.db_path) as conn:
        task = conn.execute(
            """
            SELECT status, attempts, run_owner, run_lease_expires_at, last_error
            FROM search_tasks WHERE id=?
            """,
            (task_id,),
        ).fetchone()
        assert tuple(task[:4]) == ("pending", 0, None, None)
        assert task["last_error"] == output["blocked"]
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == output["blocked"]
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 0
        event = conn.execute(
            "SELECT event, data_json FROM run_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert event["event"] == "ocr_timeout_hard_stop"
        event_data = json.loads(event["data_json"])
        assert event_data["refunded_tasks"][0]["attempts_after"] == 0


def test_probe_start_ocr_timeout_returns_last_attempt_and_is_not_generic_zero_result(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "probe timeout")
    with connect(settings.db_path) as conn:
        conn.execute(
            "UPDATE search_tasks SET attempts=2, max_attempts=3 WHERE id=?",
            (task_id,),
        )
        set_monitor_desired_state(conn, "running")

    device = _CaptureDevice()
    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)

    def timeout_at_probe_start(_settings, called_device, *, run_id, task, limits):
        probe_dir = settings.data_dir / "probes" / f"{run_id}-probe-start"
        probe_dir.mkdir(parents=True, exist_ok=True)
        screenshot = probe_dir / "current.png"
        screenshot.write_bytes(b"probe timeout screenshot")
        (probe_dir / "window.txt").write_text(
            called_device.window_focus(), encoding="utf-8"
        )
        probe = {
            "run_id": f"{run_id}-probe-start",
            "probe_dir": str(probe_dir),
            "activity": called_device.window_focus(),
            "has_anr": False,
            "risk_stop_reason": TIMEOUT_MESSAGE,
            "page_kind": "ocr_timeout",
            "screenshot": str(screenshot),
            "text": "",
            "ocr_count": 0,
            "ocr_timeout": True,
            "ocr_error": TIMEOUT_MESSAGE,
            "reason_code": "ocr_timeout",
            "infrastructure_failure": True,
            "exception": {
                "type": "OcrTimeoutError",
                "message": TIMEOUT_MESSAGE,
            },
        }
        monitor_module._guard_probe(
            _settings,
            run_id,
            probe,
            task["id"],
            device=called_device,
            dry_run=limits.dry_run,
        )
        raise AssertionError("OCR timeout guard must stop before search continues")

    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results", timeout_at_probe_start
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report", _offline_report
    )

    output = monitor_module.monitor_once(
        settings,
        limits=monitor_module.MonitorLimits(
            max_keywords=1,
            max_products_per_keyword=1,
            requeue_due_keywords=False,
            wait_seconds=0,
        ),
    )

    assert output["processed_tasks"] == 0
    assert output["captured_products"] == 0
    assert output["reason_code"] == "ocr_timeout"
    assert output["hard_stop"] is True
    assert output["requires_explicit_resume"] is True
    assert output["ocr_timeout"]["task_id"] == task_id
    assert output["ocr_timeout"]["refunded_tasks"] == [
        {
            "task_id": task_id,
            "keyword": "probe timeout",
            "attempts_before": 3,
            "attempts_after": 2,
            "status": "pending",
        }
    ]
    assert output["skipped"][0]["retryable_after_resume"] is True
    xml_path = output["ocr_timeout"]["evidence"]["xml"]
    assert xml_path
    assert Path(xml_path).exists()

    with connect(settings.db_path) as conn:
        task = conn.execute(
            """
            SELECT status, attempts, run_owner, run_lease_expires_at, last_error
            FROM search_tasks WHERE id=?
            """,
            (task_id,),
        ).fetchone()
        assert tuple(task[:4]) == ("pending", 2, None, None)
        assert task["status"] != "needs_manual_detail"
        assert task["last_error"] == output["blocked"]
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == output["blocked"]
        assert state["last_block_reason"] == output["blocked"]
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM run_events WHERE event='ocr_timeout_hard_stop'"
        ).fetchone()[0] == 1


def test_metrics_ocr_timeout_occurs_before_deferred_product_persistence(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "metrics timeout")
    monkeypatch.setattr(
        "xhs_scout.workflow.ingest_image",
        lambda *_args, **_kwargs: {
            "image": "detail.png",
            "stored": "detail.png",
            "source": "android_emulator_task",
            "text": "完整商品详情证据",
            "signals": {},
            "page_kind": "product_detail",
            "page_kind_source": "strict_product_detail_ui",
            "score": 0,
            "evidence_grade": "C",
            "reasons": [],
            "_deferred_ingest": {
                "observed_at": "2026-08-14T00:00:00+00:00",
                "fingerprint": "deferred-timeout",
                "ocr": [],
            },
        },
    )
    monkeypatch.setattr(
        "xhs_scout.workflow.capture_metrics_strip",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OcrTimeoutError("RapidOCR timed out after 60 seconds: metrics-roi.png")
        ),
    )

    output = capture_current_page_for_task(
        settings,
        _CaptureDevice(),
        task_id,
        capture_metrics=True,
        run_id="metrics-ocr-timeout",
    )

    assert output["reason_code"] == "ocr_timeout"
    assert output["ocr_timeout"]["phase"] == "metrics_strip_ocr"
    assert output["task_result"] is None
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts FROM search_tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert tuple(task) == ("pending", 0)
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM candidate_assessments").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 0


def test_metrics_success_commits_deferred_ingest_and_valid_task_result(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "metrics success")
    monkeypatch.setattr(
        "xhs_scout.workflow.ingest_image",
        lambda *_args, **_kwargs: {
            "image": "detail.png",
            "stored": "detail.png",
            "source": "android_emulator_task",
            "text": "￥9.9 已售100",
            "signals": {},
            "page_kind": "product_detail",
            "page_kind_source": "strict_product_detail_ui",
            "score": 1,
            "evidence_grade": "C",
            "reasons": ["test"],
            "_deferred_ingest": {
                "observed_at": "2026-08-14T00:00:00+00:00",
                "fingerprint": "deferred-success",
                "ocr": [],
            },
        },
    )
    monkeypatch.setattr(
        "xhs_scout.workflow.capture_metrics_strip",
        lambda *_args, **_kwargs: {
            "signals": {},
            "capture_dir": "metrics-success",
            "skip_reason": "no optional metrics in fixture",
        },
    )
    monkeypatch.setattr(
        "xhs_scout.workflow.capture_product_share_url",
        lambda *_args, **_kwargs: {"skip_reason": "not needed in fixture"},
    )

    output = capture_current_page_for_task(
        settings,
        _CaptureDevice(),
        task_id,
        capture_metrics=True,
        run_id="metrics-success",
    )

    assert output["task_result"]["status"] == "completed"
    assert "_deferred_ingest" not in output
    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM candidate_assessments").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 1


def test_seller_probe_ocr_timeout_is_not_downgraded_to_business_failure(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "seller OCR timeout")
    with connect(settings.db_path) as conn:
        conn.execute(
            "UPDATE search_tasks SET attempts=2, max_attempts=3 WHERE id=?",
            (task_id,),
        )
        set_monitor_desired_state(conn, "running")

    device = _CaptureDevice()
    probe_dir = settings.data_dir / "probes" / "seller-timeout"
    probe_dir.mkdir(parents=True, exist_ok=True)
    screenshot = probe_dir / "current.png"
    screenshot.write_bytes(b"seller timeout screenshot")

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *_args, **_kwargs: {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards",
        lambda *_args, **_kwargs: [
            UiTarget(120, 240, Bounds(100, 200, 140, 280), "product", "test")
        ],
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._probe_opened_product_page",
        lambda *_args, **_kwargs: {"page_kind": "product_detail"},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        lambda *_args, **_kwargs: {"product_id": 1, "observation_id": 1},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.record_search_result_evidence",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_seller_profile_from_product",
        lambda *_args, **_kwargs: {
            "blocked": True,
            "reason": "seller_before_risk_stop",
            "before_probe": {
                "page_kind": "ocr_timeout",
                "ocr_timeout": True,
                "ocr_error": TIMEOUT_MESSAGE,
                "reason_code": "ocr_timeout",
                "infrastructure_failure": True,
                "exception": {
                    "type": "OcrTimeoutError",
                    "message": TIMEOUT_MESSAGE,
                },
                "risk_stop_reason": TIMEOUT_MESSAGE,
                "probe_dir": str(probe_dir),
                "screenshot": str(screenshot),
                "activity": device.window_focus(),
            },
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        _offline_report,
    )

    output = monitor_module.monitor_once(
        settings,
        limits=monitor_module.MonitorLimits(
            max_keywords=1,
            max_products_per_keyword=1,
            requeue_due_keywords=False,
            wait_seconds=0,
            seller_profile=True,
        ),
    )

    assert output["reason_code"] == "ocr_timeout"
    assert output["ocr_timeout"]["phase"] == "seller_profile_before_probe_ocr"
    assert output["ocr_timeout"]["refunded_tasks"][0]["attempts_after"] == 2
    assert Path(output["ocr_timeout"]["evidence"]["xml"]).exists()
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(task) == ("pending", 2, None)
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 0
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == output["blocked"]


def test_runtime_error_with_timeout_wording_does_not_refund_attempt(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "timeout wording is not a timeout contract")
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")
        start_task(conn, task_id, owner="runtime-wording")

    device = _CaptureDevice()
    monkeypatch.setattr(
        "xhs_scout.monitor.open_related_note_once",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(TIMEOUT_MESSAGE)
        ),
    )
    recovery_calls = []
    monkeypatch.setattr(
        "xhs_scout.monitor._recover_to_product_detail_after_note_evidence",
        lambda *_args, **_kwargs: recovery_calls.append("recovered") or True,
    )
    output = monitor_module._capture_note_evidence_for_current_detail(
        settings,
        device,
        run_id="runtime-wording",
        task_id=task_id,
        product_id=None,
        limits=monitor_module.MonitorLimits(
            wait_seconds=0,
            seller_profile=False,
            note_evidence=True,
        ),
    )

    assert output["error"] == TIMEOUT_MESSAGE
    assert "ocr_timeout" not in output
    assert recovery_calls == ["recovered"]
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(task) == ("running", 1, "runtime-wording")
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 0
        assert get_monitor_state(conn)["desired_state"] == "running"


def test_note_after_probe_timeout_removes_only_its_dirty_auxiliary_row(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "note after OCR timeout")
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")
        conn.execute(
            """
            INSERT INTO products(fingerprint, title, first_seen_at, last_seen_at)
            VALUES ('note-timeout-product', 'valid base capture', ?, ?)
            """,
            ("2026-08-14T00:00:00+00:00", "2026-08-14T00:00:00+00:00"),
        )
        product_id = conn.execute(
            "SELECT id FROM products WHERE fingerprint='note-timeout-product'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(product_id, observed_at, source, raw_text)
            VALUES (?, ?, 'test', 'valid base capture')
            """,
            (product_id, "2026-08-14T00:00:00+00:00"),
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    device = _CaptureDevice()
    card = UiTarget(120, 240, Bounds(100, 200, 140, 280), "product", "test")
    probe_dir = settings.data_dir / "probes" / "note-after-timeout"
    probe_dir.mkdir(parents=True, exist_ok=True)
    screenshot = probe_dir / "current.png"
    screenshot.write_bytes(b"note after timeout screenshot")

    def timeout_note(*_args, **_kwargs):
        with connect(settings.db_path) as conn:
            dirty_id = record_note_observation(
                conn,
                product_id=product_id,
                source="related_note_card",
                screenshot_path=str(screenshot),
                probe_dir=str(probe_dir),
                page_kind="ocr_timeout",
                raw_text="",
            )
        return {
            "note_observation_id": dirty_id,
            "after_probe": {
                "page_kind": "ocr_timeout",
                "ocr_timeout": True,
                "ocr_error": TIMEOUT_MESSAGE,
                "reason_code": "ocr_timeout",
                "infrastructure_failure": True,
                "exception": {
                    "type": "OcrTimeoutError",
                    "message": TIMEOUT_MESSAGE,
                },
                "risk_stop_reason": TIMEOUT_MESSAGE,
                "probe_dir": str(probe_dir),
                "screenshot": str(screenshot),
                "activity": device.window_focus(),
            },
        }

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *_args, **_kwargs: {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards",
        lambda *_args, **_kwargs: [card],
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._probe_opened_product_page",
        lambda *_args, **_kwargs: {"page_kind": "product_detail"},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        lambda *_args, **_kwargs: {
            "product_id": product_id,
            "observation_id": observation_id,
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.record_search_result_evidence",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr("xhs_scout.monitor.open_related_note_once", timeout_note)
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        _offline_report,
    )

    output = monitor_module.monitor_once(
        settings,
        limits=monitor_module.MonitorLimits(
            max_keywords=1,
            max_products_per_keyword=1,
            requeue_due_keywords=False,
            wait_seconds=0,
            seller_profile=False,
            note_evidence=True,
        ),
    )

    removed = output["ocr_timeout"][
        "removed_ocr_timeout_note_observations"
    ]
    assert removed[0]["product_id"] == product_id
    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM note_observations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 0


def test_app_recovery_probe_timeout_returns_structured_global_stop(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")
        acquire_monitor_lease(
            conn,
            owner="app-recovery-ocr-timeout",
            ttl_seconds=900,
        )

    device = _CaptureDevice()
    probe_dir = settings.data_dir / "probes" / "app-recovery-timeout"
    probe_dir.mkdir(parents=True, exist_ok=True)
    screenshot = probe_dir / "current.png"
    screenshot.write_bytes(b"app recovery timeout screenshot")
    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor._launch_xhs",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "page_kind": "ocr_timeout",
            "ocr_timeout": True,
            "ocr_error": TIMEOUT_MESSAGE,
            "reason_code": "ocr_timeout",
            "infrastructure_failure": True,
            "exception": {
                "type": "OcrTimeoutError",
                "message": TIMEOUT_MESSAGE,
            },
            "risk_stop_reason": TIMEOUT_MESSAGE,
            "probe_dir": str(probe_dir),
            "screenshot": str(screenshot),
            "activity": device.window_focus(),
        },
    )

    output = monitor_module._recover_xhs_after_unresponsive(
        settings,
        run_id="app-recovery-ocr-timeout",
        limits=monitor_module.MonitorLimits(wait_seconds=0),
        error=monitor_module.AppUnresponsive(),
    )

    assert output["reason_code"] == "ocr_timeout"
    assert output["ocr_timeout"]["phase"] == "app_recovery_probe_ocr"
    assert output["app_recovery"]["attempted"] is True
    assert output["app_recovery"]["recovered"] is False
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == output["blocked"]


def test_ocr_timeout_task_refund_and_hard_stop_roll_back_together(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "atomic timeout")
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")
        start_task(conn, task_id, owner="atomic-run")
        dirty_note_id = record_note_observation(
            conn,
            product_id=None,
            source="related_note_card",
            screenshot_path="timeout.png",
            probe_dir="timeout-probe",
            page_kind="ocr_timeout",
            raw_text="",
        )

        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("audit insert failed")

        monkeypatch.setattr(db_module, "record_run_event", fail_audit)
        with pytest.raises(RuntimeError, match="audit insert failed"):
            record_ocr_timeout_hard_stop(
                conn,
                run_id="atomic-run",
                owner="atomic-run",
                reason="OCR infrastructure timeout: test",
                phase="current_detail_ocr",
                task_id=task_id,
                evidence={"screenshot": "test.png", "xml": "test.xml"},
                cleanup_note_observation_ids=[dirty_note_id],
            )

        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(task) == ("running", 1, "atomic-run")
        state = get_monitor_state(conn)
        assert state["desired_state"] == "running"
        assert state["risk_stop_reason"] is None
        assert conn.execute(
            "SELECT COUNT(*) FROM run_events WHERE event='ocr_timeout_hard_stop'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM note_observations WHERE id=?",
            (dirty_note_id,),
        ).fetchone()[0] == 1
