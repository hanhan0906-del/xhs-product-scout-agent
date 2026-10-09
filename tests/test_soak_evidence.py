import json
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from xhs_scout.db import connect, record_run_event, set_monitor_state
from xhs_scout.scheduler_evidence import (
    append_scheduler_evidence,
    evaluate_scheduler_evidence,
)
from xhs_scout.soak_ack import append_soak_ack, evaluate_ack_readiness
from xhs_scout.soak_baseline import (
    build_baseline_manifest,
    write_baseline_manifest,
)
from xhs_scout.soak_readiness import (
    ELIGIBLE,
    INSUFFICIENT,
    NOT_REACHED,
    PASS,
    evaluate_soak_readiness,
    evaluate_sqlite_readiness,
    load_sqlite_evidence,
)


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 7, 29, 8, 0, tzinfo=TZ)


def _round(index, *, hours=None, source_kind="real", keyword=None):
    at = BASE + timedelta(hours=index if hours is None else hours)
    return {
        "sequence": index + 1,
        "run_id": f"monitor-real-{index}",
        "task_id": index + 1,
        "keyword": keyword or f"keyword-{index}",
        "scheduled_at": at.isoformat(),
        "started_at": (at + timedelta(minutes=2)).isoformat(),
        "finished_at": (at + timedelta(minutes=8)).isoformat(),
        "result": "completed",
        "success": True,
        "product_id": 100 + index,
        "observation_id": 200 + index,
        "search_recovered": True,
        "share_url": f"https://xhslink.com/m/product{index}",
        "metrics": {"sales_7d_min": 10 + index},
        "evidence_path": f"data/probes/round-{index}",
        "source_kind": source_kind,
    }


def _snapshots():
    return {
        "digest_snapshots": [
            {"phase": phase, "alerts": []} for phase in ("start", "mid", "end")
        ],
        "quality_snapshots": [
            {
                "phase": phase,
                "summary": {"by_severity": {"error": 0}},
                "acknowledged": True,
            }
            for phase in ("start", "mid", "end")
        ],
    }


def _base_bundle(rounds):
    return {
        "soak_id": "offline-unit",
        "evidence_kind": "real",
        "rounds": rounds,
        "offline_tests_passed": True,
        "sqlite_stress_passed": True,
        "scheduler_recovery_tested": True,
        "lease_safety_tested": True,
        "lease_recovery_verified": True,
        "scheduler_recovery_verified": True,
        "risk_recovery_verified": True,
        "leases": [],
        "tasks": [],
        **_snapshots(),
    }


def _baseline_values(root):
    project = root / "baseline-project"
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "config").mkdir(exist_ok=True)
    (project / "src" / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project / "config" / "settings.json").write_text(
        '{"enabled":true}\n',
        encoding="utf-8",
    )
    return {
        "project_root": project,
        "code_files": ["src/worker.py"],
        "config_files": ["config/settings.json"],
        "database_statistics": {"quick_check": "ok", "run_count": 3},
        "run_parameters": {
            "interval_seconds": 3600,
            "max_keywords": 1,
            "max_products_per_keyword": 1,
        },
        "port_owners": {
            "8793": {"owner": "offline fixture owner"},
            "8765": {"owner": "isolated other fixture"},
        },
        "disk_summary": {"status": "caller supplied"},
        "log_summary": {"error_count": 0},
        "operator": "operator-a",
        "stop_entry": {"procedure": "pause and wait for the current round"},
    }


def _baseline(root):
    return build_baseline_manifest(**_baseline_values(root))


