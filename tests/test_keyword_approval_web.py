from __future__ import annotations

import inspect
import json
import os
import time

import pytest

from xhs_scout.config import Settings
from xhs_scout.db import connect
from xhs_scout.keyword_approval import build_keyword_approval_manifest
from xhs_scout.web import create_app


def _route(settings):
    return next(
        route.endpoint
        for route in create_app(settings).routes
        if getattr(route, "path", None) == "/api/keyword-approval-manifest"
    )


def _suggestions():
    return {
        "candidates": [
            {
                "candidate_id": "core-summer",
                "keyword": "暑假预习资料",
                "normalized": "暑假预习资料",
                "suggested_layer": "core",
                "source_products": ["p1"],
                "source_keywords": ["暑假资料"],
                "support": {
                    "score": 3.25,
                    "source_types": ["successful_search", "trend_label"],
                },
                "risk_flags": [],
                "evidence": [
                    {
                        "source_type": "successful_search",
                        "source_id": "search-1",
                        "product_id": "p1",
                        "source_keyword": "暑假资料",
                    }
                ],
            },
            {
                "candidate_id": "explore-sync",
                "keyword": "同步练习资料",
                "normalized": "同步练习资料",
                "suggested_layer": "explore",
                "source_products": ["p2"],
                "source_keywords": ["同步练习"],
                "support": {
                    "score": 1.25,
                    "source_types": ["trend_label"],
                },
                "risk_flags": [],
                "evidence": [
                    {
                        "source_type": "trend_label",
                        "source_id": "trend-2",
                        "product_id": "p2",
                        "source_keyword": "同步练习",
                    }
                ],
            },
            {
                "candidate_id": "explore-math",
                "keyword": "三年级数学资料",
                "normalized": "三年级数学资料",
                "suggested_layer": "exploration",
                "source_products": ["p3"],
                "source_keywords": ["数学资料"],
                "support": {
                    "score": 1.0,
                    "source_types": ["product_title"],
                },
                "risk_flags": [],
                "evidence": [
                    {
                        "source_type": "product_title",
                        "source_id": "title-3",
                        "product_id": "p3",
                        "source_keyword": "数学资料",
                    }
                ],
            },
        ]
    }


def _reviewed_manifest(suggestions=None, *, policy=None):
    suggestions = suggestions or _suggestions()
    pending = build_keyword_approval_manifest(suggestions, policy=policy)
    by_id = {item["candidate_id"]: item for item in pending["entries"]}
    return build_keyword_approval_manifest(
        suggestions,
        policy=policy,
        decisions=[
            {
                "candidate_id": "core-summer",
                "status": "approved",
                "reason": "人工核验通过",
                "suggestion_set_hash": pending["suggestion_set_hash"],
                "evidence_hash": by_id["core-summer"]["evidence_hash"],
            },
            {
                "candidate_id": "explore-sync",
                "status": "rejected",
                "reason": "证据不足",
                "suggestion_set_hash": pending["suggestion_set_hash"],
                "evidence_hash": by_id["explore-sync"]["evidence_hash"],
            },
        ],
    )


def _write_manifest(settings, manifest):
    path = settings.root / "approvals" / "keyword-approval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _patch_suggestions(monkeypatch, suggestions):
    monkeypatch.setattr(
        "xhs_scout.web._keyword_suggestions_snapshot",
        lambda settings, *, max_output: suggestions,
    )


