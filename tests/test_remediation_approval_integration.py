from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

import pytest

from xhs_scout.remediation import STAGE_ORDER, plan_remediation
from xhs_scout.remediation_approval import (
    build_approval_manifest,
    read_approval_manifest,
    write_approval_manifest,
)


NOW = "2026-07-29T16:00:00+08:00"


def _product(product_id: int, **overrides):
    row = {
        "product_id": product_id,
        "status": "candidate",
        "priority": 0,
        "score": 50,
        "has_valid_search_attribution": 1,
        "latest_search_attribution_valid": 1,
        "has_supported_product_link": 1,
        "has_metrics_strip": 1,
        "has_note_evidence": 1,
        "has_profile_evidence": 1,
    }
    row.update(overrides)
    return row


def _plan(*rows):
    return plan_remediation(rows, now=NOW)


def _selections(plan):
    return [
        {
            "batch_id": batch.batch_id,
            "product_ids": [item.product_id for item in batch.items],
        }
        for batch in plan.batches
    ]


def _issue_codes(manifest):
    return {issue.code for issue in manifest.issues}


def _canonical_plan_hash(plan) -> str:
    payload = plan.as_dict() if hasattr(plan, "as_dict") else plan
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _walk_strings(value):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _walk_strings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, str):
        yield value


def test_t41_representative_snapshot_flows_through_all_stages_in_order():
    plan = _plan(
        _product(
            9,
            priority=40,
            has_valid_search_attribution=0,
            latest_search_attribution_valid=None,
            has_supported_product_link=0,
            has_metrics_strip=0,
            has_note_evidence=0,
            has_profile_evidence=0,
        ),
        _product(
            18,
            priority=30,
            has_metrics_strip=0,
            has_note_evidence=0,
            has_profile_evidence=0,
        ),
        _product(
            13,
            priority=20,
            has_note_evidence=0,
            has_profile_evidence=0,
        ),
        _product(
            17,
            priority=10,
            has_profile_evidence=0,
            note_author_identifiable=1,
            note_published_days_ago=1,
            note_likes=1_000,
            potential_follower_ceiling=2_000,
        ),
    )

    assert tuple(batch.stage for batch in plan.batches) == STAGE_ORDER
    assert {
        item.product_id: (item.stage, item.required_before, item.blocks)
        for batch in plan.batches
        for item in batch.items
    } == {
        9: ("identity", (), ("metrics", "note", "profile")),
        18: (
            "metrics",
            ("valid_search_attribution", "supported_product_link"),
            ("note", "profile"),
        ),
        13: (
            "note",
            (
                "valid_search_attribution",
                "supported_product_link",
                "metrics_strip",
            ),
            ("profile",),
        ),
        17: (
            "profile",
            (
                "valid_search_attribution",
                "supported_product_link",
                "metrics_strip",
                "recent_identifiable_note",
                "note_interaction_gate",
            ),
            (),
        ),
    }

    manifest = build_approval_manifest(
        plan,
        _selections(plan),
        decision="approve",
        reviewer="t48-offline",
        reviewed_at=NOW,
    )

    assert manifest.valid
    assert manifest.plan_approval_status == "planned_approved"
    assert [batch.stage for batch in manifest.selected_batches] == list(STAGE_ORDER)
    assert [
        item.required_before
        for batch in manifest.selected_batches
        for item in batch.items
    ] == [
        (),
        ("valid_search_attribution", "supported_product_link"),
        ("valid_search_attribution", "supported_product_link", "metrics_strip"),
        (
            "valid_search_attribution",
            "supported_product_link",
            "metrics_strip",
            "recent_identifiable_note",
            "note_interaction_gate",
        ),
    ]


