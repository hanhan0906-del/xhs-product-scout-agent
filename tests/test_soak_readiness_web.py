from __future__ import annotations

import inspect
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import xhs_scout.soak_readiness as soak_readiness_module
import xhs_scout.web as web_module
from xhs_scout.config import Settings
from xhs_scout.db import connect, record_run_event
from xhs_scout.soak_ack import append_soak_ack
from xhs_scout.soak_baseline import (
    build_baseline_manifest,
    write_baseline_manifest,
)
from xhs_scout.scheduler_evidence import append_scheduler_evidence
from xhs_scout.web import create_app


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 7, 29, 8, 0, tzinfo=TZ)


def _route(settings):
    return next(
        route.endpoint
        for route in create_app(settings).routes
        if getattr(route, "path", None) == "/api/soak-readiness"
    )


def _table_counts(path):
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        return {
            row[0]: conn.execute(f'SELECT COUNT(*) FROM "{row[0]}"').fetchone()[0]
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        }
    finally:
        conn.close()


def _install_critical_alert(monkeypatch, *, alert_id="digest-critical-web-001"):
    original = soak_readiness_module.load_sqlite_evidence

    def load_with_alert(source, *, context=None):
        bundle = original(source, context=context)
        bundle["digest_snapshots"] = [
            {
                "phase": "mid",
                "alerts": [
                    {
                        "alert_id": alert_id,
                        "severity": "critical",
                        "title": "Web ACK integration fixture",
                    }
                ],
            }
        ]
        return bundle

    monkeypatch.setattr(
        soak_readiness_module,
        "load_sqlite_evidence",
        load_with_alert,
    )
    return alert_id


def _append_ack(settings, *, alert_id, decision="acknowledge"):
    evidence_path = settings.root / "evidence" / f"{alert_id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text('{"status":"reviewed"}', encoding="utf-8")
    ledger_path = settings.root / "acks" / "soak-ack.jsonl"
    append_soak_ack(
        ledger_path,
        allowed_roots=[settings.root],
        record_id=f"web-{decision}-{alert_id}",
        alert_id=alert_id,
        alert_kind="critical",
        actor="web-test-operator",
        decision=decision,
        evidence_path=evidence_path,
        note="T47 offline test",
        decided_at=BASE,
    )
    return ledger_path


def _write_baseline(settings):
    code_path = settings.root / "baseline-fixture" / "worker.py"
    config_path = settings.root / "baseline-fixture" / "settings.json"
    code_path.parent.mkdir(parents=True, exist_ok=True)
    code_path.write_text("VALUE = 1\n", encoding="utf-8")
    config_path.write_text('{"enabled":true}\n', encoding="utf-8")
    manifest = build_baseline_manifest(
        project_root=settings.root,
        code_files=["baseline-fixture/worker.py"],
        config_files=["baseline-fixture/settings.json"],
        database_statistics={"quick_check": "ok", "run_count": 0},
        run_parameters={
            "interval_seconds": 3600,
            "max_keywords": 1,
            "max_products_per_keyword": 1,
        },
        port_owners={
            "8793": {"owner": "offline web fixture"},
            "8765": {"owner": "isolated offline fixture"},
        },
        disk_summary={"status": "caller supplied"},
        log_summary={"error_count": 0},
        operator="offline-web-operator",
        stop_entry={"procedure": "pause and wait for the current round"},
    )
    manifest_path = write_baseline_manifest(
        settings.root / "evidence" / "soak-baseline.json",
        manifest,
        allowed_roots=[settings.root],
    )
    return manifest, manifest_path, code_path


