from __future__ import annotations

import json

import pytest

from xhs_scout.keyword_approval import (
    build_keyword_approval_manifest,
    validate_keyword_approval_manifest,
)
from xhs_scout.keyword_discovery import discover_keyword_candidates


def _suggestions():
    return discover_keyword_candidates(
        successful_searches=[
            {"id": "search-1", "keyword": "职场新人周报模板", "product_id": "p1"},
            {"id": "search-2", "keyword": "职场新人周报模板", "product_id": "p2"},
            {"id": "search-3", "keyword": "新人复盘清单", "product_id": "p3"},
        ],
        trend_labels=[
            {
                "id": "trend-1",
                "keyword": "职场新人周报模板",
                "product_id": "p1",
                "source_keyword": "职场新人",
            }
        ],
    )


def _bound_decision(manifest, candidate_id, status, reason):
    entry = next(
        item for item in manifest["entries"]
        if item["candidate_id"] == candidate_id
    )
    return {
        "candidate_id": candidate_id,
        "status": status,
        "reason": reason,
        "suggestion_set_hash": manifest["suggestion_set_hash"],
        "evidence_hash": entry["evidence_hash"],
    }


def test_builds_deterministic_human_only_manifest_with_provenance():
    suggestions = _suggestions()

    first = build_keyword_approval_manifest(suggestions)
    second = build_keyword_approval_manifest(
        {"candidates": list(reversed(suggestions["candidates"]))}
    )

    assert first == second
    assert first["scope"] == {
        "mode": "offline_human_keyword_approval",
        "human_review_only": True,
        "writes_queue": False,
        "search_execution": False,
        "monitor_authorization": False,
        "soak_authorization": False,
    }
    assert {item["layer"] for item in first["entries"]} == {
        "core",
        "exploration",
    }
    assert all(item["status"] == "pending" for item in first["entries"])
    assert all(item["source_summary"]["source_products"] for item in first["entries"])
    assert all(len(item["evidence_hash"]) == 64 for item in first["entries"])
    json.dumps(first, ensure_ascii=False)
    assert validate_keyword_approval_manifest(first) == (True, [])


def test_applies_only_hash_bound_decisions_and_preserves_valid_previous_review():
    pending = build_keyword_approval_manifest(_suggestions())
    approved_id = pending["entries"][0]["candidate_id"]
    rejected_id = pending["entries"][1]["candidate_id"]
    reviewed = build_keyword_approval_manifest(
        _suggestions(),
        decisions=[
            _bound_decision(pending, approved_id, "approved", "证据充分，人工批准"),
            _bound_decision(pending, rejected_id, "rejected", "范围过宽"),
        ],
    )
    carried = build_keyword_approval_manifest(
        _suggestions(),
        previous_manifest=reviewed,
    )

    assert carried == reviewed
    assert carried["stats"] == {
        "total": 2,
        "core": 1,
        "exploration": 1,
        "pending": 0,
        "approved": 1,
        "rejected": 1,
        "invalidated": 0,
    }
    assert next(
        item for item in carried["entries"]
        if item["candidate_id"] == approved_id
    )["approval_valid"] is True
    assert validate_keyword_approval_manifest(carried) == (True, [])


def test_suggestion_set_or_evidence_change_invalidates_previous_decisions():
    pending = build_keyword_approval_manifest(_suggestions())
    candidate_id = pending["entries"][0]["candidate_id"]
    reviewed = build_keyword_approval_manifest(
        _suggestions(),
        decisions=[
            _bound_decision(pending, candidate_id, "approved", "人工核验通过")
        ],
    )

    changed_set = _suggestions()
    changed_set["candidates"] = changed_set["candidates"][:1]
    invalid_set = build_keyword_approval_manifest(
        changed_set,
        previous_manifest=reviewed,
    )
    assert invalid_set["stats"]["approved"] == 0
    assert invalid_set["stats"]["invalidated"] == 1
    assert invalid_set["entries"][0]["reason"] == "previous_suggestion_set_changed"

    changed_evidence = _suggestions()
    target = next(
        item for item in changed_evidence["candidates"]
        if item["candidate_id"] == candidate_id
    )
    target["evidence"][0]["source_id"] = "changed-source"
    invalid_evidence = build_keyword_approval_manifest(
        changed_evidence,
        previous_manifest=reviewed,
    )
    target_entry = next(
        item for item in invalid_evidence["entries"]
        if item["candidate_id"] == candidate_id
    )
    assert target_entry["status"] == "pending"
    assert target_entry["approval_valid"] is False
    assert target_entry["reason"] == "previous_evidence_changed"