def test_current_manifest_is_read_only_and_reports_all_review_dimensions(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    suggestions = _suggestions()
    manifest = _reviewed_manifest(suggestions)
    _write_manifest(settings, manifest)
    _patch_suggestions(monkeypatch, suggestions)

    result = _route(settings)()

    assert result["manifest_status"] == "current"
    assert result["review_status"] == "current"
    assert result["is_current"] is True
    assert result["is_expired"] is False
    assert result["stored_stats"] == {
        "total": 3,
        "core": 1,
        "exploration": 2,
        "pending": 1,
        "approved": 1,
        "rejected": 1,
        "invalidated": 0,
    }
    assert result["current_stats"] == result["stored_stats"]
    assert result["validation"] == {
        "integrity_valid": True,
        "semantic_valid": True,
        "policy_within_bounds": True,
        "suggestion_set_hash_matches": True,
        "evidence_hashes_match": True,
        "layers_match": True,
        "statuses_valid": True,
        "counts_match": True,
        "unknown_candidate_ids": [],
    }
    assert {item["status"] for item in result["entries"]} == {
        "approved",
        "rejected",
        "pending",
    }
    assert {item["layer"] for item in result["entries"]} == {
        "core",
        "exploration",
    }
    assert result["scope"]["manifest_location"] == (
        "approvals/keyword-approval.json"
    )
    assert result["scope"]["manifest_access"] == "read_only"
    assert result["scope"]["request_path_override_allowed"] is False
    for field in (
        "writes_queue",
        "search_execution",
        "monitor_authorization",
        "soak_authorization",
    ):
        assert result["scope"][field] is False
        assert result["authorization"][field] is False


def test_real_temporary_suggestion_snapshot_keeps_database_and_manifest_unchanged(
    tmp_path,
):
    settings = Settings.load(tmp_path)
    path = _write_manifest(
        settings,
        build_keyword_approval_manifest({"candidates": []}),
    )
    with connect(settings.db_path):
        pass
    database_before = settings.db_path.read_bytes()
    manifest_before = path.read_bytes()

    result = _route(settings)()

    assert result["manifest_status"] == "current"
    assert result["stored_stats"]["total"] == 0
    assert settings.db_path.read_bytes() == database_before
    assert path.read_bytes() == manifest_before


@pytest.mark.parametrize(
    ("payload", "expected_warning"),
    [
        ("{bad json", "JSONDecodeError"),
        (json.dumps([]), "TypeError"),
    ],
)
def test_missing_or_bad_json_fails_closed(
    tmp_path,
    payload,
    expected_warning,
):
    settings = Settings.load(tmp_path)
    if payload:
        path = settings.root / "approvals" / "keyword-approval.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    result = _route(settings)()

    assert result["manifest_status"] == "invalid"
    assert result["is_current"] is False
    assert result["entries"] == []
    assert expected_warning in result["warnings"][0]
    assert not any(result["authorization"].get(key) for key in (
        "writes_queue",
        "search_execution",
        "monitor_authorization",
        "soak_authorization",
    ))


def test_missing_manifest_fails_closed_without_reading_suggestions(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("suggestions must not be read without a manifest")

    monkeypatch.setattr(
        "xhs_scout.web._keyword_suggestions_snapshot",
        forbidden,
    )
    result = _route(settings)()

    assert result["manifest_status"] == "missing"
    assert result["manifest_present"] is False
    assert result["warnings"] == ["keyword_approval_manifest_missing"]


@pytest.mark.parametrize("drift_kind", ["hash", "evidence", "layer", "unknown"])
def test_current_suggestion_drift_and_unknown_candidates_fail_closed(
    tmp_path,
    monkeypatch,
    drift_kind,
):
    settings = Settings.load(tmp_path)
    stored_suggestions = _suggestions()
    _write_manifest(settings, _reviewed_manifest(stored_suggestions))
    current = json.loads(json.dumps(stored_suggestions, ensure_ascii=False))
    if drift_kind == "hash":
        current["candidates"] = current["candidates"][:2]
    elif drift_kind == "evidence":
        current["candidates"][0]["evidence"][0]["source_id"] = "changed"
    elif drift_kind == "layer":
        current["candidates"][0]["suggested_layer"] = "explore"
    else:
        current["candidates"] = current["candidates"][1:]
    _patch_suggestions(monkeypatch, current)

    result = _route(settings)()

    assert result["manifest_status"] == "stale"
    assert result["review_status"] == "fail_closed"
    assert result["is_current"] is False
    assert all(item["approval_valid"] is False for item in result["entries"])
    assert result["validation"]["suggestion_set_hash_matches"] is False
    if drift_kind == "evidence":
        assert result["validation"]["evidence_hashes_match"] is False
    if drift_kind == "layer":
        assert result["validation"]["layers_match"] is False
    if drift_kind in {"hash", "unknown"}:
        assert result["validation"]["unknown_candidate_ids"]


def test_tampered_counts_status_and_evidence_hash_fail_closed(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    suggestions = _suggestions()
    _patch_suggestions(monkeypatch, suggestions)

    for mutate in (
        lambda value: value["stats"].update(total=99),
        lambda value: value["entries"][0].update(status="executed"),
        lambda value: value["entries"][0].update(evidence_hash="0" * 64),
    ):
        manifest = _reviewed_manifest(suggestions)
        mutate(manifest)
        _write_manifest(settings, manifest)
        result = _route(settings)()
        assert result["manifest_status"] in {"invalid", "out_of_bounds"}
        assert result["is_current"] is False
        assert result["entries"] == []


def test_policy_over_default_safety_bounds_and_expired_file_fail_closed(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    suggestions = _suggestions()
    _patch_suggestions(monkeypatch, suggestions)
    overbound = build_keyword_approval_manifest(
        suggestions,
        policy={"max_approved": 6},
    )
    _write_manifest(settings, overbound)

    result = _route(settings)()

    assert result["manifest_status"] == "out_of_bounds"
    assert result["validation"]["integrity_valid"] is True
    assert result["validation"]["policy_within_bounds"] is False

    path = _write_manifest(settings, _reviewed_manifest(suggestions))
    old = time.time() - (25 * 60 * 60)
    os.utime(path, (old, old))
    result = _route(settings)()

    assert result["manifest_status"] == "expired"
    assert result["is_expired"] is True
    assert result["is_current"] is False
    assert result["warnings"] == ["keyword_approval_manifest_expired"]
    assert all(item["approval_valid"] is False for item in result["entries"])


def test_route_is_get_only_has_no_path_override_and_preserves_other_routes(
    tmp_path,
):
    settings = Settings.load(tmp_path)
    routes = {
        route.path: route
        for route in create_app(settings).routes
        if hasattr(route, "methods")
    }

    assert routes["/api/keyword-approval-manifest"].methods == {"GET"}
    assert list(
        inspect.signature(
            routes["/api/keyword-approval-manifest"].endpoint
        ).parameters
    ) == []
    for preserved in (
        "/api/keyword-suggestions",
        "/api/remediation-plan",
        "/api/approval-manifest",
        "/api/soak-readiness",
    ):
        assert routes[preserved].methods == {"GET"}
    assert not any(
        "keyword-approval" in path and route.methods != {"GET"}
        for path, route in routes.items()
    )
