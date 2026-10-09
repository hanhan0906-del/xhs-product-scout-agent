import json
from datetime import datetime, timedelta, timezone

import pytest

from xhs_scout.scheduler_evidence import (
    append_scheduler_evidence,
    evaluate_scheduler_evidence,
)
from xhs_scout.soak_ack import append_soak_ack
from xhs_scout.soak_readiness import INSUFFICIENT, PASS, evaluate_soak_readiness


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 7, 29, 8, 0, tzinfo=TZ)
DIGEST_ALERT_ID = "digest-critical-current"
QUALITY_ALERT_ID = "quality-error-current"


def _round(index):
    scheduled = BASE + timedelta(hours=index)
    return {
        "sequence": index + 1,
        "run_id": f"monitor-real-{index}",
        "task_id": index + 1,
        "keyword": f"keyword-{index}",
        "scheduled_at": scheduled.isoformat(),
        "started_at": (scheduled + timedelta(minutes=2)).isoformat(),
        "finished_at": (scheduled + timedelta(minutes=8)).isoformat(),
        "result": "completed",
        "success": True,
        "product_id": 100 + index,
        "observation_id": 200 + index,
        "search_recovered": True,
        "share_url": f"https://xhslink.com/m/product-{index}",
        "metrics": {"sales_7d_min": 10 + index},
        "evidence_path": f"fixture/round-{index}",
        "source_kind": "real",
    }


def _bundle(rounds):
    return {
        "soak_id": "t52-offline-chain",
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
        "digest_snapshots": [
            {"phase": "start", "alerts": []},
            {
                "phase": "mid",
                "alerts": [
                    {
                        "alert_id": DIGEST_ALERT_ID,
                        "severity": "critical",
                        "acknowledged": False,
                    }
                ],
            },
            {"phase": "end", "alerts": []},
        ],
        "quality_snapshots": [
            {
                "phase": "start",
                "summary": {"by_severity": {"error": 0}},
                "acknowledged": True,
            },
            {
                "phase": "mid",
                "summary": {"by_severity": {"error": 1}},
                "acknowledged": False,
                "issues": [{"id": QUALITY_ALERT_ID, "severity": "error"}],
            },
            {
                "phase": "end",
                "summary": {"by_severity": {"error": 0}},
                "acknowledged": True,
            },
        ],
    }


def _artifact(root, name):
    path = root / "artifacts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fixture": name}), encoding="utf-8")
    return path


def _append_ack(
    root,
    *,
    alert_id,
    record_id,
    decision="acknowledge",
    decided_at=BASE,
):
    return append_soak_ack(
        root / "acks" / "soak-ack.jsonl",
        allowed_roots=[root],
        record_id=record_id,
        alert_id=alert_id,
        alert_kind="quality" if alert_id.startswith("quality-") else "critical",
        actor="t52-operator",
        decision=decision,
        evidence_path=_artifact(root, f"{record_id}-ack.json"),
        note="T52 offline evidence review",
        decided_at=decided_at,
    )


def _complete_ack_ledger(root):
    _append_ack(
        root,
        alert_id=DIGEST_ALERT_ID,
        record_id="ack-digest-current",
    )
    _append_ack(
        root,
        alert_id=QUALITY_ALERT_ID,
        record_id="ack-quality-current",
        decided_at=BASE + timedelta(minutes=1),
    )
    return root / "acks" / "soak-ack.jsonl"