def test_rejects_unknown_stale_duplicate_and_over_budget_decisions():
    pending = build_keyword_approval_manifest(
        _suggestions(),
        policy={"max_approved": 1},
    )
    first_id, second_id = [
        item["candidate_id"] for item in pending["entries"]
    ]

    with pytest.raises(ValueError, match="outside suggestions"):
        build_keyword_approval_manifest(
            _suggestions(),
            decisions=[
                {
                    "candidate_id": "missing",
                    "status": "approved",
                    "reason": "no",
                    "suggestion_set_hash": pending["suggestion_set_hash"],
                    "evidence_hash": "0" * 64,
                }
            ],
        )
    stale = _bound_decision(pending, first_id, "approved", "人工通过")
    stale["evidence_hash"] = "0" * 64
    with pytest.raises(ValueError, match="stale evidence_hash"):
        build_keyword_approval_manifest(_suggestions(), decisions=[stale])
    with pytest.raises(ValueError, match="duplicate decision"):
        decision = _bound_decision(pending, first_id, "approved", "人工通过")
        build_keyword_approval_manifest(
            _suggestions(),
            decisions=[decision, decision],
        )
    with pytest.raises(ValueError, match="exceed max_approved"):
        build_keyword_approval_manifest(
            _suggestions(),
            policy={"max_approved": 1},
            decisions=[
                _bound_decision(pending, first_id, "approved", "人工通过"),
                _bound_decision(pending, second_id, "approved", "人工通过"),
            ],
        )


def test_dedupes_identical_suggestions_but_rejects_conflicting_duplicates():
    candidate = _suggestions()["candidates"][0]
    deduped = build_keyword_approval_manifest([candidate, dict(candidate)])
    assert deduped["stats"]["total"] == 1

    conflict = dict(candidate)
    conflict["candidate_id"] = "different-id"
    with pytest.raises(ValueError, match="conflicting duplicate"):
        build_keyword_approval_manifest([candidate, conflict])


@pytest.mark.parametrize(
    ("candidate_update", "error"),
    [
        ({"keyword": "a"}, "too short"),
        ({"keyword": "这是一个明显超过十八个字符限制的超长关键词测试样本"}, "too long"),
        ({"keyword": "安全词/../../逃逸"}, "path traversal"),
        ({"keyword": "正常词", "api_key": "should-not-be-here"}, "sensitive field"),
        ({"keyword": "正常词", "source_path": r"C:\private\data"}, "unsafe path"),
        ({"keyword": "正常词<script>"}, "unsafe characters"),
    ],
)
def test_keyword_safety_sensitive_fields_and_paths_fail_closed(
    candidate_update,
    error,
):
    candidate = {
        "candidate_id": "safe-id",
        "keyword": "正常学习资料",
        "suggested_layer": "explore",
        "support": {"score": 1.0, "source_types": ["product_title"]},
        "source_products": ["p1"],
        "evidence": [
            {
                "source_type": "product_title",
                "source_id": "p1:title",
                "product_id": "p1",
                "source_keyword": "学习资料",
            }
        ],
    }
    candidate.update(candidate_update)

    with pytest.raises(ValueError, match=error):
        build_keyword_approval_manifest([candidate])


def test_tampered_authorization_or_hash_fails_manifest_validation():
    manifest = build_keyword_approval_manifest(_suggestions())
    manifest["scope"]["writes_queue"] = True
    valid, errors = validate_keyword_approval_manifest(manifest)
    assert valid is False
    assert "scope.writes_queue must be False" in errors

    manifest = build_keyword_approval_manifest(_suggestions())
    manifest["entries"][0]["evidence_hash"] = "0" * 64
    valid, errors = validate_keyword_approval_manifest(manifest)
    assert valid is False
    assert any("evidence_hash mismatch" in item for item in errors)
