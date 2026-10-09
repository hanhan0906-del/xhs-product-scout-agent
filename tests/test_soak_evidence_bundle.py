from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta

import pytest

from xhs_scout.remediation import plan_remediation
from xhs_scout.remediation_approval import build_approval_manifest
from xhs_scout.soak_baseline import build_baseline_manifest
from xhs_scout.soak_evidence_bundle import (
    SoakEvidenceBundleError,
    SoakEvidenceBundleIntegrityError,
    SoakEvidenceBundlePathError,
    build_soak_evidence_bundle,
    read_soak_evidence_bundle,
    validate_soak_evidence_bundle,
    write_soak_evidence_bundle,
)


def _baseline(tmp_path):
    code = tmp_path / "agent.py"
    config = tmp_path / "config.json"
    code.write_text("print('offline')\n", encoding="utf-8")
    config.write_text('{"mode":"offline"}\n', encoding="utf-8")
    return build_baseline_manifest(
        project_root=tmp_path,
        code_files=[code],
        config_files=[config],
        database_statistics={"quick_check": "ok", "row_count": 2},
        run_parameters={
            "interval_seconds": 3600,
            "max_keywords": 1,
            "max_products_per_keyword": 1,
        },
        port_owners={
            "8793": {"owner": "offline fixture", "expected": True},
            "8765": {"owner": "other fixture", "isolated": True},
        },
        disk_summary={"free_bytes": 1000},
        log_summary={"error_count": 0},
        operator="offline-test",
        stop_entry={"procedure": "offline pause fixture", "verified": True},
    )


def _approval():
    plan = plan_remediation(
        [
            {
                "product_id": 1,
                "status": "candidate",
                "score": 50,
                "has_valid_search_attribution": 0,
                "has_supported_product_link": 0,
                "has_metrics_strip": 1,
                "has_note_evidence": 1,
                "has_profile_evidence": 1,
            }
        ],
        now="2026-07-29T08:00:00+08:00",
    )
    batch_id = plan.batches[0].batch_id
    return build_approval_manifest(
        plan,
        [{"batch_id": batch_id, "product_ids": [1]}],
        decision="approve",
        reviewer="offline-reviewer",
        reviewed_at="2026-07-29T09:00:00+08:00",
    )


def _ack():
    return {
        "ready": True,
        "required_alert_ids": ["alert-1"],
        "acknowledged_alert_ids": ["alert-1"],
        "missing_alert_ids": [],
        "unresolved_alert_ids": [],
        "latest_decisions": {"alert-1": "acknowledge"},
        "integrity_error": None,
    }


def _scheduler():
    return {
        "ready": True,
        "ledger_integrity_ok": True,
        "record_count": 1,
        "stages": {
            "G2": {
                "stage": "G2",
                "ready_for_gate_evaluation": True,
                "expected_due_point_count": 1,
                "recorded_due_point_count": 1,
                "real_due_point_count": 1,
                "simulated_due_point_count": 0,
                "result_counts": {
                    "blocked": 0,
                    "busy": 0,
                    "completed": 1,
                    "failed": 0,
                    "skipped": 0,
                },
                "missing_due_point_ids": [],
                "unexpected_due_point_ids": [],
                "duplicate_due_point_ids": [],
                "max_start_delay_seconds": 0,
                "max_duration_seconds": 60,
                "risk_count": 0,
                "blocked_count": 0,
                "missing_ack_count": 0,
                "reasons": [],
            }
        },
        "integrity_error": None,
    }


def _readiness():
    gates = {
        name: {
            "gate": name,
            "status": "passed" if name in {"G0", "G1", "G2", "G3"} else "not_reached",
            "reasons": [],
            "evidence": {},
        }
        for name in ("G0", "G1", "G2", "G3", "G4", "G5", "G6")
    }
    return {
        "target": "pre_soak",
        "evidence_kind": "real",
        "generated_at": "2026-07-29T10:00:00+08:00",
        "summary": {
            "ack_required_alert_ids": ["alert-1"],
            "ack_ready": True,
        },
        "gates": gates,
        "record": {},
        "warnings": [],
        "ready_for_pre_soak": True,
        "ready_for_24h_soak": False,
    }


def _build(tmp_path, **overrides):
    approval = _approval()
    values = {
        "baseline": _baseline(tmp_path),
        "ack": _ack(),
        "scheduler_evidence": _scheduler(),
        "scheduler_expected": {"G2": ["due-1"]},
        "remediation_approval": approval,
        "current_remediation_plan_hash": approval.source_plan_hash,
        "readiness": _readiness(),
        "allowed_roots": [tmp_path],
        "assembled_at": "2026-07-29T10:00:00+08:00",
    }
    values.update(overrides)
    return build_soak_evidence_bundle(**values)