def _scheduler_record(
    root,
    *,
    stage,
    index,
    scheduled_at,
    source="real",
    **overrides,
):
    scheduled = datetime.fromisoformat(scheduled_at)
    started = scheduled + timedelta(minutes=2)
    finished = started + timedelta(minutes=6)
    prefix = f"{stage.lower()}-{index}"
    value = {
        "record_id": f"record-{prefix}",
        "stage": stage,
        "soak_id": "t52-offline-chain",
        "due_point_id": f"due-{prefix}",
        "evidence_source": source,
        "scheduled_at": scheduled.isoformat(),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "start_delay_seconds": 120,
        "duration_seconds": 360,
        "result": "completed",
        "run_id": f"monitor-{prefix}",
        "task_id": index + 1,
        "product_id": 100 + index,
        "observation_id": 200 + index,
        "keyword": f"keyword-{prefix}",
        "keyword_source": "portfolio",
        "portfolio_cursor_before": index,
        "portfolio_cursor_after": index + 1,
        "portfolio_selected": [f"keyword-{prefix}"],
        "portfolio_deferred_reason": None,
        "risk_stop_reason": None,
        "last_block_reason": None,
        "last_skip_reason": None,
        "run_lease_owner": f"monitor-{prefix}",
        "task_lease_owner": f"monitor-{prefix}",
        "lease_state": "released",
        "desired_state": "running",
        "scheduler_running": True,
        "scheduler_thread_alive": True,
        "scheduler_worker_state": "running",
        "db_status": "ok",
        "sqlite_error": None,
        "db_evidence_path": _artifact(root, f"{prefix}-db.json"),
        "http_status": {
            "api_status": 200,
            "monitor_status": 200,
            "candidates_csv": 200,
        },
        "http_evidence_path": _artifact(root, f"{prefix}-http.json"),
        "evidence_paths": [_artifact(root, f"{prefix}-round.json")],
        "operator_ack_refs": [],
    }
    value.update(overrides)
    return value


def _scheduler_ledger(
    root,
    rounds,
    *,
    source="real",
    g2_updates=None,
    g4_updates=None,
    g4_indices=range(7),
):
    ledger = root / "scheduler" / "evidence.jsonl"
    expected = {"G2": [], "G4": []}
    for stage, indices, updates in (
        ("G2", range(3), g2_updates or {}),
        ("G4", g4_indices, g4_updates or {}),
    ):
        for index in indices:
            scheduled_at = rounds[index]["scheduled_at"]
            expected[stage].append(scheduled_at)
            append_scheduler_evidence(
                ledger,
                allowed_roots=[root],
                evidence=_scheduler_record(
                    root,
                    stage=stage,
                    index=index,
                    scheduled_at=scheduled_at,
                    source=source,
                    **(updates if index == 0 else {}),
                ),
            )
    return ledger, expected


def _evaluate(root, bundle, ack_ledger, scheduler_ledger, expected):
    return evaluate_soak_readiness(
        bundle,
        ack_ledger_path=ack_ledger,
        ack_allowed_roots=[root],
        scheduler_evidence_ledger_path=scheduler_ledger,
        scheduler_evidence_allowed_roots=[root],
        expected_scheduler_scheduled_at=expected,
    )


def _complete_chain(root, **scheduler_kwargs):
    rounds = [_round(index) for index in range(7)]
    ack_ledger = _complete_ack_ledger(root)
    scheduler_ledger, expected = _scheduler_ledger(
        root,
        rounds,
        **scheduler_kwargs,
    )
    return _bundle(rounds), ack_ledger, scheduler_ledger, expected


def test_complete_t43_t46_t49_chain_is_required_for_g2_and_g4(tmp_path):
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(tmp_path)

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    assert report.gates["G2"].status == PASS
    assert report.gates["G4"].status == PASS
    assert report.summary["ack_required_alert_ids"] == [
        DIGEST_ALERT_ID,
        QUALITY_ALERT_ID,
    ]
    assert report.summary["acknowledged_alert_ids"] == [
        DIGEST_ALERT_ID,
        QUALITY_ALERT_ID,
    ]
    assert report.summary["ack_ready"] is True
    for stage in ("G2", "G4"):
        evidence = report.summary["scheduler_evidence_stages"][stage]
        assert evidence["ready"] is True
        assert evidence["missing_scheduled_at"] == []
        assert evidence["unexpected_scheduled_at"] == []
        assert evidence["t46_ready_for_gate_evaluation"] is True


