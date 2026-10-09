import json
from datetime import datetime, timedelta, timezone

import pytest

from xhs_scout.soak_ack import (
    SoakAckConflictError,
    SoakAckError,
    SoakAckIntegrityError,
    append_soak_ack,
    evaluate_ack_readiness,
    read_soak_acks,
)


TZ = timezone(timedelta(hours=8))
AT = datetime(2026, 7, 29, 16, 30, tzinfo=TZ)


def _evidence(root, name="quality.json"):
    path = root / "evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"status":"reviewed"}', encoding="utf-8")
    return path


def _append(root, *, record_id="ack-001", alert_id="quality-001", **overrides):
    values = {
        "ledger_path": root / "acks" / "soak-ack.jsonl",
        "allowed_roots": [root],
        "record_id": record_id,
        "alert_id": alert_id,
        "alert_kind": "quality",
        "actor": "operator-a",
        "decision": "acknowledge",
        "evidence_path": _evidence(root),
        "note": "reviewed offline snapshot",
        "decided_at": AT,
    }
    values.update(overrides)
    return append_soak_ack(**values)


def test_appends_valid_ack_and_reads_deterministically(tmp_path):
    first = _append(tmp_path)
    second = _append(
        tmp_path,
        record_id="ack-002",
        alert_id="digest-001",
        alert_kind="digest",
        decision="defer",
        evidence_path=_evidence(tmp_path, "digest.json"),
        decided_at=AT + timedelta(minutes=5),
    )

    records = read_soak_acks(
        tmp_path / "acks" / "soak-ack.jsonl",
        allowed_roots=[tmp_path],
    )

    assert records == (first, second)
    assert [record.sequence for record in records] == [1, 2]
    assert second.previous_hash == first.record_hash
    assert records[0].evidence_path == str(_evidence(tmp_path).resolve())


def test_same_record_is_idempotent_but_conflicting_record_id_is_rejected(tmp_path):
    first = _append(tmp_path)

    assert _append(tmp_path) == first
    with pytest.raises(SoakAckConflictError, match="different content"):
        _append(tmp_path, decision="reject")

    assert len(
        read_soak_acks(
            tmp_path / "acks" / "soak-ack.jsonl",
            allowed_roots=[tmp_path],
        )
    ) == 1


def test_later_decision_preserves_history_and_latest_decision_controls_readiness(
    tmp_path,
):
    _append(tmp_path, decision="defer")
    deferred = evaluate_ack_readiness(
        tmp_path / "acks" / "soak-ack.jsonl",
        allowed_roots=[tmp_path],
        required_alert_ids=["quality-001"],
    )
    _append(
        tmp_path,
        record_id="ack-002",
        decision="acknowledge",
        decided_at=AT + timedelta(minutes=10),
    )
    acknowledged = evaluate_ack_readiness(
        tmp_path / "acks" / "soak-ack.jsonl",
        allowed_roots=[tmp_path],
        required_alert_ids=["quality-001"],
    )

    assert deferred.ready is False
    assert deferred.unresolved_alert_ids == ("quality-001",)
    assert acknowledged.ready is True
    assert acknowledged.latest_decisions == {"quality-001": "acknowledge"}
    assert len(
        read_soak_acks(
            tmp_path / "acks" / "soak-ack.jsonl",
            allowed_roots=[tmp_path],
        )
    ) == 2


@pytest.mark.parametrize(
    "replacement",
    [
        "{bad json}\n",
        '{"schema_version":1}\n',
    ],
)
def test_bad_json_or_incomplete_record_fails_closed(tmp_path, replacement):
    _append(tmp_path)
    ledger = tmp_path / "acks" / "soak-ack.jsonl"
    ledger.write_text(replacement, encoding="utf-8")

    with pytest.raises(SoakAckIntegrityError):
        read_soak_acks(ledger, allowed_roots=[tmp_path])
    report = evaluate_ack_readiness(
        ledger,
        allowed_roots=[tmp_path],
        required_alert_ids=["quality-001"],
    )
    assert report.ready is False
    assert report.integrity_error


def test_hash_tampering_and_truncated_final_line_fail_closed(tmp_path):
    _append(tmp_path)
    ledger = tmp_path / "acks" / "soak-ack.jsonl"
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    payload["decision"] = "reject"
    ledger.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(SoakAckIntegrityError, match="invalid record hash"):
        read_soak_acks(ledger, allowed_roots=[tmp_path])

    ledger.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    report = evaluate_ack_readiness(
        ledger,
        allowed_roots=[tmp_path],
        required_alert_ids=["quality-001"],
    )
    assert report.ready is False
    assert "truncated" in report.integrity_error


def test_evidence_and_ledger_paths_must_stay_inside_allowed_roots(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(SoakAckError, match="evidence_path resolves outside"):
        append_soak_ack(
            project / "acks.jsonl",
            allowed_roots=[project],
            record_id="ack-001",
            alert_id="quality-001",
            alert_kind="quality",
            actor="operator-a",
            decision="acknowledge",
            evidence_path=outside,
            decided_at=AT,
        )
    with pytest.raises(SoakAckError, match="ledger_path resolves outside"):
        append_soak_ack(
            tmp_path / "outside-ledger.jsonl",
            allowed_roots=[project],
            record_id="ack-001",
            alert_id="quality-001",
            alert_kind="quality",
            actor="operator-a",
            decision="acknowledge",
            evidence_path=_evidence(project),
            decided_at=AT,
        )


@pytest.mark.parametrize("field", ["token", "Cookie", "api_token", "credentials"])
def test_sensitive_fields_in_ledger_are_rejected(tmp_path, field):
    record = _append(tmp_path)
    ledger = tmp_path / "acks" / "soak-ack.jsonl"
    payload = record.as_dict()
    payload[field] = "must-not-be-stored"
    ledger.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(SoakAckIntegrityError, match="sensitive field"):
        read_soak_acks(ledger, allowed_roots=[tmp_path])
    assert (
        evaluate_ack_readiness(
            ledger,
            allowed_roots=[tmp_path],
            required_alert_ids=["quality-001"],
        ).ready
        is False
    )


def test_missing_ack_and_empty_required_set_fail_closed(tmp_path):
    missing = evaluate_ack_readiness(
        tmp_path / "missing.jsonl",
        allowed_roots=[tmp_path],
        required_alert_ids=["critical-001", "quality-001"],
    )
    empty_scope = evaluate_ack_readiness(
        tmp_path / "missing.jsonl",
        allowed_roots=[tmp_path],
        required_alert_ids=[],
    )

    assert missing.ready is False
    assert missing.missing_alert_ids == ("critical-001", "quality-001")
    assert empty_scope.ready is False
    assert empty_scope.integrity_error == "no required alert ids were supplied"


def test_naive_datetime_and_missing_evidence_are_rejected(tmp_path):
    with pytest.raises(SoakAckError, match="timezone"):
        _append(tmp_path, decided_at=datetime(2026, 7, 29, 16, 30))
    missing = tmp_path / "evidence" / "missing.json"
    with pytest.raises(SoakAckError, match="does not exist"):
        _append(tmp_path, evidence_path=missing)