def _rehash_baseline(payload):
    unsigned = {
        "schema_version": payload["schema_version"],
        "manifest_kind": payload["manifest_kind"],
        "status": payload["status"],
        "sources": payload["sources"],
        "safety": payload["safety"],
    }
    content_hash = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload["baseline_id"] = f"pre-soak-baseline-{content_hash[:16]}"
    signed = {"baseline_id": payload["baseline_id"], **unsigned}
    payload["manifest_hash"] = hashlib.sha256(
        json.dumps(
            signed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _scheduler_record(
    root,
    index,
    *,
    stage,
    scheduled_at,
    source="real",
    **overrides,
):
    artifact_dir = root / "scheduler-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for kind in ("db", "http", "round"):
        path = artifact_dir / f"{stage.lower()}-{index}-{kind}.json"
        path.write_text(json.dumps({"kind": kind}), encoding="utf-8")
        artifacts[kind] = path
    scheduled = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
    started = scheduled + timedelta(minutes=2)
    finished = started + timedelta(minutes=6)
    value = {
        "record_id": f"record-{stage.lower()}-{index}",
        "stage": stage,
        "soak_id": "offline-unit",
        "due_point_id": f"due-{stage.lower()}-{index}",
        "evidence_source": source,
        "scheduled_at": scheduled.isoformat(),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "start_delay_seconds": 120,
        "duration_seconds": 360,
        "result": "completed",
        "run_id": f"monitor-{stage.lower()}-{index}",
        "task_id": index + 1,
        "product_id": 100 + index,
        "observation_id": 200 + index,
        "keyword": f"{stage.lower()}-keyword-{index}",
        "keyword_source": "portfolio",
        "portfolio_cursor_before": index,
        "portfolio_cursor_after": index + 1,
        "portfolio_selected": [f"{stage.lower()}-keyword-{index}"],
        "portfolio_deferred_reason": None,
        "risk_stop_reason": None,
        "last_block_reason": None,
        "last_skip_reason": None,
        "run_lease_owner": f"monitor-{stage.lower()}-{index}",
        "task_lease_owner": f"monitor-{stage.lower()}-{index}",
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
    value.update(overrides)
    return value


def _scheduler_inputs(tmp_path, rounds, *, stages=("G2", "G4")):
    ledger = tmp_path / "scheduler-evidence.jsonl"
    expected = {}
    for stage in stages:
        stage_rounds = rounds[:3] if stage == "G2" else rounds
        expected[stage] = [row["scheduled_at"] for row in stage_rounds]
        for index, row in enumerate(stage_rounds):
            append_scheduler_evidence(
                ledger,
                allowed_roots=[tmp_path],
                evidence=_scheduler_record(
                    tmp_path,
                    index,
                    stage=stage,
                    scheduled_at=row["scheduled_at"],
                ),
            )
    return {
        "scheduler_evidence_ledger_path": ledger,
        "scheduler_evidence_allowed_roots": [tmp_path],
        "expected_scheduler_scheduled_at": expected,
    }


def _critical_alert(bundle, *, alert_id="digest-critical-001"):
    bundle["digest_snapshots"][1]["alerts"] = [
        {
            "alert_id": alert_id,
            "severity": "critical",
            "title": "需要人工判定",
        }
    ]
    return alert_id


def _ack_ledger(
    tmp_path,
    alert_id,
    *,
    decision="acknowledge",
    alert_kind="critical",
):
    evidence_path = tmp_path / "evidence" / f"{alert_id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text('{"status":"reviewed"}', encoding="utf-8")
    ledger_path = tmp_path / "acks" / "soak-ack.jsonl"
    append_soak_ack(
        ledger_path,
        allowed_roots=[tmp_path],
        record_id=f"record-{decision}",
        alert_id=alert_id,
        alert_kind=alert_kind,
        actor="operator-a",
        decision=decision,
        evidence_path=evidence_path,
        note="offline readiness review",
        decided_at=BASE,
    )
    return ledger_path


def test_baseline_must_be_supplied_explicitly_and_is_auditable(tmp_path):
    manifest = _baseline(tmp_path)
    bundle = _base_bundle([])
    bundle["baseline_manifest"] = manifest

    missing = evaluate_soak_readiness(bundle)
    accepted = evaluate_soak_readiness(bundle, baseline_manifest=manifest)

    assert missing.summary["baseline_status"] == INSUFFICIENT
    assert missing.summary["baseline_source"] == "not_provided"
    assert missing.gates["G0"].status == INSUFFICIENT
    assert "显式提供" in missing.summary["baseline"]["gaps"][0]
    assert any("baseline 未通过" in warning for warning in missing.warnings)
    assert missing.ready_for_pre_soak is False
    assert accepted.summary["baseline_status"] == PASS
    assert accepted.summary["baseline_integrity_ok"] is True
    assert accepted.summary["baseline_id"] == manifest.baseline_id
    assert accepted.record["baseline"]["files_reverified"] is True


def test_baseline_path_requires_allowed_roots_and_reverifies_files(tmp_path):
    manifest = _baseline(tmp_path)
    manifest_path = write_baseline_manifest(
        tmp_path / "baseline-project" / "baseline.json",
        manifest,
        allowed_roots=[tmp_path],
    )

    missing_roots = evaluate_soak_readiness(
        _base_bundle([]),
        baseline_manifest_path=manifest_path,
    )
    accepted = evaluate_soak_readiness(
        _base_bundle([]),
        baseline_manifest_path=manifest_path,
        baseline_allowed_roots=[tmp_path],
    )

    assert missing_roots.summary["baseline_status"] == "failed"
    assert "allowed_roots" in missing_roots.summary["baseline"]["gaps"][0]
    assert accepted.summary["baseline_status"] == PASS
    assert accepted.summary["baseline_source"] == "path"
    assert accepted.summary["baseline_manifest_hash"] == manifest.manifest_hash


def test_corrupt_hash_and_observed_file_drift_fail_baseline_closed(tmp_path):
    manifest = _baseline(tmp_path)
    bad_hash = manifest.as_dict()
    bad_hash["manifest_hash"] = "0" * 64
    hash_report = evaluate_soak_readiness(
        _base_bundle([]),
        baseline_manifest=bad_hash,
    )

    (tmp_path / "baseline-project" / "src" / "worker.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    drift_report = evaluate_soak_readiness(
        _base_bundle([]),
        baseline_manifest=manifest,
    )

    assert hash_report.summary["baseline_status"] == "failed"
    assert "integrity hash" in hash_report.summary["baseline"]["gaps"][0]
    assert hash_report.gates["G0"].status == "failed"
    assert drift_report.summary["baseline_status"] == "failed"
    assert "changed after baseline" in drift_report.summary["baseline"]["gaps"][0]
    assert drift_report.ready_for_pre_soak is False


def test_corrupt_baseline_path_fails_closed_without_raising(tmp_path):
    path = tmp_path / "broken-baseline.json"
    path.write_text("{not json}\n", encoding="utf-8")

    report = evaluate_soak_readiness(
        _base_bundle([]),
        baseline_manifest_path=path,
        baseline_allowed_roots=[tmp_path],
    )

    assert report.summary["baseline_status"] == "failed"
    assert report.summary["baseline_integrity_ok"] is False
    assert report.gates["G0"].status == "failed"
    assert report.ready_for_24h_soak is False


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (
            lambda payload: payload["sources"]["caller_supplied"][
                "port_owners"
            ].pop("8793"),
            "8793 and 8765",
        ),
        (
            lambda payload: payload["sources"]["caller_supplied"].update(
                stop_entry={}
            ),
            "stop_entry",
        ),
        (
            lambda payload: payload["sources"]["caller_supplied"][
                "database_statistics"
            ].pop("quick_check"),
            "quick_check",
        ),
        (
            lambda payload: payload["sources"]["caller_supplied"][
                "run_parameters"
            ].pop("max_products_per_keyword"),
            "max_products_per_keyword",
        ),
    ],
)
def test_baseline_missing_owner_stop_db_or_1x1_parameter_fails_readiness(
    tmp_path,
    mutation,
    fragment,
):
    payload = _baseline(tmp_path).as_dict()
    mutation(payload)
    _rehash_baseline(payload)

    report = evaluate_soak_readiness(
        _base_bundle([]),
        baseline_manifest=payload,
    )

    assert report.summary["baseline_status"] == "failed"
    assert fragment in report.summary["baseline"]["gaps"][0]
    assert report.gates["G0"].status == "failed"


@pytest.mark.parametrize(
    "authorization_path",
    ["safety", "caller_supplied"],
)
def test_any_true_authorization_in_baseline_fails_closed(
    tmp_path,
    authorization_path,
):
    payload = _baseline(tmp_path).as_dict()
    if authorization_path == "safety":
        payload["safety"]["pre_soak_start_authorized"] = True
    else:
        payload["sources"]["caller_supplied"]["run_parameters"][
            "manual_authorization"
        ] = True
    _rehash_baseline(payload)

    report = evaluate_soak_readiness(
        _base_bundle([]),
        baseline_manifest=payload,
    )
    result = report.as_dict()

    assert report.summary["baseline_status"] == "failed"
    assert report.gates["G0"].status == "failed"
    assert result["pre_soak_start_authorized"] is False
    assert result["soak_24h_start_authorized"] is False
    assert result["scheduler_start_authorized"] is False
    assert report.record["authorization"]["pre_soak_start_authorized"] is False


def test_mapping_bundle_passes_g0_to_g4_for_real_six_hour_pre_soak(tmp_path):
    rounds = [_round(index) for index in range(7)]
    report = evaluate_soak_readiness(
        _base_bundle(rounds),
        baseline_manifest=_baseline(tmp_path),
        **_scheduler_inputs(tmp_path, rounds),
    )

    assert [report.gates[f"G{index}"].status for index in range(5)] == [PASS] * 5
    assert report.gates["G5"].status == INSUFFICIENT
    assert report.gates["G6"].status == NOT_REACHED
    assert report.ready_for_24h_soak is True
    assert report.summary["successful_round_count"] == 7
    assert report.summary["wall_clock_span_hours"] > 6
    assert report.record["simulation_disclaimer"].startswith("模拟测试不等于真实 soak")
    assert report.summary["ack_source"] == "not_required"
    assert report.summary["ack_ready"] is True


def test_legacy_call_keeps_g1_but_cannot_promote_g2_or_g4_without_scheduler():
    report = evaluate_soak_readiness(
        _base_bundle([_round(index) for index in range(7)])
    )

    assert report.gates["G1"].status == PASS
    assert report.gates["G2"].status == INSUFFICIENT
    assert report.gates["G4"].status == INSUFFICIENT
    assert report.summary["scheduler_evidence_source"] == "not_provided"
    assert any(
        "expected scheduled_at" in reason
        for reason in report.gates["G2"].reasons
    )


def test_complete_real_scheduler_g2_passes_but_does_not_infer_g4(tmp_path):
    rounds = [_round(index) for index in range(7)]
    report = evaluate_soak_readiness(
        _base_bundle(rounds),
        **_scheduler_inputs(tmp_path, rounds, stages=("G2",)),
    )

    assert report.gates["G2"].status == PASS
    assert report.gates["G4"].status == INSUFFICIENT
    assert report.summary["scheduler_evidence_stages"]["G2"]["ready"] is True
    assert report.summary["scheduler_evidence_stages"]["G4"]["ready"] is False


def test_scheduler_ledger_and_explicit_expected_schedule_are_both_required(tmp_path):
    rounds = [_round(index) for index in range(3)]
    inputs = _scheduler_inputs(tmp_path, rounds, stages=("G2",))

    without_expected = evaluate_soak_readiness(
        _base_bundle(rounds),
        scheduler_evidence_ledger_path=inputs["scheduler_evidence_ledger_path"],
        scheduler_evidence_allowed_roots=[tmp_path],
    )
    missing_ledger = evaluate_soak_readiness(
        _base_bundle(rounds),
        scheduler_evidence_ledger_path=tmp_path / "missing.jsonl",
        scheduler_evidence_allowed_roots=[tmp_path],
        expected_scheduler_scheduled_at=inputs[
            "expected_scheduler_scheduled_at"
        ],
    )

    assert without_expected.gates["G2"].status != PASS
    assert any(
        "expected scheduled_at" in reason
        for reason in without_expected.gates["G2"].reasons
    )
    assert missing_ledger.gates["G2"].status != PASS
    assert any(
        "账本缺失或为空" in reason
        for reason in missing_ledger.gates["G2"].reasons
    )


def test_missing_explicit_due_point_is_not_inferred_from_recorded_events(tmp_path):
    rounds = [_round(index) for index in range(3)]
    inputs = _scheduler_inputs(tmp_path, rounds, stages=("G2",))
    inputs["expected_scheduler_scheduled_at"]["G2"][-1] = (
        BASE + timedelta(hours=3)
    ).isoformat()

    report = evaluate_soak_readiness(_base_bundle(rounds), **inputs)

    assert report.gates["G2"].status == "failed"
    assert report.summary["scheduler_evidence_stages"]["G2"][
        "missing_scheduled_at"
    ] == [(BASE + timedelta(hours=3)).isoformat(timespec="seconds")]
    assert report.summary["scheduler_evidence_stages"]["G2"][
        "unexpected_scheduled_at"
    ] == [(BASE + timedelta(hours=2)).isoformat(timespec="seconds")]


def test_simulated_scheduler_evidence_never_promotes_g2(tmp_path):
    rounds = [_round(index) for index in range(3)]
    ledger = tmp_path / "scheduler-evidence.jsonl"
    expected = []
    for index, row in enumerate(rounds):
        expected.append(row["scheduled_at"])
        append_scheduler_evidence(
            ledger,
            allowed_roots=[tmp_path],
            evidence=_scheduler_record(
                tmp_path,
                index,
                stage="G2",
                scheduled_at=row["scheduled_at"],
                source="simulated",
            ),
        )

    report = evaluate_soak_readiness(
        _base_bundle(rounds),
        scheduler_evidence_ledger_path=ledger,
        scheduler_evidence_allowed_roots=[tmp_path],
        expected_scheduler_scheduled_at={"G2": expected},
    )

    assert report.gates["G2"].status == "failed"
    assert any("simulated" in reason for reason in report.gates["G2"].reasons)


@pytest.mark.parametrize(
    ("case", "updates", "reason"),
    [
        (
            "delay",
            {
                "started_at": (BASE + timedelta(minutes=16)).isoformat(),
                "finished_at": (BASE + timedelta(minutes=22)).isoformat(),
                "start_delay_seconds": 960,
            },
            "start delay exceeds",
        ),
        ("risk_ack", {"risk_stop_reason": "captcha"}, "lack operator ACK"),
        ("block", {"result": "blocked", "last_block_reason": "guard"}, "blocked"),
        ("thread", {"scheduler_thread_alive": False}, "scheduler/thread"),
        (
            "db",
            {"db_status": "error", "sqlite_error": "database is locked"},
            "DB evidence",
        ),
        (
            "http",
            {
                "http_status": {
                    "api_status": 200,
                    "monitor_status": 503,
                    "candidates_csv": 200,
                }
            },
            "HTTP evidence",
        ),
        ("lease", {"lease_state": "lost"}, "lease state"),
    ],
)
def test_scheduler_health_failures_close_g2(tmp_path, case, updates, reason):
    rounds = [_round(index) for index in range(3)]
    ledger = tmp_path / "scheduler-evidence.jsonl"
    expected = []
    for index, row in enumerate(rounds):
        expected.append(row["scheduled_at"])
        record_updates = updates if index == 0 else {}
        append_scheduler_evidence(
            ledger,
            allowed_roots=[tmp_path],
            evidence=_scheduler_record(
                tmp_path,
                index,
                stage="G2",
                scheduled_at=row["scheduled_at"],
                **record_updates,
            ),
        )

    report = evaluate_soak_readiness(
        _base_bundle(rounds),
        scheduler_evidence_ledger_path=ledger,
        scheduler_evidence_allowed_roots=[tmp_path],
        expected_scheduler_scheduled_at={"G2": expected},
    )

    assert report.gates["G2"].status == "failed", case
    assert any(reason in item for item in report.gates["G2"].reasons)


def test_g4_expected_schedule_must_span_six_hours(tmp_path):
    rounds = [_round(index) for index in range(7)]
    short_g4 = [rounds[index] for index in (0, 2, 4)]
    inputs = _scheduler_inputs(tmp_path, short_g4, stages=("G4",))

    report = evaluate_soak_readiness(_base_bundle(rounds), **inputs)

    assert report.gates["G4"].status == INSUFFICIENT
    assert any("跨度不足 6 小时" in reason for reason in report.gates["G4"].reasons)


def test_g4_unhealthy_scheduler_record_fails_closed(tmp_path):
    rounds = [_round(index) for index in range(7)]
    ledger = tmp_path / "scheduler-evidence.jsonl"
    expected = []
    for index, row in enumerate(rounds):
        expected.append(row["scheduled_at"])
        updates = (
            {
                "risk_stop_reason": "captcha",
                "scheduler_thread_alive": False,
                "db_status": "error",
                "sqlite_error": "database is locked",
                "http_status": {
                    "api_status": 200,
                    "monitor_status": 503,
                    "candidates_csv": 200,
                },
            }
            if index == 3
            else {}
        )
        append_scheduler_evidence(
            ledger,
            allowed_roots=[tmp_path],
            evidence=_scheduler_record(
                tmp_path,
                index,
                stage="G4",
                scheduled_at=row["scheduled_at"],
                **updates,
            ),
        )

    report = evaluate_soak_readiness(
        _base_bundle(rounds),
        scheduler_evidence_ledger_path=ledger,
        scheduler_evidence_allowed_roots=[tmp_path],
        expected_scheduler_scheduled_at={"G4": expected},
    )

    assert report.gates["G4"].status == "failed"
    reasons = " ".join(report.gates["G4"].reasons)
    assert "risk" in reasons
    assert "scheduler/thread" in reasons
    assert "DB evidence" in reasons
    assert "HTTP evidence" in reasons
    assert "lack operator ACK" in reasons


def test_plain_t46_evaluation_cannot_substitute_for_scheduled_at_binding(tmp_path):
    rounds = [_round(index) for index in range(3)]
    inputs = _scheduler_inputs(tmp_path, rounds, stages=("G2",))
    evaluated = evaluate_scheduler_evidence(
        inputs["scheduler_evidence_ledger_path"],
        allowed_roots=[tmp_path],
        expected_due_points={"G2": 3},
    )

    report = evaluate_soak_readiness(
        _base_bundle(rounds),
        scheduler_evidence_readiness=evaluated,
        expected_scheduler_scheduled_at=inputs[
            "expected_scheduler_scheduled_at"
        ],
    )

    assert report.gates["G2"].status == INSUFFICIENT
    assert any("逐点 scheduled_at 绑定" in reason for reason in report.gates["G2"].reasons)


def test_pre_evaluated_scheduler_mapping_with_time_binding_is_supported(tmp_path):
    rounds = [_round(index) for index in range(3)]
    inputs = _scheduler_inputs(tmp_path, rounds, stages=("G2",))
    evaluated = evaluate_scheduler_evidence(
        inputs["scheduler_evidence_ledger_path"],
        allowed_roots=[tmp_path],
        expected_due_points={"G2": 3},
    ).as_dict()
    evaluated["scheduled_at_by_stage"] = inputs[
        "expected_scheduler_scheduled_at"
    ]

    report = evaluate_soak_readiness(
        _base_bundle(rounds),
        scheduler_evidence_readiness=evaluated,
        expected_scheduler_scheduled_at=inputs[
            "expected_scheduler_scheduled_at"
        ],
    )

    assert report.gates["G2"].status == PASS
    assert report.summary["scheduler_evidence_source"] == "evaluation"


def test_simulated_cycles_never_count_as_real_soak_even_with_24h_timestamps(
    tmp_path,
):
    rounds = [_round(index, hours=index, source_kind="simulation") for index in range(25)]
    bundle = _base_bundle(rounds)
    bundle["evidence_kind"] = "simulation"

    report = evaluate_soak_readiness(
        bundle,
        target="24h_soak",
        baseline_manifest=_baseline(tmp_path),
    )

    assert report.summary["real_round_count"] == 0
    assert report.gates["G0"].status == PASS
    assert report.gates["G1"].status == INSUFFICIENT
    assert report.gates["G4"].status == INSUFFICIENT
    assert report.gates["G5"].status == INSUFFICIENT
    assert any("不能等同于真实" in warning for warning in report.warnings)


def test_missing_link_metrics_recovery_and_ids_fail_closed():
    rounds = [_round(index) for index in range(3)]
    rounds[0]["share_url"] = "https://example.com/not-xhs"
    rounds[1]["metrics"] = {}
    rounds[2]["search_recovered"] = None
    rounds[2]["observation_id"] = None

    report = evaluate_soak_readiness(_base_bundle(rounds))

    assert report.summary["successful_round_count"] == 0
    assert report.gates["G1"].status == "failed"
    assert any("完整成功证据" in reason for reason in report.gates["G1"].reasons)


def test_risk_residual_state_sqlite_lock_and_unacked_alert_are_hard_failures():
    bundle = _base_bundle([_round(index) for index in range(7)])
    bundle["rounds"][2]["risk_stop_reason"] = "captcha detected"
    bundle["leases"] = [{"name": "monitor", "owner": "old-run"}]
    bundle["tasks"] = [{"id": 9, "status": "running"}]
    bundle["sqlite_events"] = [{"error": "database is locked"}]
    bundle["digest_snapshots"][1]["alerts"] = [
        {"severity": "critical", "title": "风控", "acknowledged": False}
    ]

    report = evaluate_soak_readiness(bundle)

    assert report.gates["G0"].status == "failed"
    assert report.gates["G1"].status == "failed"
    assert report.gates["G3"].status == "failed"
    assert report.gates["G4"].status == "failed"
    assert report.summary["active_lease_count"] == 1
    assert report.summary["running_task_count"] == 1
    assert report.summary["sqlite_lock_error_count"] == 1
    assert report.summary["digest_unacked_critical_error_count"] == 1


def test_critical_alert_without_ack_fails_closed():
    bundle = _base_bundle([_round(index) for index in range(7)])
    alert_id = _critical_alert(bundle)

    report = evaluate_soak_readiness(bundle)

    assert report.summary["ack_required_alert_ids"] == [alert_id]
    assert report.summary["ack_missing_alert_ids"] == [alert_id]
    assert report.summary["ack_ready"] is False
    assert report.gates["G3"].status == "failed"
    assert report.gates["G4"].status == "failed"
    assert report.ready_for_24h_soak is False


def test_acknowledged_ledger_allows_existing_readiness_gates(tmp_path):
    rounds = [_round(index) for index in range(7)]
    bundle = _base_bundle(rounds)
    alert_id = _critical_alert(bundle)
    ledger_path = _ack_ledger(tmp_path, alert_id)

    report = evaluate_soak_readiness(
        bundle,
        ack_ledger_path=ledger_path,
        ack_allowed_roots=[tmp_path],
        baseline_manifest=_baseline(tmp_path),
        **_scheduler_inputs(tmp_path, rounds),
    )

    assert report.summary["ack_source"] == "ledger"
    assert report.summary["acknowledged_alert_ids"] == [alert_id]
    assert report.summary["ack_ready"] is True
    assert [report.gates[f"G{index}"].status for index in range(5)] == [PASS] * 5
    assert report.ready_for_24h_soak is True


@pytest.mark.parametrize("decision", ["reject", "defer"])
def test_latest_non_ack_decision_fails_closed(tmp_path, decision):
    bundle = _base_bundle([_round(index) for index in range(7)])
    alert_id = _critical_alert(bundle)
    ledger_path = _ack_ledger(tmp_path, alert_id, decision=decision)

    report = evaluate_soak_readiness(
        bundle,
        ack_ledger_path=ledger_path,
        ack_allowed_roots=[tmp_path],
    )

    assert report.summary["ack_unresolved_alert_ids"] == [alert_id]
    assert report.summary["ack_latest_decisions"] == {alert_id: decision}
    assert report.summary["ack_ready"] is False
    assert any(
        "最新决定不是 acknowledge" in reason
        for reason in report.gates["G3"].reasons
    )


def test_corrupt_ack_ledger_fails_closed(tmp_path):
    bundle = _base_bundle([_round(index) for index in range(7)])
    alert_id = _critical_alert(bundle)
    ledger_path = _ack_ledger(tmp_path, alert_id)
    ledger_path.write_text("{bad json}\n", encoding="utf-8")

    report = evaluate_soak_readiness(
        bundle,
        ack_ledger_path=ledger_path,
        ack_allowed_roots=[tmp_path],
    )

    assert report.summary["ack_integrity_error"]
    assert report.summary["ack_ready"] is False
    assert any("损坏" in reason for reason in report.gates["G3"].reasons)


def test_ack_evaluation_alert_id_mismatch_fails_closed(tmp_path):
    bundle = _base_bundle([_round(index) for index in range(7)])
    required_alert_id = _critical_alert(bundle)
    ledger_path = _ack_ledger(tmp_path, "different-critical-id")
    evaluated = evaluate_ack_readiness(
        ledger_path,
        allowed_roots=[tmp_path],
        required_alert_ids=["different-critical-id"],
    )

    report = evaluate_soak_readiness(bundle, ack_readiness=evaluated)

    assert report.summary["ack_required_alert_ids"] == [required_alert_id]
    assert report.summary["ack_evidence_mismatches"]
    assert report.summary["ack_ready"] is False
    assert any("ID 不匹配" in reason for reason in report.gates["G3"].reasons)


def test_pre_evaluated_ack_result_is_supported(tmp_path):
    rounds = [_round(index) for index in range(7)]
    bundle = _base_bundle(rounds)
    alert_id = _critical_alert(bundle)
    ledger_path = _ack_ledger(tmp_path, alert_id)
    evaluated = evaluate_ack_readiness(
        ledger_path,
        allowed_roots=[tmp_path],
        required_alert_ids=[alert_id],
    )

    report = evaluate_soak_readiness(
        bundle,
        ack_readiness=evaluated,
        baseline_manifest=_baseline(tmp_path),
        **_scheduler_inputs(tmp_path, rounds),
    )

    assert report.summary["ack_source"] == "evaluation"
    assert report.summary["ack_ready"] is True
    assert report.ready_for_24h_soak is True


def test_quality_error_uses_same_ack_gate_despite_legacy_inline_flag(tmp_path):
    rounds = [_round(index) for index in range(7)]
    bundle = _base_bundle(rounds)
    quality_alert_id = "quality-error-001"
    bundle["quality_snapshots"][1].update(
        {
            "summary": {"by_severity": {"error": 1}},
            "acknowledged": True,
            "issues": [{"id": quality_alert_id, "severity": "error"}],
        }
    )

    without_ledger = evaluate_soak_readiness(bundle)
    ledger_path = _ack_ledger(
        tmp_path,
        quality_alert_id,
        alert_kind="quality",
    )
    with_ledger = evaluate_soak_readiness(
        bundle,
        ack_ledger_path=ledger_path,
        ack_allowed_roots=[tmp_path],
        **_scheduler_inputs(tmp_path, rounds),
    )

    assert without_ledger.summary["ack_ready"] is False
    assert without_ledger.gates["G4"].status == "failed"
    assert with_ledger.summary["ack_ready"] is True
    assert with_ledger.gates["G4"].status == PASS


def test_24h_gate_requires_18_real_starts_and_only_makes_g6_eligible(tmp_path):
    hours = [index * (24 / 18) for index in range(19)]
    rounds = [_round(index, hours=hours[index]) for index in range(19)]
    bundle = _base_bundle(rounds)

    report = evaluate_soak_readiness(
        bundle,
        target="24h_soak",
        baseline_manifest=_baseline(tmp_path),
        **_scheduler_inputs(tmp_path, rounds),
    )

    assert report.gates["G5"].status == PASS
    assert report.gates["G6"].status == ELIGIBLE
    assert "不代表已授权扩容" in report.gates["G6"].reasons[0]


def test_scheduler_exception_must_have_recovery_and_zero_failure_residue():
    bundle = _base_bundle([_round(index) for index in range(7)])
    bundle["scheduler_events"] = [
        {
            "kind": "scheduler_exception",
            "at": BASE.isoformat(),
            "recovered": False,
        }
    ]

    report = evaluate_soak_readiness(bundle)

    assert report.summary["scheduler_exception_count"] == 1
    assert report.summary["unrecovered_scheduler_exception_count"] == 1
    assert report.gates["G3"].status == "failed"


def test_sqlite_fixture_is_read_only_and_builds_real_round_from_run_events(tmp_path):
    db_path = tmp_path / "soak-fixture.sqlite3"
    with connect(db_path) as conn:
        task_id = conn.execute(
            """
            INSERT INTO search_tasks(
                keyword, source, status, created_at, updated_at,
                last_started_at, last_finished_at
            ) VALUES (?, 'fixture', 'completed', ?, ?, ?, ?)
            """,
            (
                "fixture-keyword",
                BASE.isoformat(),
                BASE.isoformat(),
                BASE.isoformat(),
                (BASE + timedelta(minutes=8)).isoformat(),
            ),
        ).lastrowid
        product_id = conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, share_url, first_seen_at, last_seen_at
            ) VALUES ('fixture-product', 'fixture', ?, ?, ?)
            """,
            (
                "https://xhslink.com/m/fixture-product",
                BASE.isoformat(),
                BASE.isoformat(),
            ),
        ).lastrowid
        observation_id = conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, screenshot_path, sales_7d_min
            ) VALUES (?, ?, 'fixture', 'fixture.png', 88)
            """,
            (product_id, BASE.isoformat()),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                task_id, product_id, observation_id, source_keyword, result_rank,
                search_probe_dir, recorded_at, valid
            ) VALUES (?, ?, ?, 'fixture-keyword', 1, 'probe/search', ?, 1)
            """,
            (task_id, product_id, observation_id, BASE.isoformat()),
        )
        record_run_event(
            conn,
            run_id="monitor-fixture",
            phase="monitor",
            event="monitor_once_started",
            task_id=task_id,
            data={"limits": {"dry_run": False}},
        )
        conn.execute(
            """
            UPDATE run_events SET event_at=?
            WHERE run_id='monitor-fixture' AND event='monitor_once_started'
            """,
            (BASE.isoformat(),),
        )
        record_run_event(
            conn,
            run_id="monitor-fixture",
            phase="search_ui",
            event="back_to_search_results",
            task_id=task_id,
            product_id=product_id,
            observation_id=observation_id,
        )
        record_run_event(
            conn,
            run_id="monitor-fixture",
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
            WHERE run_id='monitor-fixture' AND event='monitor_once_finished'
            """,
            ((BASE + timedelta(minutes=8)).isoformat(),),
        )
        set_monitor_state(conn, "scheduler_running", False)

    before = db_path.stat().st_mtime_ns
    bundle = load_sqlite_evidence(db_path)
    report = evaluate_sqlite_readiness(
        db_path,
        context={
            "offline_tests_passed": True,
            "sqlite_stress_passed": True,
            "scheduler_recovery_tested": True,
            "lease_safety_tested": True,
        },
    )

    assert before == db_path.stat().st_mtime_ns
    assert len(bundle["rounds"]) == 1
    assert bundle["rounds"][0]["share_url"].startswith("https://xhslink.com/")
    assert bundle["rounds"][0]["metrics"]["sales_7d_min"] == 88
    assert report.summary["real_round_count"] == 1
    assert report.summary["successful_round_count"] == 1
    assert report.gates["G1"].status == INSUFFICIENT


def test_plain_round_iterable_is_supported_and_missing_context_fails_g0():
    report = evaluate_soak_readiness([_round(index) for index in range(3)])

    assert report.summary["real_round_count"] == 3
    assert report.gates["G0"].status == INSUFFICIENT
    assert report.gates["G1"].status == PASS