def test_complete_object_bundle_is_deterministic_and_never_authorizes(tmp_path):
    first = _build(tmp_path)
    second = _build(tmp_path)

    assert first.status == "evidence_complete"
    assert first.bundle_id == second.bundle_id
    assert first.manifest_hash == second.manifest_hash
    assert first.to_json() == second.to_json()
    assert first.assembled_at == "2026-07-29T10:00:00+08:00"
    assert not first.authorizes_execution
    assert not first.authorizes_soak
    assert all(
        first.safety[name] is False
        for name in (
            "execution_authorized",
            "pre_soak_start_authorized",
            "soak_24h_start_authorized",
            "scheduler_start_authorized",
        )
    )


def test_missing_and_invalid_sources_fail_closed_without_raising(tmp_path):
    bundle = _build(
        tmp_path,
        baseline=None,
        ack={"ready": True},
        scheduler_evidence={"ready": True},
    )

    assert bundle.status == "incomplete"
    assert bundle.sources["baseline"].status == "missing"
    assert bundle.sources["scheduler"].status == "invalid"
    assert not bundle.authorizes_execution
    # Sensitive input is rejected rather than copied into a failed bundle.
    with pytest.raises(SoakEvidenceBundleError, match="sensitive field"):
        _build(tmp_path, ack={"ready": True, "cookie": "x"})


def test_semantic_gaps_are_not_ready_but_sources_remain_valid(tmp_path):
    ack = _ack()
    ack["ready"] = False
    ack["unresolved_alert_ids"] = ["alert-1"]
    approval = _approval().as_dict()
    approval["plan_approval_status"] = "pending_review"
    unsigned = dict(approval)
    unsigned.pop("manifest_hash")
    # Deliberately damaged approval hash makes the source invalid, not trusted.
    bundle = _build(tmp_path, ack=ack, remediation_approval=approval)

    assert bundle.status == "incomplete"
    assert bundle.sources["ack"].status == "valid"
    assert "ACK readiness is false" in bundle.sources["ack"].gaps
    assert bundle.sources["remediation_approval"].status == "invalid"


def test_file_inputs_are_hashed_and_path_escape_is_rejected(tmp_path):
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(
        json.dumps(_readiness(), ensure_ascii=False),
        encoding="utf-8",
    )
    bundle = _build(tmp_path, readiness=readiness_path)

    assert bundle.sources["readiness"].source_kind == "file"
    assert len(bundle.sources["readiness"].source_hash) == 64

    outside = tmp_path.parent / "outside-readiness.json"
    outside.write_text(json.dumps(_readiness()), encoding="utf-8")
    with pytest.raises(SoakEvidenceBundlePathError, match="outside"):
        _build(tmp_path, readiness=outside)


def test_missing_file_fails_closed_and_symlink_escape_is_rejected(tmp_path):
    missing = tmp_path / "missing.json"
    bundle = _build(tmp_path, readiness=missing)
    assert bundle.status == "incomplete"
    assert bundle.sources["readiness"].status == "invalid"

    outside = tmp_path.parent / "real-readiness.json"
    outside.write_text(json.dumps(_readiness()), encoding="utf-8")
    link = tmp_path / "linked-readiness.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(SoakEvidenceBundlePathError):
        _build(tmp_path, readiness=link)


def test_true_authorization_in_readiness_is_invalid_and_stays_false(tmp_path):
    readiness = _readiness()
    readiness["record"] = {"scheduler_start_authorized": True}
    bundle = _build(tmp_path, readiness=readiness)

    assert bundle.status == "incomplete"
    assert bundle.sources["readiness"].status == "invalid"
    assert "true authorization" in " ".join(bundle.gaps)
    assert bundle.safety["scheduler_start_authorized"] is False


def test_scheduler_expected_is_part_of_deterministic_identity(tmp_path):
    first = _build(tmp_path, scheduler_expected={"G2": ["due-1"]})
    second = _build(tmp_path, scheduler_expected={"G2": ["due-2"]})

    assert first.sources["scheduler"].details["expected_hash"] != second.sources[
        "scheduler"
    ].details["expected_hash"]
    assert first.bundle_id != second.bundle_id