def _seed_round(settings, *, run_id: str, started_at: datetime, bad_json=False):
    with connect(settings.db_path) as conn:
        now = started_at.isoformat()
        task_id = conn.execute(
            """
            INSERT INTO search_tasks(
                keyword, source, status, created_at, updated_at,
                last_started_at, last_finished_at
            ) VALUES (?, 'web-test', 'completed', ?, ?, ?, ?)
            """,
            (
                f"keyword-{run_id}",
                now,
                now,
                now,
                (started_at + timedelta(minutes=8)).isoformat(),
            ),
        ).lastrowid
        product_id = conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, share_url, first_seen_at, last_seen_at
            ) VALUES (?, 'fixture', ?, ?, ?)
            """,
            (
                f"product-{run_id}",
                f"https://xhslink.com/m/{run_id}",
                now,
                now,
            ),
        ).lastrowid
        observation_id = conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, screenshot_path, sales_7d_min
            ) VALUES (?, ?, 'web-test', ?, 88)
            """,
            (product_id, now, f"evidence/{run_id}.png"),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                task_id, product_id, observation_id, source_keyword, result_rank,
                search_probe_dir, recorded_at, valid
            ) VALUES (?, ?, ?, ?, 1, ?, ?, 1)
            """,
            (
                task_id,
                product_id,
                observation_id,
                f"keyword-{run_id}",
                f"probe/{run_id}",
                now,
            ),
        )
        record_run_event(
            conn,
            run_id=run_id,
            phase="monitor",
            event="monitor_once_started",
            task_id=task_id,
            data={"limits": {"dry_run": False}},
        )
        conn.execute(
            """
            UPDATE run_events SET event_at=?
            WHERE run_id=? AND event='monitor_once_started'
            """,
            (now, run_id),
        )
        record_run_event(
            conn,
            run_id=run_id,
            phase="search_ui",
            event="back_to_search_results",
            task_id=task_id,
            product_id=product_id,
            observation_id=observation_id,
        )
        record_run_event(
            conn,
            run_id=run_id,
            phase="monitor",
            event="monitor_once_finished",
            task_id=task_id,
            product_id=product_id,
            observation_id=observation_id,
            data={"captured_products": 1, "blocked": None, "busy": False},
        )
        conn.execute(
            """
            UPDATE run_events SET event_at=?
            WHERE run_id=? AND event='monitor_once_finished'
            """,
            ((started_at + timedelta(minutes=8)).isoformat(), run_id),
        )
        if bad_json:
            conn.execute(
                """
                UPDATE run_events SET data_json='{bad json'
                WHERE run_id=? AND event='monitor_once_finished'
                """,
                (run_id,),
            )


def _scheduler_record(
    settings,
    *,
    stage: str,
    index: int,
    scheduled_at: datetime,
    source: str = "real",
    **overrides,
):
    artifact_dir = settings.root / "evidence" / "scheduler-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for kind in ("db", "http", "round"):
        path = artifact_dir / f"{stage.lower()}-{index}-{kind}.json"
        path.write_text(json.dumps({"kind": kind}), encoding="utf-8")
        artifacts[kind] = path
    started_at = scheduled_at + timedelta(minutes=2)
    finished_at = started_at + timedelta(minutes=3)
    record = {
        "record_id": f"web-record-{stage.lower()}-{index}",
        "stage": stage,
        "soak_id": "web-offline-fixture",
        "due_point_id": f"web-due-{stage.lower()}-{index}",
        "evidence_source": source,
        "scheduled_at": scheduled_at.isoformat(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "start_delay_seconds": 120,
        "duration_seconds": 180,
        "result": "completed",
        "run_id": f"web-scheduler-{stage.lower()}-{index}",
        "task_id": index + 1,
        "product_id": 100 + index,
        "observation_id": 200 + index,
        "keyword": f"web-keyword-{stage.lower()}-{index}",
        "keyword_source": "portfolio",
        "portfolio_cursor_before": index,
        "portfolio_cursor_after": index + 1,
        "portfolio_selected": [f"web-keyword-{stage.lower()}-{index}"],
        "portfolio_deferred_reason": None,
        "risk_stop_reason": None,
        "last_block_reason": None,
        "last_skip_reason": None,
        "run_lease_owner": f"web-scheduler-{stage.lower()}-{index}",
        "task_lease_owner": f"web-scheduler-{stage.lower()}-{index}",
        "lease_state": "released",
        "desired_state": "running",
        "scheduler_running": True,
        "scheduler_thread_alive": True,
        "scheduler_worker_state": "running",
        "db_status": "ok",
        "sqlite_error": None,
        "db_evidence_path": artifacts["db"],
        "http_status": {
            "api_status": 200,
            "monitor_status": 200,
            "candidates_csv": 200,
        },
        "http_evidence_path": artifacts["http"],
        "evidence_paths": [artifacts["round"]],
        "operator_ack_refs": [],
    }
    record.update(overrides)
    if "start_delay_seconds" in overrides and "started_at" not in overrides:
        delayed_start = scheduled_at + timedelta(
            seconds=float(record["start_delay_seconds"])
        )
        record["started_at"] = delayed_start.isoformat()
        record["finished_at"] = (
            delayed_start + timedelta(seconds=float(record["duration_seconds"]))
        ).isoformat()
    return record


def _install_scheduler_files(
    settings,
    *,
    source: str = "real",
    record_overrides: dict | None = None,
):
    ledger = settings.root / "evidence" / "scheduler-evidence.jsonl"
    expected = {
        "G2": [(BASE + timedelta(hours=index)).isoformat() for index in range(3)],
        "G4": [(BASE + timedelta(hours=index)).isoformat() for index in range(7)],
    }
    for stage, values in expected.items():
        for index, value in enumerate(values):
            append_scheduler_evidence(
                ledger,
                allowed_roots=[settings.root],
                evidence=_scheduler_record(
                    settings,
                    stage=stage,
                    index=index,
                    scheduled_at=datetime.fromisoformat(value),
                    source=source,
                    **(record_overrides or {}),
                ),
            )
    expected_path = settings.root / "evidence" / "scheduler-expected.json"
    expected_path.write_text(
        json.dumps(expected, ensure_ascii=False),
        encoding="utf-8",
    )
    return ledger, expected_path, expected


def test_soak_readiness_returns_all_gates_gaps_scope_and_no_authorization(tmp_path):
    settings = Settings.load(tmp_path)
    for index in range(7):
        _seed_round(
            settings,
            run_id=f"web-real-{index}",
            started_at=BASE + timedelta(hours=index),
        )

    before = _table_counts(settings.db_path)
    result = _route(settings)()
    after = _table_counts(settings.db_path)

    assert before == after
    assert list(result["gates"]) == [f"G{index}" for index in range(7)]
    assert result["summary"]["real_round_count"] == 7
    assert result["summary"]["wall_clock_span_hours"] >= 6
    assert result["gates"]["G0"]["status"] == "failed"
    assert result["gates"]["G1"]["status"] == "passed"
    assert result["gates"]["G2"]["status"] != "passed"
    scheduler = result["record"]["scheduler_evidence"]
    assert scheduler["ledger_location"] == "evidence/scheduler-evidence.jsonl"
    assert scheduler["expected_location"] == "evidence/scheduler-expected.json"
    assert scheduler["request_path_override_allowed"] is False
    assert scheduler["stages"]["G2"]["ready"] is False
    assert scheduler["stages"]["G4"]["ready"] is False
    assert "scheduler_evidence_ledger_missing" in result["warnings"]
    assert "scheduler_expected_missing" in result["warnings"]
    assert result["gaps"]
    assert result["ack_readiness"] == {
        "required": False,
        "ready": True,
        "source": "not_required",
        "required_alert_ids": [],
        "acknowledged_alert_ids": [],
        "missing_alert_ids": [],
        "unresolved_alert_ids": [],
        "latest_decisions": {},
        "integrity_error": None,
        "evidence_mismatches": [],
        "ledger_location": "acks/soak-ack.jsonl",
        "ledger_access": "read_only_when_required",
        "request_path_override_allowed": False,
    }
    assert result["record"]["schema_version"] == 1
    assert result["evidence_scope"]["database_access"] == "sqlite_mode_ro_query_only"
    assert result["evidence_scope"]["rounds_read"] == 7
    assert result["evidence_scope"]["database_write"] is False
    assert result["evidence_scope"]["monitor_trigger"] is False
    assert result["soak_start_authorized"] is False
    assert result["authorization"]["expansion_authorized"] is False
    assert "不授权启动" in result["authorization"]["statement"]


def test_complete_real_scheduler_files_are_bound_to_g2_g4_and_read_only(tmp_path):
    settings = Settings.load(tmp_path)
    for index in range(7):
        _seed_round(
            settings,
            run_id=f"web-scheduler-real-{index}",
            started_at=BASE + timedelta(hours=index),
        )
    _install_scheduler_files(settings)

    before = _table_counts(settings.db_path)
    result = _route(settings)()
    after = _table_counts(settings.db_path)

    scheduler = result["record"]["scheduler_evidence"]
    assert before == after
    assert scheduler["source"] == "ledger"
    assert scheduler["ledger_integrity_ok"] is True
    assert scheduler["integrity_error"] is None
    assert scheduler["stages"]["G2"]["ready"] is True
    assert scheduler["stages"]["G4"]["ready"] is True
    assert scheduler["stages"]["G2"]["expected_scheduled_at"] == (
        scheduler["stages"]["G2"]["recorded_scheduled_at"]
    )
    assert scheduler["stages"]["G4"]["expected_span_hours"] == 6.0
    # The scheduler dimension is complete, but legacy SQLite rounds do not
    # contain scheduled_at. T49 keeps the aggregate G2 gate fail closed.
    assert result["gates"]["G2"]["status"] != "passed"
    assert result["soak_start_authorized"] is False
    assert result["authorization"]["expansion_authorized"] is False


def test_bad_scheduler_expected_json_preserves_g1_but_closes_g2_g4(tmp_path):
    settings = Settings.load(tmp_path)
    for index in range(3):
        _seed_round(
            settings,
            run_id=f"web-bad-expected-{index}",
            started_at=BASE + timedelta(hours=index),
        )
    _, expected_path, _ = _install_scheduler_files(settings)
    expected_path.write_text("{bad json", encoding="utf-8")

    result = _route(settings)()

    scheduler = result["record"]["scheduler_evidence"]
    assert result["gates"]["G1"]["status"] == "passed"
    assert result["gates"]["G2"]["status"] != "passed"
    assert result["gates"]["G4"]["status"] != "passed"
    assert scheduler["stages"]["G2"]["ready"] is False
    assert scheduler["stages"]["G4"]["ready"] is False
    assert any(
        warning.startswith("scheduler_expected_invalid:JSONDecodeError")
        for warning in result["warnings"]
    )
    assert any(
        "必须是 G2/G4" in reason
        for stage in scheduler["stages"].values()
        for reason in stage["failed_reasons"]
    )


def test_missing_scheduler_due_point_is_visible_in_record_gap_and_warning(tmp_path):
    settings = Settings.load(tmp_path)
    for index in range(7):
        _seed_round(
            settings,
            run_id=f"web-missing-due-{index}",
            started_at=BASE + timedelta(hours=index),
        )
    _, expected_path, expected = _install_scheduler_files(settings)
    missing_at = (BASE + timedelta(hours=8)).isoformat()
    expected["G2"].append(missing_at)
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    result = _route(settings)()

    g2 = result["record"]["scheduler_evidence"]["stages"]["G2"]
    assert g2["ready"] is False
    assert g2["missing_scheduled_at"] == [missing_at]
    assert result["gates"]["G2"]["status"] != "passed"
    assert any(item["gate"] == "G2" for item in result["gaps"])
    assert any("缺少预期到期点" in warning for warning in result["warnings"])


def test_corrupt_scheduler_ledger_is_visible_and_fails_closed(tmp_path):
    settings = Settings.load(tmp_path)
    for index in range(7):
        _seed_round(
            settings,
            run_id=f"web-corrupt-ledger-{index}",
            started_at=BASE + timedelta(hours=index),
        )
    ledger, _, _ = _install_scheduler_files(settings)
    ledger.write_text("{bad json}\n", encoding="utf-8")

    result = _route(settings)()

    scheduler = result["record"]["scheduler_evidence"]
    assert scheduler["ledger_integrity_ok"] is False
    assert scheduler["integrity_error"]
    assert scheduler["stages"]["G2"]["ready"] is False
    assert scheduler["stages"]["G4"]["ready"] is False
    assert result["gates"]["G2"]["status"] != "passed"
    assert result["gates"]["G4"]["status"] != "passed"
    assert any(
        warning.startswith("scheduler_evidence_integrity_error:")
        for warning in result["warnings"]
    )


@pytest.mark.parametrize(
    ("source", "overrides", "reason_fragment"),
    [
        ("simulated", {}, "simulated"),
        ("real", {"start_delay_seconds": 901}, "start delay"),
        ("real", {"risk_stop_reason": "offline-risk"}, "risk"),
        ("real", {"scheduler_thread_alive": False}, "thread"),
    ],
)
def test_scheduler_simulation_delay_risk_and_health_close_gates(
    tmp_path,
    source,
    overrides,
    reason_fragment,
):
    settings = Settings.load(tmp_path)
    for index in range(7):
        _seed_round(
            settings,
            run_id=f"web-unhealthy-{reason_fragment}-{index}",
            started_at=BASE + timedelta(hours=index),
        )
    _install_scheduler_files(
        settings,
        source=source,
        record_overrides=overrides,
    )

    result = _route(settings)()

    scheduler = result["record"]["scheduler_evidence"]
    assert scheduler["stages"]["G2"]["ready"] is False
    assert scheduler["stages"]["G4"]["ready"] is False
    assert result["gates"]["G2"]["status"] != "passed"
    assert result["gates"]["G4"]["status"] != "passed"
    assert any(
        reason_fragment.casefold() in reason.casefold()
        for stage in scheduler["stages"].values()
        for reason in stage["failed_reasons"]
    )
    assert any(
        reason_fragment.casefold() in warning.casefold()
        for warning in result["warnings"]
    )


def test_soak_readiness_missing_database_fails_closed(tmp_path):
    settings = Settings.load(tmp_path)
    settings.db_path.unlink(missing_ok=True)

    result = _route(settings)()

    assert result["summary"]["round_count"] == 0
    assert all(
        decision["status"] != "passed" for decision in result["gates"].values()
    )
    assert result["soak_start_authorized"] is False
    assert result["warnings"][-1] == "readonly_database_unavailable:OperationalError"


def test_soak_readiness_bad_event_json_is_warned_and_fails_closed(tmp_path):
    settings = Settings.load(tmp_path)
    _seed_round(settings, run_id="bad-json", started_at=BASE, bad_json=True)

    result = _route(settings)()

    assert result["evidence_scope"]["malformed_json_count"] == 1
    assert "malformed_run_event_json:1" in result["warnings"]
    assert result["summary"]["successful_round_count"] == 0
    assert result["gates"]["G1"]["status"] != "passed"
    assert result["gaps"][-1]["gate"] == "EVIDENCE_INTEGRITY"
    assert result["ready_for_pre_soak"] is False
    assert result["ready_for_24h_soak"] is False
    assert result["soak_start_authorized"] is False


def test_soak_readiness_connection_enforces_query_only(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    captured = {}

    def inspect_connection(
        conn,
        *,
        target,
        ack_ledger_path,
        ack_allowed_roots,
        scheduler_evidence_ledger_path,
        scheduler_evidence_allowed_roots,
        expected_scheduler_scheduled_at,
        baseline_manifest_path,
        baseline_allowed_roots,
    ):
        captured["target"] = target
        captured["query_only"] = conn.execute("PRAGMA query_only").fetchone()[0]
        captured["ack_ledger_path"] = ack_ledger_path
        captured["ack_allowed_roots"] = ack_allowed_roots
        captured["scheduler_evidence_ledger_path"] = (
            scheduler_evidence_ledger_path
        )
        captured["scheduler_evidence_allowed_roots"] = (
            scheduler_evidence_allowed_roots
        )
        captured["expected_scheduler_scheduled_at"] = (
            expected_scheduler_scheduled_at
        )
        captured["baseline_manifest_path"] = baseline_manifest_path
        captured["baseline_allowed_roots"] = baseline_allowed_roots
        try:
            conn.execute("CREATE TABLE forbidden_write(id INTEGER)")
        except sqlite3.OperationalError:
            captured["write_blocked"] = True
        else:
            captured["write_blocked"] = False
        from xhs_scout.soak_readiness import evaluate_soak_readiness

        return evaluate_soak_readiness({"rounds": []}, target=target)

    monkeypatch.setattr(
        "xhs_scout.web.evaluate_sqlite_readiness",
        inspect_connection,
    )

    result = _route(settings)()

    assert captured["target"] == "pre_soak"
    assert captured["query_only"] == 1
    assert captured["write_blocked"] is True
    assert captured["ack_ledger_path"] == (
        settings.root / "acks" / "soak-ack.jsonl"
    )
    assert captured["ack_allowed_roots"] == (settings.root,)
    assert captured["scheduler_evidence_ledger_path"] == (
        settings.root / "evidence" / "scheduler-evidence.jsonl"
    )
    assert captured["scheduler_evidence_allowed_roots"] == (settings.root,)
    assert captured["expected_scheduler_scheduled_at"] is None
    assert captured["baseline_manifest_path"] == (
        settings.root / "evidence" / "soak-baseline.json"
    )
    assert captured["baseline_allowed_roots"] == (settings.root,)
    assert result["evidence_scope"]["database_access"] == "sqlite_mode_ro_query_only"


def test_missing_fixed_baseline_is_visible_and_fails_closed(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass

    result = _route(settings)()

    baseline = result["record"]["baseline"]
    assert baseline["status"] == "failed"
    assert baseline["source"] == "path"
    assert baseline["integrity_ok"] is False
    assert baseline["manifest_location"] == "evidence/soak-baseline.json"
    assert baseline["manifest_access"] == "read_only"
    assert baseline["request_path_override_allowed"] is False
    assert baseline["authorizes_start"] is False
    assert "soak_baseline_missing" in result["warnings"]
    assert any(
        "baseline 路径校验失败" in reason
        for item in result["gaps"]
        if item["gate"] == "G0"
        for reason in item["reasons"]
    )
    assert result["ready_for_pre_soak"] is False
    assert result["ready_for_24h_soak"] is False
    assert result["soak_start_authorized"] is False
    assert result["authorization"]["expansion_authorized"] is False


def test_fixed_baseline_path_is_passed_to_t56_and_reverified(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    manifest, _, _ = _write_baseline(settings)

    result = _route(settings)()

    baseline = result["record"]["baseline"]
    assert baseline["status"] == "passed"
    assert baseline["source"] == "path"
    assert baseline["integrity_ok"] is True
    assert baseline["files_reverified"] is True
    assert baseline["baseline_id"] == manifest.baseline_id
    assert baseline["manifest_hash"] == manifest.manifest_hash
    assert "soak_baseline_missing" not in result["warnings"]
    assert result["soak_start_authorized"] is False
    assert result["authorization"]["expansion_authorized"] is False


@pytest.mark.parametrize("failure", ["bad_json", "bad_hash", "file_drift"])
def test_invalid_or_drifted_fixed_baseline_fails_closed(tmp_path, failure):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    _, manifest_path, code_path = _write_baseline(settings)
    if failure == "bad_json":
        manifest_path.write_text("{bad json}\n", encoding="utf-8")
    elif failure == "bad_hash":
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["manifest_hash"] = "0" * 64
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        code_path.write_text("VALUE = 2\n", encoding="utf-8")

    result = _route(settings)()

    baseline = result["record"]["baseline"]
    assert baseline["status"] == "failed"
    assert baseline["integrity_ok"] is False
    assert any(
        warning.startswith("soak_baseline:baseline 路径校验失败")
        for warning in result["warnings"]
    )
    assert any(
        "baseline 路径校验失败" in reason
        for item in result["gaps"]
        if item["gate"] == "G0"
        for reason in item["reasons"]
    )
    assert result["ready_for_pre_soak"] is False
    assert result["ready_for_24h_soak"] is False
    assert result["soak_start_authorized"] is False
    assert result["authorization"]["expansion_authorized"] is False


def test_critical_alert_without_ledger_fails_closed(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    alert_id = _install_critical_alert(monkeypatch)

    result = _route(settings)()

    ack = result["ack_readiness"]
    assert ack["required"] is True
    assert ack["ready"] is False
    assert ack["source"] == "ledger"
    assert ack["required_alert_ids"] == [alert_id]
    assert ack["missing_alert_ids"] == [alert_id]
    assert result["ready_for_pre_soak"] is False
    assert result["ready_for_24h_soak"] is False
    assert any(item["gate"] == "G3" for item in result["gaps"])
    assert any("ACK" in warning for warning in result["warnings"])


def test_valid_ack_ledger_is_exposed_without_authorizing_soak(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    alert_id = _install_critical_alert(monkeypatch)
    _append_ack(settings, alert_id=alert_id)

    result = _route(settings)()

    ack = result["ack_readiness"]
    assert ack["ready"] is True
    assert ack["acknowledged_alert_ids"] == [alert_id]
    assert ack["latest_decisions"] == {alert_id: "acknowledge"}
    assert ack["integrity_error"] is None
    assert result["soak_start_authorized"] is False
    assert result["authorization"]["expansion_authorized"] is False


@pytest.mark.parametrize("decision", ["reject", "defer"])
def test_non_ack_latest_decision_fails_closed(tmp_path, monkeypatch, decision):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    alert_id = _install_critical_alert(monkeypatch)
    _append_ack(settings, alert_id=alert_id, decision=decision)

    result = _route(settings)()

    ack = result["ack_readiness"]
    assert ack["ready"] is False
    assert ack["unresolved_alert_ids"] == [alert_id]
    assert ack["latest_decisions"] == {alert_id: decision}
    assert any(
        "最新决定不是 acknowledge" in reason
        for item in result["gaps"]
        for reason in item["reasons"]
    )


def test_corrupt_ack_ledger_fails_closed(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    alert_id = _install_critical_alert(monkeypatch)
    ledger_path = settings.root / "acks" / "soak-ack.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("{bad json}\n", encoding="utf-8")

    result = _route(settings)()

    ack = result["ack_readiness"]
    assert ack["ready"] is False
    assert ack["integrity_error"]
    assert ack["missing_alert_ids"] == [alert_id]
    assert any(
        "损坏" in reason
        for item in result["gaps"]
        for reason in item["reasons"]
    )


def test_ack_for_different_alert_id_fails_closed(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    required_alert_id = _install_critical_alert(monkeypatch)
    _append_ack(settings, alert_id="different-critical-id")

    result = _route(settings)()

    ack = result["ack_readiness"]
    assert ack["ready"] is False
    assert ack["required_alert_ids"] == [required_alert_id]
    assert ack["acknowledged_alert_ids"] == []
    assert ack["missing_alert_ids"] == [required_alert_id]


def test_ack_path_is_fixed_inside_project_root(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    outside_name = f"{tmp_path.name}-outside"
    monkeypatch.setattr(
        web_module,
        "_SOAK_ACK_LEDGER_RELATIVE",
        Path("..") / outside_name / "soak-ack.jsonl",
    )
    called = False

    def must_not_evaluate(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("unsafe ACK path must be rejected before evaluation")

    monkeypatch.setattr(web_module, "evaluate_sqlite_readiness", must_not_evaluate)

    result = _route(settings)()

    assert called is False
    assert result["summary"]["round_count"] == 0
    assert result["warnings"][-1] == "soak_evidence_unavailable:ValueError"
    assert result["soak_start_authorized"] is False


@pytest.mark.parametrize(
    "constant_name",
    [
        "_SCHEDULER_EVIDENCE_LEDGER_RELATIVE",
        "_SCHEDULER_EXPECTED_RELATIVE",
    ],
)
def test_scheduler_paths_are_fixed_inside_project_root(
    tmp_path,
    monkeypatch,
    constant_name,
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    monkeypatch.setattr(
        web_module,
        constant_name,
        Path("..") / "outside-scheduler-evidence",
    )
    called = False

    def must_not_evaluate(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError(
            "unsafe scheduler path must be rejected before evaluation"
        )

    monkeypatch.setattr(web_module, "evaluate_sqlite_readiness", must_not_evaluate)

    result = _route(settings)()

    assert called is False
    assert result["summary"]["round_count"] == 0
    assert result["warnings"][-1] == "soak_evidence_unavailable:ValueError"
    assert result["gates"]["G2"]["status"] != "passed"
    assert result["gates"]["G4"]["status"] != "passed"
    assert result["soak_start_authorized"] is False


def test_baseline_path_is_fixed_inside_project_root(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    monkeypatch.setattr(
        web_module,
        "_SOAK_BASELINE_RELATIVE",
        Path("..") / "outside-soak-baseline.json",
    )
    called = False

    def must_not_evaluate(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("unsafe baseline path must be rejected before evaluation")

    monkeypatch.setattr(web_module, "evaluate_sqlite_readiness", must_not_evaluate)

    result = _route(settings)()

    assert called is False
    assert result["summary"]["round_count"] == 0
    assert result["warnings"][-1] == "soak_evidence_unavailable:ValueError"
    assert any(
        "soak baseline path must be a fixed project-relative path" in reason
        for item in result["gaps"]
        if item["gate"] == "INPUT_INTEGRITY"
        for reason in item["reasons"]
    )
    assert result["gates"]["G0"]["status"] != "passed"
    assert result["soak_start_authorized"] is False
    assert result["authorization"]["expansion_authorized"] is False


def test_soak_readiness_surface_is_get_only_and_preserves_adjacent_routes(tmp_path):
    settings = Settings.load(tmp_path)
    routes = [
        route
        for route in create_app(settings).routes
        if getattr(route, "path", "") in {
            "/api/soak-readiness",
            "/api/keyword-suggestions",
            "/api/remediation-plan",
        }
    ]

    assert [(route.path, route.methods) for route in routes] == [
        ("/api/keyword-suggestions", {"GET"}),
        ("/api/remediation-plan", {"GET"}),
        ("/api/soak-readiness", {"GET"}),
    ]
    endpoint = next(route.endpoint for route in routes if route.path == "/api/soak-readiness")
    assert list(inspect.signature(endpoint).parameters) == []
