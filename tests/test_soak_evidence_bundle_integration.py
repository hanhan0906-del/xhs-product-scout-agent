from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from xhs_scout.remediation import plan_remediation
from xhs_scout.remediation_approval import (
    build_approval_manifest,
    write_approval_manifest,
)
from xhs_scout.scheduler_evidence import (
    append_scheduler_evidence,
    evaluate_scheduler_evidence,
)
from xhs_scout.soak_ack import append_soak_ack, evaluate_ack_readiness
from xhs_scout.soak_baseline import (
    build_baseline_manifest,
    write_baseline_manifest,
)
from xhs_scout.soak_evidence_bundle import build_soak_evidence_bundle
from xhs_scout.soak_readiness import PASS, evaluate_soak_readiness


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 7, 29, 8, 0, tzinfo=TZ)
DIGEST_ALERT_ID = "digest-critical-t62"
QUALITY_ALERT_ID = "quality-error-t62"
AUTHORIZATION_FIELDS = (
    "execution_authorized",
    "scheduler_start_authorized",
    "pre_soak_start_authorized",
    "soak_24h_start_authorized",
)


def _artifact(root, name):
    path = root / "artifacts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"fixture": name}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _round(index, *, source_kind="real"):
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
        "share_url": f"https://xhslink.com/m/t62-product-{index}",
        "metrics": {"sales_7d_min": 10 + index},
        "evidence_path": f"offline/round-{index}",
        "source_kind": source_kind,
    }


def _readiness_evidence(rounds):
    return {
        "soak_id": "t62-offline-integration",
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


def _baseline(root):
    project = root / "baseline-project"
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "config").mkdir(exist_ok=True)
    code_path = project / "src" / "worker.py"
    config_path = project / "config" / "settings.json"
    code_path.write_text("BASELINE_VALUE = 1\n", encoding="utf-8")
    config_path.write_text(
        '{"max_keywords":1,"max_products_per_keyword":1}\n',
        encoding="utf-8",
    )

    database_path = root / "fixture.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE evidence_rows (id INTEGER PRIMARY KEY, status TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO evidence_rows (status) VALUES (?)",
            ("offline",),
        )
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        row_count = connection.execute(
            "SELECT COUNT(*) FROM evidence_rows"
        ).fetchone()[0]

    manifest = build_baseline_manifest(
        project_root=project,
        code_files=["src/worker.py"],
        config_files=["config/settings.json"],
        database_statistics={
            "quick_check": quick_check,
            "row_count": row_count,
        },
        run_parameters={
            "interval_seconds": 3600,
            "max_keywords": 1,
            "max_products_per_keyword": 1,
        },
        port_owners={
            "8793": {"owner": "offline fixture owner"},
            "8765": {"owner": "isolated offline fixture"},
        },
        disk_summary={"status": "caller supplied fixture"},
        log_summary={"error_count": 0},
        operator="offline-operator",
        stop_entry={"procedure": "pause and wait for current round"},
    )
    path = write_baseline_manifest(
        root / "baseline.json",
        manifest,
        allowed_roots=[root],
    )
    return manifest, path, code_path


def _ack_ledger(root):
    ledger = root / "acks" / "soak-ack.jsonl"
    for index, (alert_id, alert_kind) in enumerate(
        (
            (DIGEST_ALERT_ID, "critical"),
            (QUALITY_ALERT_ID, "quality"),
        )
    ):
        append_soak_ack(
            ledger,
            allowed_roots=[root],
            record_id=f"ack-t62-{index}",
            alert_id=alert_id,
            alert_kind=alert_kind,
            actor="t62-operator",
            decision="acknowledge",
            evidence_path=_artifact(root, f"ack-{index}.json"),
            note="T62 offline review",
            decided_at=BASE + timedelta(minutes=index),
        )
    result = evaluate_ack_readiness(
        ledger,
        allowed_roots=[root],
        required_alert_ids=[DIGEST_ALERT_ID, QUALITY_ALERT_ID],
    )
    assert result.ready is True
    return ledger, result