def test_baseline_file_input_rechecks_observed_files_within_allowed_roots(
    tmp_path,
):
    baseline_root = tmp_path / "baseline-project"
    baseline_root.mkdir()
    baseline = _baseline(baseline_root)
    baseline_path = baseline_root / "baseline.json"
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")
    (baseline_root / "agent.py").write_text(
        "print('changed after baseline')\n",
        encoding="utf-8",
    )

    bundle = _build(tmp_path, baseline=baseline_path)

    assert bundle.status == "incomplete"
    assert bundle.sources["baseline"].status == "invalid"


def test_approval_freshness_uses_explicit_assembly_time_and_positive_max_age(
    tmp_path,
):
    stale = _build(
        tmp_path,
        assembled_at="2026-07-31T10:00:01+08:00",
        max_approval_age=timedelta(days=2),
    )
    future = _build(
        tmp_path,
        assembled_at="2026-07-29T08:30:00+08:00",
    )

    assert stale.status == "not_ready"
    assert "expired" in " ".join(stale.sources["remediation_approval"].gaps)
    assert future.status == "not_ready"
    assert "future" in " ".join(future.sources["remediation_approval"].gaps)
    with pytest.raises(SoakEvidenceBundleError, match="assembled_at"):
        _build(tmp_path, assembled_at="not-a-time")
    with pytest.raises(SoakEvidenceBundleError, match="max_approval_age"):
        _build(tmp_path, max_approval_age=timedelta(0))


def test_current_plan_hash_is_explicit_and_legacy_omission_is_not_ready(
    tmp_path,
):
    approval = _approval()
    legacy = _build(
        tmp_path,
        remediation_approval=approval,
        current_remediation_plan_hash=None,
    )
    drifted = _build(
        tmp_path,
        remediation_approval=approval,
        current_remediation_plan_hash="0" * 64,
    )

    assert legacy.status == "not_ready"
    assert "cannot be verified" in " ".join(
        legacy.sources["remediation_approval"].gaps
    )
    assert drifted.status == "not_ready"
    assert "plan drift" in " ".join(
        drifted.sources["remediation_approval"].gaps
    )


@pytest.mark.parametrize(
    ("field", "gate"),
    (
        ("ready_for_pre_soak", "G3"),
        ("ready_for_24h_soak", "G4"),
    ),
)
def test_readiness_top_level_flags_must_match_gate_statuses(
    tmp_path,
    field,
    gate,
):
    readiness = _readiness()
    readiness[field] = True
    readiness["gates"][gate]["status"] = "failed"

    bundle = _build(tmp_path, readiness=readiness)

    assert bundle.status == "incomplete"
    assert bundle.sources["readiness"].status == "invalid"
    assert "contradicts" in " ".join(bundle.sources["readiness"].gaps)


def test_bundle_round_trip_and_tamper_detection(tmp_path):
    bundle = _build(tmp_path)
    target = write_soak_evidence_bundle(
        tmp_path / "bundle.json",
        bundle,
        allowed_roots=[tmp_path],
    )
    restored = read_soak_evidence_bundle(target, allowed_roots=[tmp_path])
    assert restored == bundle

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["status"] = "incomplete"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        SoakEvidenceBundleIntegrityError, match="manifest hash"
    ):
        read_soak_evidence_bundle(target, allowed_roots=[tmp_path])


def test_unknown_or_sensitive_stored_fields_are_rejected(tmp_path):
    bundle = _build(tmp_path).as_dict()
    bundle["api_token"] = "x"
    with pytest.raises(SoakEvidenceBundleError, match="sensitive field"):
        validate_soak_evidence_bundle(bundle)

    bundle = _build(tmp_path).as_dict()
    bundle["unknown"] = True
    with pytest.raises(SoakEvidenceBundleIntegrityError, match="fields"):
        validate_soak_evidence_bundle(bundle)


def test_damaged_source_objects_never_turn_into_authorization(tmp_path):
    readiness = deepcopy(_readiness())
    readiness["generated_at"] = "not-a-time"
    scheduler = deepcopy(_scheduler())
    scheduler["ledger_integrity_ok"] = False
    scheduler["integrity_error"] = "damaged"

    bundle = _build(
        tmp_path,
        readiness=readiness,
        scheduler_evidence=scheduler,
    )

    assert bundle.status == "not_ready"
    assert bundle.sources["scheduler"].details["integrity_ok"] is False
    assert "generated_at" in " ".join(bundle.sources["readiness"].gaps)
    assert all(
        value is False
        for key, value in bundle.safety.items()
        if key != "statement"
    )
