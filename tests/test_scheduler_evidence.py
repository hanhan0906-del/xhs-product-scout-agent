import json
from datetime import datetime, timedelta, timezone

import pytest

from xhs_scout.scheduler_evidence import (
    SchedulerEvidenceError,
    SchedulerEvidenceIntegrityError,
    append_scheduler_evidence,
    evaluate_scheduler_evidence,
    read_scheduler_evidence,
)


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 7, 29, 18, 0, tzinfo=TZ)


def _artifacts(root, suffix):
    paths = {}
    for name in ("db", "http", "round"):
        path = root / "evidence" / f"{suffix}-{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"kind": name, "suffix": suffix}),
            encoding="utf-8",
        )
        paths[name] = path
    return paths


def _evidence(root, index=1, *, stage="G2", source="real", **overrides):
    artifacts = _artifacts(root, f"{stage.lower()}-{index}")
    scheduled = BASE + timedelta(hours=index - 1)
    started = scheduled + timedelta(minutes=2)
    finished = started + timedelta(minutes=3)
    value = {
        "record_id": f"record-{stage.lower()}-{index}",
        "stage": stage,
        "soak_id": "offline-fixture",
        "due_point_id": f"due-{stage.lower()}-{index}",
        "evidence_source": source,
        "scheduled_at": scheduled.isoformat(),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "start_delay_seconds": 120,
        "duration_seconds": 180,
        "result": "completed",
        "run_id": f"monitor-{stage.lower()}-{index}",
        "task_id": index,
        "product_id": 100 + index,
        "observation_id": 200 + index,
        "keyword": f"keyword-{index}",
        "keyword_source": "portfolio",
        "portfolio_cursor_before": index - 1,
        "portfolio_cursor_after": index,
        "portfolio_selected": [f"keyword-{index}"],
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


def _append(root, evidence):
    return append_scheduler_evidence(
        root / "scheduler-evidence.jsonl",
        allowed_roots=[root],
        evidence=evidence,
    )


def test_complete_real_due_points_hash_chain_and_stage_summary(tmp_path):
    g2 = [_append(tmp_path, _evidence(tmp_path, index)) for index in range(1, 4)]
    g4 = [
        _append(tmp_path, _evidence(tmp_path, index, stage="G4"))
        for index in range(1, 3)
    ]

    records = read_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
    )
    report = evaluate_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
        expected_due_points={
            "G2": [record.due_point_id for record in g2],
            "G4": [record.due_point_id for record in g4],
        },
    )

    assert records == tuple(g2 + g4)
    assert [record.sequence for record in records] == [1, 2, 3, 4, 5]
    assert records[1].previous_hash == records[0].record_hash
    assert records[-1].previous_hash == records[-2].record_hash
    assert report.ready is True
    assert report.ledger_integrity_ok is True
    assert report.stages["G2"].ready_for_gate_evaluation is True
    assert report.stages["G2"].real_due_point_count == 3
    assert report.stages["G4"].result_counts["completed"] == 2


def test_simulated_due_points_are_recorded_but_never_admissible(tmp_path):
    for index in range(1, 4):
        _append(
            tmp_path,
            _evidence(tmp_path, index, source="simulated"),
        )

    report = evaluate_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
        expected_due_points={"G2": 3},
    )

    assert report.ready is False
    assert report.stages["G2"].real_due_point_count == 0
    assert report.stages["G2"].simulated_due_point_count == 3
    assert any("simulated" in reason for reason in report.stages["G2"].reasons)


def test_missing_due_point_and_missing_field_fail_closed(tmp_path):
    _append(tmp_path, _evidence(tmp_path, 1))
    report = evaluate_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
        expected_due_points={"G2": ["due-g2-1", "due-g2-2"]},
    )

    assert report.ready is False
    assert report.stages["G2"].missing_due_point_ids == ("due-g2-2",)

    incomplete = _evidence(tmp_path, 2)
    incomplete.pop("scheduler_thread_alive")
    with pytest.raises(SchedulerEvidenceError, match="missing="):
        _append(tmp_path, incomplete)


def test_duplicate_sequence_and_duplicate_due_point_are_rejected(tmp_path):
    _append(tmp_path, _evidence(tmp_path, 1))
    _append(tmp_path, _evidence(tmp_path, 2))
    ledger = tmp_path / "scheduler-evidence.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    rows[1]["sequence"] = 1
    ledger.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SchedulerEvidenceIntegrityError,
        match="non-contiguous sequence",
    ):
        read_scheduler_evidence(ledger, allowed_roots=[tmp_path])

    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    _append(clean_root, _evidence(clean_root, 1))
    duplicate = _evidence(clean_root, 2, due_point_id="due-g2-1")
    with pytest.raises(SchedulerEvidenceError, match="already exists"):
        _append(clean_root, duplicate)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "started_at",
            (BASE - timedelta(seconds=1)).isoformat(),
            "must not precede scheduled_at",
        ),
        (
            "finished_at",
            BASE.isoformat(),
            "must not precede started_at",
        ),
    ],
)
def test_time_inversion_is_rejected(tmp_path, field, value, message):
    evidence = _evidence(tmp_path)
    evidence[field] = value

    with pytest.raises(SchedulerEvidenceError, match=message):
        _append(tmp_path, evidence)


def test_delay_over_limit_is_preserved_but_stage_fails_closed(tmp_path):
    scheduled = BASE
    started = BASE + timedelta(minutes=16)
    finished = started + timedelta(minutes=3)
    _append(
        tmp_path,
        _evidence(
            tmp_path,
            scheduled_at=scheduled.isoformat(),
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            start_delay_seconds=960,
            duration_seconds=180,
        ),
    )

    report = evaluate_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
        expected_due_points={"G2": 1},
    )

    assert report.ready is False
    assert report.stages["G2"].max_start_delay_seconds == 960
    assert any("exceeds 900" in reason for reason in report.stages["G2"].reasons)