def test_planned_approval_is_not_execution_and_contains_no_execution_surface(tmp_path):
    plan = _plan(
        _product(
            9,
            has_valid_search_attribution=0,
            latest_search_attribution_valid=None,
            has_supported_product_link=0,
        ),
        _product(11, has_supported_product_link=0),
    )
    manifest = build_approval_manifest(
        plan,
        _selections(plan),
        decision="approve",
        reviewer="t48-offline",
        reviewed_at=NOW,
    )
    path = write_approval_manifest(tmp_path / "approval.json", manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert manifest.plan_approval_status == "planned_approved"
    assert manifest.execution_status == "not_executed"
    assert manifest.authorizes_execution is False
    assert read_approval_manifest(path) == manifest
    assert list(tmp_path.iterdir()) == [path]
    assert set(payload) == {
        "schema_version",
        "manifest_id",
        "source_plan_hash",
        "source_generated_at",
        "reviewed_at",
        "reviewer",
        "requested_decision",
        "plan_approval_status",
        "execution_status",
        "authorizes_execution",
        "policy",
        "selected_batches",
        "issues",
        "manifest_hash",
    }
    assert set(payload["selected_batches"][0]) == {
        "batch_id",
        "stage",
        "hour_window",
        "items",
    }
    assert set(payload["selected_batches"][0]["items"][0]) == {
        "product_id",
        "status",
        "stage",
        "actions",
        "required_before",
    }
    serialized_strings = "\n".join(_walk_strings(payload)).casefold()
    for forbidden in (
        "http://",
        "https://",
        "adb ",
        "bluestacks",
        "8793",
        "8765",
        "queue_command",
        "device_command",
        "http_method",
        "enqueue",
    ):
        assert forbidden not in serialized_strings


def test_changed_planner_snapshot_makes_old_approval_stale():
    old_plan = _plan(
        _product(
            9,
            score=80,
            has_valid_search_attribution=0,
            latest_search_attribution_valid=None,
            has_supported_product_link=0,
        )
    )
    old_manifest = build_approval_manifest(
        old_plan,
        _selections(old_plan),
        decision="approve",
        reviewed_at=NOW,
    )

    refreshed_plan = _plan(
        _product(
            9,
            score=81,
            has_valid_search_attribution=0,
            latest_search_attribution_valid=None,
            has_supported_product_link=0,
        )
    )
    refreshed_manifest = build_approval_manifest(
        refreshed_plan,
        _selections(refreshed_plan),
        decision="approve",
        reviewed_at=NOW,
    )
    current_plan_hash = _canonical_plan_hash(refreshed_plan)

    assert old_manifest.source_plan_hash == _canonical_plan_hash(old_plan)
    assert refreshed_manifest.source_plan_hash == current_plan_hash
    assert old_manifest.source_plan_hash != current_plan_hash
    assert old_manifest.manifest_id != refreshed_manifest.manifest_id


def test_t41_identity_queue_respects_batch_and_hourly_budgets():
    t41_identity_ids = (9, 11, 12, 3, 1, 2, 22, 19, 18, 23, 13, 17, 16)
    plan = _plan(
        *(
            _product(
                product_id,
                priority=len(t41_identity_ids) - position,
                has_supported_product_link=0,
            )
            for position, product_id in enumerate(t41_identity_ids)
        )
    )

    assert [len(batch.items) for batch in plan.batches] == [2, 2, 2, 2, 2, 2, 1]
    assert [batch.hour_window for batch in plan.batches] == [1, 1, 1, 2, 2, 2, 3]
    assert all(batch.max_items == 2 for batch in plan.batches)

    approved = build_approval_manifest(
        plan,
        _selections(plan),
        decision="approve",
        reviewed_at=NOW,
    )
    assert approved.plan_approval_status == "planned_approved"

    tampered = plan.as_dict()
    for batch in tampered["batches"]:
        batch["hour_window"] = 1
    rejected = build_approval_manifest(
        tampered,
        [
            {
                "batch_id": batch["batch_id"],
                "product_ids": [item["product_id"] for item in batch["items"]],
            }
            for batch in tampered["batches"]
        ],
        decision="approve",
        reviewed_at=NOW,
    )
    assert rejected.plan_approval_status == "rejected"
    assert "hourly_over_budget" in _issue_codes(rejected)


def test_product_20_isolation_cannot_be_released_by_approval():
    isolated_plan = _plan(
        _product(
            20,
            latest_search_attribution_valid=0,
            has_supported_product_link=0,
        )
    )
    assert not isolated_plan.batches
    assert [(item.product_id, item.code) for item in isolated_plan.isolated] == [
        (20, "search_attribution_quarantine")
    ]

    planner_release_attempt = _plan(
        _product(
            20,
            quarantine_released=1,
            latest_search_attribution_valid=1,
            has_supported_product_link=0,
        )
    )
    manifest = build_approval_manifest(
        planner_release_attempt,
        _selections(planner_release_attempt),
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    assert {"quarantined_in_plan", "quarantined_product"} <= _issue_codes(manifest)


@pytest.mark.parametrize("product_id", [19, 20])
@pytest.mark.parametrize("stage", ["note", "profile"])
def test_t41_stopped_products_cannot_enter_note_or_profile(product_id, stage):
    if stage == "note":
        row = _product(
            product_id,
            quarantine_released=1,
            has_note_evidence=0,
            has_profile_evidence=0,
        )
    else:
        row = _product(
            product_id,
            quarantine_released=1,
            has_profile_evidence=0,
            note_author_identifiable=1,
            note_published_days_ago=1,
            note_likes=1_000,
            potential_follower_ceiling=2_000,
        )
    plan = _plan(row)
    assert [batch.stage for batch in plan.batches] == [stage]

    manifest = build_approval_manifest(
        plan,
        _selections(plan),
        decision="approve",
        reviewed_at=NOW,
    )

    assert manifest.plan_approval_status == "rejected"
    expected = {"low_follower_stop_in_plan", "low_follower_stop"}
    if product_id == 20:
        expected |= {"quarantined_in_plan", "quarantined_product"}
    assert expected <= _issue_codes(manifest)


def test_unmet_identity_stays_at_identity_and_cannot_be_selected_as_downstream():
    plan = _plan(
        _product(
            18,
            has_supported_product_link=0,
            has_metrics_strip=0,
            has_note_evidence=0,
            has_profile_evidence=0,
        )
    )
    item = plan.batches[0].items[0]

    assert item.stage == "identity"
    assert item.required_before == ()
    assert item.blocks == ("metrics", "note", "profile")
    assert "capture_supported_product_link" in item.actions

    manifest = build_approval_manifest(
        plan,
        [{"batch_id": "metrics-01", "product_ids": [18]}],
        decision="approve",
        reviewed_at=NOW,
    )
    assert manifest.plan_approval_status == "rejected"
    assert "unknown_batch" in _issue_codes(manifest)

    tampered = plan.as_dict()
    tampered["batches"][0]["stage"] = "metrics"
    tampered["batches"][0]["items"][0]["stage"] = "metrics"
    manifest = build_approval_manifest(
        tampered,
        [{"batch_id": "identity-01", "product_ids": [18]}],
        decision="approve",
        reviewed_at=NOW,
    )
    assert manifest.plan_approval_status == "rejected"
    assert {
        "dependency_contract_mismatch",
        "stage_blocks_mismatch",
        "invalid_stage_action",
    } <= _issue_codes(manifest)
