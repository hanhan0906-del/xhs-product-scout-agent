import hashlib
import json

import pytest

from xhs_scout.remediation import plan_remediation
from xhs_scout.remediation_approval import (
    RemediationApprovalError,
    RemediationApprovalIntegrityError,
    build_approval_manifest,
    read_approval_manifest,
    serialize_approval_manifest,
    write_approval_manifest,
)


NOW = "2026-07-29T16:00:00+08:00"


def product(product_id, **overrides):
    row = {
        "product_id": product_id,
        "status": "candidate",
        "score": 50,
        "has_valid_search_attribution": 1,
        "has_supported_product_link": 1,
        "has_metrics_strip": 1,
        "has_note_evidence": 1,
        "has_profile_evidence": 1,
    }
    row.update(overrides)
    return row


def plan_for(*rows):
    return plan_remediation(rows, now=NOW)


def selection(plan, *product_ids):
    batch_id_by_product = {
        item.product_id: batch.batch_id
        for batch in plan.batches
        for item in batch.items
    }
    grouped = []
    for product_id in product_ids:
        batch_id = batch_id_by_product[product_id]
        existing = next(
            (item for item in grouped if item["batch_id"] == batch_id), None
        )
        if existing:
            existing["product_ids"].append(product_id)
        else:
            grouped.append({"batch_id": batch_id, "product_ids": [product_id]})
    return grouped


def issue_codes(manifest):
    return {issue.code for issue in manifest.issues}


def test_valid_batch_can_be_plan_approved_but_is_never_executed(tmp_path):
    plan = plan_for(
        product(9, has_valid_search_attribution=0, has_supported_product_link=0),
        product(11, has_supported_product_link=0),
    )

    manifest = build_approval_manifest(
        plan,
        selection(plan, 9, 11),
        decision="approve",
        reviewer="operator-a",
        reviewed_at=NOW,
    )
    path = write_approval_manifest(tmp_path / "approval.json", manifest)

    assert manifest.valid is True
    assert manifest.plan_approval_status == "planned_approved"
    assert manifest.execution_status == "not_executed"
    assert manifest.authorizes_execution is False
    assert len(manifest.selected_batches[0].items) == 2
    assert read_approval_manifest(path) == manifest
    assert list(tmp_path.iterdir()) == [path]


def test_default_is_pending_review_and_serialization_is_deterministic():
    plan = plan_for(product(18, has_metrics_strip=0))
    first = build_approval_manifest(plan, selection(plan, 18), reviewed_at=NOW)
    second = build_approval_manifest(plan, selection(plan, 18), reviewed_at=NOW)

    assert first.plan_approval_status == "pending_review"
    assert first.execution_status == "not_executed"
    assert first == second
    assert serialize_approval_manifest(first) == serialize_approval_manifest(second)
    assert json.loads(first.to_json())["authorizes_execution"] is False


