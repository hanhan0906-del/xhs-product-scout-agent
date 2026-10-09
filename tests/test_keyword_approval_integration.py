from __future__ import annotations

import builtins
import sqlite3

import pytest

from xhs_scout.keyword_approval import (
    build_keyword_approval_manifest,
    validate_keyword_approval_manifest,
)
from xhs_scout.keyword_discovery import discover_keyword_candidates


def _derived_suggestions():
    return discover_keyword_candidates(
        successful_searches=[
            {
                "id": "same-search",
                "keyword": "职场 新人-周报模板",
                "product_id": "product-1",
            },
            {
                "id": "same-search",
                "keyword": "职场新人周报模板",
                "product_id": "product-1",
            },
            {
                "id": "second-search",
                "keyword": "职场新人周报模板",
                "product_id": "product-2",
            },
            {
                "id": "exploration-search",
                "keyword": "新人复盘清单",
                "product_id": "product-3",
            },
        ]
    )


def _bound_decision(manifest, candidate_id, *, status="approved", reason="人工核验通过"):
    entry = next(
        item
        for item in manifest["entries"]
        if item["candidate_id"] == candidate_id
    )
    return {
        "candidate_id": candidate_id,
        "status": status,
        "reason": reason,
        "suggestion_set_hash": manifest["suggestion_set_hash"],
        "evidence_hash": entry["evidence_hash"],
    }


def _assert_no_execution_authority(manifest):
    assert manifest["scope"]["writes_queue"] is False
    assert manifest["scope"]["search_execution"] is False
    assert manifest["scope"]["monitor_authorization"] is False
    assert manifest["scope"]["soak_authorization"] is False


def test_real_discovery_output_preserves_layers_and_dedupes_same_source_variants():
    suggestions = _derived_suggestions()
    core = next(
        item
        for item in suggestions["candidates"]
        if item["normalized"] == "职场新人周报模板"
    )

    assert core["suggested_layer"] == "core"
    assert core["support"]["evidence_count"] == 2
    assert core["support"]["score"] == 4.0
    assert suggestions["scope"]["production_queue_write"] is False
    assert suggestions["scope"]["search_trigger"] is False

    manifest = build_keyword_approval_manifest(suggestions)

    assert manifest["stats"]["core"] == 1
    assert manifest["stats"]["exploration"] == 1
    assert {
        item["normalized"]: item["layer"] for item in manifest["entries"]
    } == {
        "职场新人周报模板": "core",
        "新人复盘清单": "exploration",
    }
    assert all(item["status"] == "pending" for item in manifest["entries"])
    _assert_no_execution_authority(manifest)
    assert validate_keyword_approval_manifest(manifest) == (True, [])


def test_ocr_gibberish_is_filtered_and_unsafe_characters_cannot_enter_approval():
    suggestions = discover_keyword_candidates(
        successful_searches=[
            "资枓丨模扳丨课桯",
            "lI1|O0资料",
            "正常学习资料/测试",
        ]
    )

    assert [item["reason"] for item in suggestions["filtered"]] == [
        "ocr_gibberish",
        "ocr_gibberish",
    ]
    assert [item["keyword"] for item in suggestions["candidates"]] == [
        "正常学习资料/测试"
    ]
    with pytest.raises(ValueError, match="unsafe characters"):
        build_keyword_approval_manifest(suggestions)


def test_source_product_and_evidence_change_invalidates_real_derived_approval():
    original = discover_keyword_candidates(
        successful_searches=[
            {
                "id": "stable-search",
                "keyword": "职场新人周报模板",
                "product_id": "product-1",
            }
        ]
    )
    pending = build_keyword_approval_manifest(original)
    candidate_id = pending["entries"][0]["candidate_id"]
    reviewed = build_keyword_approval_manifest(
        original,
        decisions=[_bound_decision(pending, candidate_id)],
    )
    assert reviewed["entries"][0]["approval_valid"] is True

    changed_source = discover_keyword_candidates(
        successful_searches=[
            {
                "id": "stable-search",
                "keyword": "职场新人周报模板",
                "product_id": "product-9",
            }
        ]
    )
    invalidated = build_keyword_approval_manifest(
        changed_source,
        previous_manifest=reviewed,
    )

    assert invalidated["suggestion_set_hash"] != reviewed["suggestion_set_hash"]
    assert (
        invalidated["entries"][0]["evidence_hash"]
        != reviewed["entries"][0]["evidence_hash"]
    )
    assert invalidated["stats"]["invalidated"] == 1
    assert invalidated["stats"]["approved"] == 0
    assert invalidated["entries"][0]["status"] == "pending"
    assert invalidated["entries"][0]["reason"] == "previous_evidence_changed"
    assert invalidated["entries"][0]["approval_valid"] is False
    _assert_no_execution_authority(invalidated)


def test_unknown_duplicate_conflict_and_over_budget_decisions_fail_closed():
    suggestions = _derived_suggestions()
    pending = build_keyword_approval_manifest(
        suggestions,
        policy={"max_approved": 1},
    )
    candidate_ids = [item["candidate_id"] for item in pending["entries"]]

    with pytest.raises(ValueError, match="outside suggestions"):
        build_keyword_approval_manifest(
            suggestions,
            decisions=[
                {
                    "candidate_id": "unknown-derived-keyword",
                    "status": "approved",
                    "reason": "不应接受",
                    "suggestion_set_hash": pending["suggestion_set_hash"],
                    "evidence_hash": "0" * 64,
                }
            ],
        )

    first_source = discover_keyword_candidates(
        successful_searches=[
            {
                "id": "source-a",
                "keyword": "职场新人周报模板",
                "product_id": "product-a",
            }
        ]
    )
    second_source = discover_keyword_candidates(
        successful_searches=[
            {
                "id": "source-b",
                "keyword": "职场新人周报模板",
                "product_id": "product-b",
            }
        ]
    )
    with pytest.raises(ValueError, match="conflicting duplicate"):
        build_keyword_approval_manifest(
            first_source["candidates"] + second_source["candidates"]
        )

    with pytest.raises(ValueError, match="exceed max_approved"):
        build_keyword_approval_manifest(
            suggestions,
            policy={"max_approved": 1},
            decisions=[
                _bound_decision(pending, candidate_ids[0]),
                _bound_decision(pending, candidate_ids[1]),
            ],
        )


def test_pipeline_uses_only_plain_objects_and_never_writes_files_or_sqlite(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    real_open = builtins.open

    def reject_writes(file, mode="r", *args, **kwargs):
        if any(marker in mode for marker in ("w", "a", "x", "+")):
            pytest.fail(f"unexpected file write: {file!s} mode={mode}")
        return real_open(file, mode, *args, **kwargs)

    def reject_database(*args, **kwargs):
        pytest.fail("keyword discovery/approval must not open SQLite")

    monkeypatch.setattr(builtins, "open", reject_writes)
    monkeypatch.setattr(sqlite3, "connect", reject_database)

    suggestions = _derived_suggestions()
    manifest = build_keyword_approval_manifest(suggestions)

    assert suggestions["scope"]["database_access"] is False
    assert suggestions["scope"]["production_queue_write"] is False
    assert suggestions["scope"]["search_trigger"] is False
    _assert_no_execution_authority(manifest)
    assert list(tmp_path.iterdir()) == []