def test_ack_is_required_by_g4_and_expected_schedule_by_both_scheduler_gates(
    tmp_path,
):
    bundle, _, scheduler_ledger, expected = _complete_chain(tmp_path)

    without_ack = evaluate_soak_readiness(
        bundle,
        scheduler_evidence_ledger_path=scheduler_ledger,
        scheduler_evidence_allowed_roots=[tmp_path],
        expected_scheduler_scheduled_at=expected,
    )
    without_expected = evaluate_soak_readiness(
        bundle,
        ack_ledger_path=_complete_ack_ledger(tmp_path / "second"),
        ack_allowed_roots=[tmp_path / "second"],
        scheduler_evidence_ledger_path=scheduler_ledger,
        scheduler_evidence_allowed_roots=[tmp_path],
    )

    assert without_ack.gates["G2"].status == PASS
    assert without_ack.gates["G3"].status == "failed"
    assert without_ack.gates["G4"].status != PASS
    assert without_ack.summary["ack_ready"] is False
    assert without_expected.gates["G2"].status != PASS
    assert without_expected.gates["G4"].status != PASS


def test_old_ack_for_previous_alert_and_wrong_current_id_fail_closed(tmp_path):
    rounds = [_round(index) for index in range(7)]
    bundle = _bundle(rounds)
    scheduler_ledger, expected = _scheduler_ledger(tmp_path, rounds)
    old_ack = _append_ack(
        tmp_path,
        alert_id="digest-critical-previous",
        record_id="ack-previous-alert",
    )
    _append_ack(
        tmp_path,
        alert_id="quality-error-wrong",
        record_id="ack-wrong-quality",
        decided_at=BASE + timedelta(minutes=1),
    )

    report = _evaluate(
        tmp_path,
        bundle,
        tmp_path / "acks" / "soak-ack.jsonl",
        scheduler_ledger,
        expected,
    )

    assert old_ack.decision == "acknowledge"
    assert report.summary["ack_missing_alert_ids"] == [
        DIGEST_ALERT_ID,
        QUALITY_ALERT_ID,
    ]
    assert report.gates["G4"].status == "failed"


@pytest.mark.parametrize("latest_decision", ["reject", "defer"])
def test_latest_reject_or_defer_overrides_old_ack(tmp_path, latest_decision):
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(tmp_path)
    _append_ack(
        tmp_path,
        alert_id=DIGEST_ALERT_ID,
        record_id=f"ack-digest-{latest_decision}",
        decision=latest_decision,
        decided_at=BASE + timedelta(minutes=5),
    )

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    assert report.summary["ack_latest_decisions"][DIGEST_ALERT_ID] == latest_decision
    assert report.summary["ack_ready"] is False
    assert report.gates["G4"].status == "failed"


def test_ack_ledger_hash_tampering_fails_closed(tmp_path):
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(tmp_path)
    rows = ack_ledger.read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[0])
    payload["decision"] = "reject"
    rows[0] = json.dumps(payload, ensure_ascii=False)
    ack_ledger.write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    assert report.summary["ack_integrity_error"]
    assert report.summary["ack_ready"] is False
    assert report.gates["G4"].status == "failed"


def test_scheduler_ledger_hash_tampering_closes_g2_and_g4(tmp_path):
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(tmp_path)
    rows = scheduler_ledger.read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[0])
    payload["keyword"] = "tampered-keyword"
    rows[0] = json.dumps(payload, ensure_ascii=False)
    scheduler_ledger.write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    assert report.summary["scheduler_evidence_integrity_ok"] is False
    assert report.gates["G2"].status == "failed"
    assert report.gates["G4"].status == "failed"