def test_more_than_two_products_in_one_selected_batch_is_rejected():
    plan = json.loads(
        json.dumps(
            plan_for(
                product(1, has_supported_product_link=0),
                product(2, has_supported_product_link=0),
                product(3, has_supported_product_link=0),
            ).as_dict()
        )
    )
    plan["batches"][0]["items"].append(plan["batches"][1]["items"][0])
    plan["batches"][0]["items"][-1]["stage"] = "identity"
    plan["batches"] = plan["batches"][:1]

    manifest = build_approval_manifest(
        plan,
        [{"batch_id": "identity-01", "product_ids": [1, 2, 3]}],
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    assert {"planner_batch_over_budget", "batch_over_budget"} <= issue_codes(manifest)


def test_more_than_six_visits_in_one_hour_is_rejected():
    plan = plan_for(
        *(product(i, has_supported_product_link=0) for i in range(1, 8))
    ).as_dict()
    for batch in plan["batches"]:
        batch["hour_window"] = 1

    manifest = build_approval_manifest(
        plan,
        [
            {
                "batch_id": batch["batch_id"],
                "product_ids": [item["product_id"] for item in batch["items"]],
            }
            for batch in plan["batches"]
        ],
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    assert "hourly_over_budget" in issue_codes(manifest)


def test_cross_stage_selection_order_is_rejected():
    plan = plan_for(
        product(9, has_supported_product_link=0),
        product(18, has_metrics_strip=0),
    )
    batches = {batch.stage: batch for batch in plan.batches}

    manifest = build_approval_manifest(
        plan,
        [
            {"batch_id": batches["metrics"].batch_id, "product_ids": [18]},
            {"batch_id": batches["identity"].batch_id, "product_ids": [9]},
        ],
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    assert "selection_stage_order" in issue_codes(manifest)


def test_quarantine_product_20_cannot_be_released_by_tampered_plan():
    plan = plan_for(
        product(
            20,
            quarantine_released=1,
            latest_search_attribution_valid=1,
            has_supported_product_link=0,
        )
    )

    manifest = build_approval_manifest(
        plan,
        selection(plan, 20),
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    assert {"quarantined_in_plan", "quarantined_product"} <= issue_codes(manifest)


@pytest.mark.parametrize("product_id", [19, 20])
@pytest.mark.parametrize("stage", ["note", "profile"])
def test_low_follower_stop_products_never_enter_note_or_profile(product_id, stage):
    rows = (
        [product(product_id, has_note_evidence=0, has_profile_evidence=0)]
        if stage == "note"
        else [
            product(
                product_id,
                has_profile_evidence=0,
                note_author_identifiable=1,
                note_published_days_ago=1,
                note_likes=1000,
            )
        ]
    )
    plan = plan_for(*rows)
    if not plan.batches:
        # T24 already stopped a known high-follower profile; fabricate only the
        # planner contract violation that this approval layer must catch.
        plan = plan_for(
            product(
                30,
                has_profile_evidence=0,
                note_author_identifiable=1,
                note_published_days_ago=1,
                note_likes=1000,
            )
        ).as_dict()
        plan["batches"][0]["items"][0]["product_id"] = product_id
    manifest = build_approval_manifest(
        plan,
        [{"batch_id": f"{stage}-01", "product_ids": [product_id]}],
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    assert {"low_follower_stop_in_plan", "low_follower_stop"} & issue_codes(manifest)


def test_missing_dependencies_in_tampered_item_are_rejected():
    plan = plan_for(product(18, has_metrics_strip=0)).as_dict()
    plan["batches"][0]["items"][0]["required_before"] = []

    manifest = build_approval_manifest(
        plan,
        [{"batch_id": "metrics-01", "product_ids": [18]}],
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    assert "dependency_contract_mismatch" in issue_codes(manifest)


def test_duplicate_product_selection_and_wrong_batch_fail_closed():
    plan = plan_for(
        product(9, has_supported_product_link=0),
        product(18, has_metrics_strip=0),
    )
    identity = next(batch for batch in plan.batches if batch.stage == "identity")
    metrics = next(batch for batch in plan.batches if batch.stage == "metrics")

    manifest = build_approval_manifest(
        plan,
        [
            {"batch_id": identity.batch_id, "product_ids": [9, 18]},
            {"batch_id": metrics.batch_id, "product_ids": [18]},
        ],
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    assert {"product_not_in_batch", "duplicate_selected_product"} <= issue_codes(manifest)


def test_bad_planner_input_and_unknown_batch_fail_closed():
    bad = build_approval_manifest(
        "not-a-plan",
        [{"batch_id": "identity-01", "product_ids": [1]}],
        decision="approve",
        reviewed_at=NOW,
    )
    unknown = build_approval_manifest(
        plan_for(product(1, has_supported_product_link=0)),
        [{"batch_id": "forged-01", "product_ids": [1]}],
        decision="approve",
        reviewed_at=NOW,
    )

    assert bad.plan_approval_status == "rejected"
    assert "invalid_plan" in issue_codes(bad)
    assert unknown.plan_approval_status == "rejected"
    assert "unknown_batch" in issue_codes(unknown)


def test_stored_manifest_tampering_is_detected(tmp_path):
    plan = plan_for(product(18, has_metrics_strip=0))
    manifest = build_approval_manifest(
        plan,
        selection(plan, 18),
        decision="approve",
        reviewed_at=NOW,
    )
    path = write_approval_manifest(tmp_path / "approval.json", manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["execution_status"] = "executed"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RemediationApprovalIntegrityError, match="integrity hash"):
        read_approval_manifest(path)


def test_rehashed_execution_claim_still_fails_semantic_validation(tmp_path):
    plan = plan_for(product(18, has_metrics_strip=0))
    manifest = build_approval_manifest(
        plan,
        selection(plan, 18),
        decision="approve",
        reviewed_at=NOW,
    )
    path = write_approval_manifest(tmp_path / "approval.json", manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["execution_status"] = "executed"
    unsigned = dict(payload)
    unsigned.pop("manifest_hash")
    payload["manifest_hash"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RemediationApprovalError, match="not executed"):
        read_approval_manifest(path)