def test_bad_json_and_hash_tampering_fail_integrity_and_summary(tmp_path):
    _append(tmp_path, _evidence(tmp_path))
    ledger = tmp_path / "scheduler-evidence.jsonl"
    ledger.write_text("{bad json}\n", encoding="utf-8")

    report = evaluate_scheduler_evidence(
        ledger,
        allowed_roots=[tmp_path],
        expected_due_points={"G2": ["due-g2-1"]},
    )
    assert report.ready is False
    assert report.ledger_integrity_ok is False
    assert "invalid JSON" in report.integrity_error

    other = tmp_path / "tamper"
    other.mkdir()
    _append(other, _evidence(other))
    other_ledger = other / "scheduler-evidence.jsonl"
    row = json.loads(other_ledger.read_text(encoding="utf-8"))
    row["keyword"] = "tampered-keyword"
    other_ledger.write_text(
        json.dumps(row, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SchedulerEvidenceIntegrityError, match="invalid record hash"):
        read_scheduler_evidence(other_ledger, allowed_roots=[other])


def test_risk_and_block_require_ack_reference_and_never_promote(tmp_path):
    blocked = _evidence(
        tmp_path,
        result="blocked",
        product_id=None,
        observation_id=None,
        risk_stop_reason="captcha detected",
        last_block_reason="scheduler paused by hard guard",
        lease_state="not_acquired",
        desired_state="paused",
        scheduler_running=False,
        scheduler_thread_alive=False,
        scheduler_worker_state="risk_paused",
        http_status={
            "api_status": 200,
            "monitor_status": 200,
            "candidates_csv": 200,
        },
    )
    _append(tmp_path, blocked)
    without_ack = evaluate_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
        expected_due_points={"G2": 1},
    )

    assert without_ack.ready is False
    assert without_ack.stages["G2"].risk_count == 1
    assert without_ack.stages["G2"].blocked_count == 1
    assert without_ack.stages["G2"].missing_ack_count == 1

    acked_root = tmp_path / "acked"
    acked_root.mkdir()
    acked = _evidence(
        acked_root,
        result="blocked",
        product_id=None,
        observation_id=None,
        risk_stop_reason="captcha detected",
        last_block_reason="scheduler paused by hard guard",
        lease_state="not_acquired",
        desired_state="paused",
        scheduler_running=False,
        scheduler_thread_alive=False,
        scheduler_worker_state="risk_paused",
        operator_ack_refs=["soak-ack.jsonl#ack-risk-001"],
    )
    _append(acked_root, acked)
    with_ack = evaluate_scheduler_evidence(
        acked_root / "scheduler-evidence.jsonl",
        allowed_roots=[acked_root],
        expected_due_points={"G2": 1},
    )

    assert with_ack.ready is False
    assert with_ack.stages["G2"].missing_ack_count == 0
    assert with_ack.stages["G2"].risk_count == 1


@pytest.mark.parametrize(
    ("result", "updates"),
    [
        (
            "busy",
            {
                "run_id": None,
                "task_id": None,
                "product_id": None,
                "observation_id": None,
                "keyword": None,
                "keyword_source": None,
                "portfolio_selected": [],
                "lease_state": "not_acquired",
            },
        ),
        (
            "skipped",
            {
                "run_id": None,
                "task_id": None,
                "product_id": None,
                "observation_id": None,
                "keyword": None,
                "keyword_source": None,
                "portfolio_selected": [],
                "last_skip_reason": "keyword cooldown",
                "lease_state": "not_acquired",
            },
        ),
        (
            "blocked",
            {
                "run_id": None,
                "task_id": None,
                "product_id": None,
                "observation_id": None,
                "keyword": None,
                "keyword_source": None,
                "portfolio_selected": [],
                "last_block_reason": "scheduler error budget exhausted",
                "lease_state": "not_acquired",
                "desired_state": "paused",
                "scheduler_running": False,
                "scheduler_thread_alive": False,
                "operator_ack_refs": ["soak-ack.jsonl#ack-block-001"],
            },
        ),
    ],
)
def test_busy_skipped_and_blocked_are_explicit_supported_outcomes(
    tmp_path,
    result,
    updates,
):
    evidence = _evidence(tmp_path, result=result, **updates)
    record = _append(tmp_path, evidence)

    assert record.result == result
    assert read_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
    ) == (record,)


def test_summary_is_deterministic_and_carries_cursor_db_http_and_ack_fields(
    tmp_path,
):
    record = _append(
        tmp_path,
        _evidence(
            tmp_path,
            operator_ack_refs=["soak-ack.jsonl#ack-info-001"],
        ),
    )
    first = evaluate_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
        expected_due_points={"G2": ["due-g2-1"]},
    )
    second = evaluate_scheduler_evidence(
        tmp_path / "scheduler-evidence.jsonl",
        allowed_roots=[tmp_path],
        expected_due_points={"G2": ["due-g2-1"]},
    )

    assert first.as_dict() == second.as_dict()
    assert record.portfolio_cursor_before == 0
    assert record.portfolio_cursor_after == 1
    assert record.db_status == "ok"
    assert record.http_status == {
        "api_status": 200,
        "candidates_csv": 200,
        "monitor_status": 200,
    }
    assert record.operator_ack_refs == ("soak-ack.jsonl#ack-info-001",)