def _scheduler_record(
    root,
    *,
    stage,
    index,
    scheduled_at,
    source="real",
):
    scheduled = datetime.fromisoformat(scheduled_at)
    prefix = f"{stage.lower()}-{index}"
    return {
        "record_id": f"record-{prefix}",
        "stage": stage,
        "soak_id": "t62-offline-integration",
        "due_point_id": f"due-{prefix}",
        "evidence_source": source,
        "scheduled_at": scheduled.isoformat(),
        "started_at": (scheduled + timedelta(minutes=2)).isoformat(),
        "finished_at": (scheduled + timedelta(minutes=8)).isoformat(),
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


def _scheduler(root, rounds, *, source="real"):
    ledger = root / "scheduler" / "evidence.jsonl"
    expected_ids = {"G2": [], "G4": []}
    expected_times = {"G2": [], "G4": []}
    for stage, stage_rounds in (("G2", rounds[:3]), ("G4", rounds)):
        for index, row in enumerate(stage_rounds):
            record = append_scheduler_evidence(
                ledger,
                allowed_roots=[root],
                evidence=_scheduler_record(
                    root,
                    stage=stage,
                    index=index,
                    scheduled_at=row["scheduled_at"],
                    source=source,
                ),
            )
            expected_ids[stage].append(record.due_point_id)
            expected_times[stage].append(row["scheduled_at"])
    report = evaluate_scheduler_evidence(
        ledger,
        allowed_roots=[root],
        expected_due_points=expected_ids,
    )
    return ledger, expected_ids, expected_times, report


def _remediation_approval(root, *, plan_time=BASE.isoformat()):
    database_path = root / "remediation.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE remediation_products (
                product_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                score INTEGER NOT NULL,
                has_valid_search_attribution INTEGER NOT NULL,
                has_supported_product_link INTEGER NOT NULL,
                has_metrics_strip INTEGER NOT NULL,
                has_note_evidence INTEGER NOT NULL,
                has_profile_evidence INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO remediation_products VALUES
            (1, 'candidate', 50, 0, 0, 1, 1, 1)
            """
        )
        plan = plan_remediation(connection, now=plan_time)

    approval = build_approval_manifest(
        plan,
        [
            {
                "batch_id": plan.batches[0].batch_id,
                "product_ids": [1],
            }
        ],
        decision="approve",
        reviewer="offline-reviewer",
        reviewed_at=plan_time,
    )
    assert approval.valid
    assert approval.planned_approved
    assert approval.execution_status == "not_executed"
    assert approval.authorizes_execution is False
    path = write_approval_manifest(root / "approval.json", approval)
    return plan, approval, path


def _chain(
    root,
    *,
    scheduler_source="real",
    readiness_updates=None,
    approval_time=BASE.isoformat(),
):
    rounds = [_round(index) for index in range(7)]
    baseline, baseline_path, code_path = _baseline(root)
    ack_path, ack_result = _ack_ledger(root)
    scheduler_path, expected_ids, expected_times, scheduler_report = _scheduler(
        root,
        rounds,
        source=scheduler_source,
    )
    plan, approval, approval_path = _remediation_approval(
        root,
        plan_time=approval_time,
    )
    evidence = _readiness_evidence(rounds)
    if readiness_updates:
        evidence.update(readiness_updates)
    readiness = evaluate_soak_readiness(
        evidence,
        generated_at=BASE + timedelta(hours=7),
        ack_ledger_path=ack_path,
        ack_allowed_roots=[root],
        scheduler_evidence_ledger_path=scheduler_path,
        scheduler_evidence_allowed_roots=[root],
        expected_scheduler_scheduled_at=expected_times,
        baseline_manifest=baseline,
    )
    inputs = {
        "baseline": baseline_path,
        "ack": ack_path,
        "scheduler_evidence": scheduler_path,
        "scheduler_expected": expected_ids,
        "remediation_approval": approval_path,
        "current_remediation_plan_hash": approval.source_plan_hash,
        "readiness": readiness,
        "allowed_roots": [root],
        "assembled_at": BASE + timedelta(hours=7),
    }
    return {
        "inputs": inputs,
        "baseline": baseline,
        "baseline_path": baseline_path,
        "baseline_code_path": code_path,
        "ack_path": ack_path,
        "ack_result": ack_result,
        "scheduler_path": scheduler_path,
        "scheduler_report": scheduler_report,
        "expected_ids": expected_ids,
        "expected_times": expected_times,
        "plan": plan,
        "approval": approval,
        "approval_path": approval_path,
        "readiness": readiness,
    }


def _bundle(chain, **overrides):
    values = dict(chain["inputs"])
    values.update(overrides)
    return build_soak_evidence_bundle(**values)


def _assert_never_authorized(bundle):
    assert bundle.authorizes_execution is False
    assert bundle.authorizes_soak is False
    for field in AUTHORIZATION_FIELDS:
        assert bundle.safety[field] is False


def test_real_modules_form_deterministic_complete_provenance_chain(tmp_path):
    chain = _chain(tmp_path)

    assert chain["scheduler_report"].ready is True
    assert chain["readiness"].ready_for_pre_soak is True
    assert all(
        chain["readiness"].gates[name].status == PASS
        for name in ("G0", "G1", "G2", "G3")
    )

    first = _bundle(chain)
    second = _bundle(chain)

    assert first.status == "evidence_complete"
    assert first.bundle_id == second.bundle_id
    assert first.manifest_hash == second.manifest_hash
    assert first.to_json() == second.to_json()
    assert set(first.sources) == {
        "baseline",
        "ack",
        "scheduler",
        "remediation_approval",
        "readiness",
    }
    assert all(source.status == "valid" for source in first.sources.values())
    assert all(source.source_hash for source in first.sources.values())
    assert first.sources["baseline"].details["baseline_id"] == (
        chain["baseline"].baseline_id
    )
    assert first.sources["ack"].details["required_alert_count"] == 2
    assert first.sources["scheduler"].details["record_count"] == 10
    assert first.sources["remediation_approval"].details["manifest_id"] == (
        chain["approval"].manifest_id
    )
    assert first.sources["readiness"].details["ready_for_pre_soak"] is True
    _assert_never_authorized(first)


@pytest.mark.parametrize(
    ("input_name", "source_name"),
    (
        ("baseline", "baseline"),
        ("ack", "ack"),
        ("scheduler_evidence", "scheduler"),
        ("remediation_approval", "remediation_approval"),
        ("readiness", "readiness"),
    ),
)
def test_any_missing_source_makes_bundle_incomplete(
    tmp_path,
    input_name,
    source_name,
):
    chain = _chain(tmp_path)

    bundle = _bundle(chain, **{input_name: None})

    assert bundle.status == "incomplete"
    assert bundle.sources[source_name].status == "missing"
    _assert_never_authorized(bundle)


@pytest.mark.parametrize(
    ("input_name", "source_name", "old", "new"),
    (
        ("baseline", "baseline", "offline-operator", "tampered-operator"),
        ("ack", "ack", '"decision":"acknowledge"', '"decision":"defer"'),
        ("scheduler_evidence", "scheduler", '"result":"completed"', '"result":"failed"'),
        (
            "remediation_approval",
            "remediation_approval",
            "offline-reviewer",
            "tampered-reviewer",
        ),
    ),
)
def test_hash_chained_or_signed_source_tampering_is_incomplete(
    tmp_path,
    input_name,
    source_name,
    old,
    new,
):
    chain = _chain(tmp_path)
    source_path = chain["inputs"][input_name]
    original = source_path.read_text(encoding="utf-8")
    assert old in original
    source_path.write_text(original.replace(old, new, 1), encoding="utf-8")

    bundle = _bundle(chain)

    assert bundle.status == "incomplete"
    assert bundle.sources[source_name].status == "invalid"
    _assert_never_authorized(bundle)


@pytest.mark.parametrize("decision", ("reject", "defer"))
def test_latest_reject_or_defer_ack_makes_bundle_not_ready(tmp_path, decision):
    chain = _chain(tmp_path)
    append_soak_ack(
        chain["ack_path"],
        allowed_roots=[tmp_path],
        record_id=f"latest-{decision}",
        alert_id=DIGEST_ALERT_ID,
        alert_kind="critical",
        actor="t62-operator",
        decision=decision,
        evidence_path=_artifact(tmp_path, f"latest-{decision}.json"),
        decided_at=BASE + timedelta(hours=8),
    )

    bundle = _bundle(chain)

    assert bundle.status == "not_ready"
    assert bundle.sources["ack"].details["unresolved_alert_count"] == 1
    _assert_never_authorized(bundle)


def test_simulated_scheduler_evidence_makes_bundle_not_ready(tmp_path):
    chain = _chain(tmp_path, scheduler_source="simulated")

    bundle = _bundle(chain)

    assert chain["scheduler_report"].ready is False
    assert chain["readiness"].ready_for_pre_soak is False
    assert bundle.status == "not_ready"
    assert bundle.sources["scheduler"].details["ready"] is False
    assert bundle.sources["readiness"].details["ready_for_pre_soak"] is False
    _assert_never_authorized(bundle)


def test_scheduler_expected_plan_drift_makes_bundle_not_ready(tmp_path):
    chain = _chain(tmp_path)
    drifted_expected = deepcopy(chain["expected_ids"])
    drifted_expected["G2"][0] = "due-g2-replanned"

    bundle = _bundle(chain, scheduler_expected=drifted_expected)

    assert bundle.status == "not_ready"
    assert bundle.sources["scheduler"].details["ready"] is False
    assert any("scheduler" in gap for gap in bundle.gaps)
    _assert_never_authorized(bundle)


def test_readiness_gate_downgrade_makes_bundle_not_ready(tmp_path):
    chain = _chain(
        tmp_path,
        readiness_updates={"lease_recovery_verified": False},
    )

    bundle = _bundle(chain)

    assert chain["readiness"].gates["G3"].status != PASS
    assert chain["readiness"].ready_for_pre_soak is False
    assert bundle.status == "not_ready"
    assert bundle.sources["readiness"].details["ready_for_pre_soak"] is False
    _assert_never_authorized(bundle)


def test_observed_baseline_file_drift_makes_bundle_incomplete(tmp_path):
    chain = _chain(tmp_path)
    chain["baseline_code_path"].write_text(
        "BASELINE_VALUE = 2\n",
        encoding="utf-8",
    )

    bundle = _bundle(chain)

    assert bundle.status == "incomplete"
    assert bundle.sources["baseline"].status == "invalid"
    _assert_never_authorized(bundle)


def test_stale_approval_makes_bundle_not_ready(tmp_path):
    chain = _chain(
        tmp_path,
        approval_time="2020-01-01T00:00:00+08:00",
    )

    bundle = _bundle(
        chain,
        assembled_at="2026-07-29T16:00:00+08:00",
    )

    assert bundle.status == "not_ready"
    assert any("expired" in gap.lower() or "stale" in gap.lower() for gap in bundle.gaps)
    _assert_never_authorized(bundle)


def test_remediation_plan_drift_invalidates_old_approval(tmp_path):
    chain = _chain(tmp_path)
    current_plan = plan_remediation(
        [
            {
                "product_id": 2,
                "status": "candidate",
                "score": 60,
                "has_valid_search_attribution": 0,
                "has_supported_product_link": 0,
                "has_metrics_strip": 1,
                "has_note_evidence": 1,
                "has_profile_evidence": 1,
            }
        ],
        now=BASE + timedelta(hours=1),
    )
    current_plan_hash = hashlib.sha256(
        json.dumps(
            current_plan.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert current_plan_hash != chain["approval"].source_plan_hash

    bundle = _bundle(
        chain,
        current_remediation_plan_hash=current_plan_hash,
    )

    assert bundle.status == "not_ready"
    assert any("plan" in gap.lower() and "drift" in gap.lower() for gap in bundle.gaps)
    _assert_never_authorized(bundle)


def test_internally_inconsistent_readiness_payload_is_incomplete(tmp_path):
    chain = _chain(tmp_path)
    readiness = chain["readiness"].as_dict()
    readiness["gates"]["G3"]["status"] = "failed"
    assert readiness["ready_for_pre_soak"] is True

    bundle = _bundle(chain, readiness=readiness)

    assert bundle.status == "incomplete"
    assert bundle.sources["readiness"].status == "invalid"
    _assert_never_authorized(bundle)