@pytest.mark.parametrize("stage", ["G2", "G4"])
@pytest.mark.parametrize(
    ("case", "updates", "reason_fragment"),
    [
        (
            "timeout",
            {
                "started_at": (BASE + timedelta(minutes=16)).isoformat(),
                "finished_at": (BASE + timedelta(minutes=22)).isoformat(),
                "start_delay_seconds": 960,
            },
            "start delay exceeds",
        ),
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
        ("thread", {"scheduler_thread_alive": False}, "scheduler/thread"),
        ("lease", {"lease_state": "lost"}, "lease state"),
        ("risk", {"risk_stop_reason": "captcha"}, "risk"),
    ],
)
def test_each_scheduler_health_guard_closes_its_gate(
    tmp_path,
    stage,
    case,
    updates,
    reason_fragment,
):
    scheduler_kwargs = {
        "g2_updates" if stage == "G2" else "g4_updates": updates,
    }
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(
        tmp_path,
        **scheduler_kwargs,
    )

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    assert report.gates[stage].status == "failed", f"{stage}:{case}"
    assert any(reason_fragment in reason for reason in report.gates[stage].reasons)


def test_simulated_source_never_promotes_g2_or_g4(tmp_path):
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(
        tmp_path,
        source="simulated",
    )

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    assert report.gates["G2"].status == "failed"
    assert report.gates["G4"].status == "failed"
    assert all(
        any(
            "simulated" in reason
            for reason in report.summary["scheduler_evidence_stages"][stage][
                "failed_reasons"
            ]
        )
        for stage in ("G2", "G4")
    )


@pytest.mark.parametrize("coverage_error", ["missing", "extra"])
def test_expected_schedule_must_match_recorded_points_exactly(
    tmp_path,
    coverage_error,
):
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(tmp_path)
    if coverage_error == "missing":
        expected["G2"][-1] = (BASE + timedelta(hours=3)).isoformat()
    else:
        expected["G2"].append((BASE + timedelta(hours=3)).isoformat())

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    stage = report.summary["scheduler_evidence_stages"]["G2"]
    assert report.gates["G2"].status == "failed"
    assert stage["missing_scheduled_at"]
    if coverage_error == "missing":
        assert stage["unexpected_scheduled_at"]


def test_unexpected_recorded_point_closes_exact_expected_coverage(tmp_path):
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(tmp_path)
    append_scheduler_evidence(
        scheduler_ledger,
        allowed_roots=[tmp_path],
        evidence=_scheduler_record(
            tmp_path,
            stage="G2",
            index=99,
            scheduled_at=(BASE + timedelta(hours=7)).isoformat(),
        ),
    )

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    stage = report.summary["scheduler_evidence_stages"]["G2"]
    assert report.gates["G2"].status == "failed"
    assert stage["unexpected_scheduled_at"] == [
        (BASE + timedelta(hours=7)).isoformat(timespec="seconds")
    ]


def test_g4_expected_points_must_span_at_least_six_hours(tmp_path):
    rounds = [_round(index) for index in range(7)]
    bundle = _bundle(rounds)
    ack_ledger = _complete_ack_ledger(tmp_path)
    scheduler_ledger, expected = _scheduler_ledger(
        tmp_path,
        rounds,
        g4_indices=(0, 2, 4),
    )

    report = _evaluate(
        tmp_path,
        bundle,
        ack_ledger,
        scheduler_ledger,
        expected,
    )

    assert report.gates["G2"].status == PASS
    assert report.gates["G4"].status == INSUFFICIENT
    assert any("跨度不足 6 小时" in reason for reason in report.gates["G4"].reasons)


def test_pre_evaluated_scheduler_report_without_point_binding_cannot_promote(
    tmp_path,
):
    bundle, ack_ledger, scheduler_ledger, expected = _complete_chain(tmp_path)
    evaluated = evaluate_scheduler_evidence(
        scheduler_ledger,
        allowed_roots=[tmp_path],
        expected_due_points={"G2": 3, "G4": 7},
    )

    report = evaluate_soak_readiness(
        bundle,
        ack_ledger_path=ack_ledger,
        ack_allowed_roots=[tmp_path],
        scheduler_evidence_readiness=evaluated,
        expected_scheduler_scheduled_at=expected,
    )

    assert report.gates["G2"].status == INSUFFICIENT
    assert report.gates["G4"].status == INSUFFICIENT
    assert all(
        any(
            "逐点 scheduled_at 绑定" in reason
            for reason in report.gates[stage].reasons
        )
        for stage in ("G2", "G4")
    )
