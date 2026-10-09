from __future__ import annotations

import inspect
import json
import sqlite3
from pathlib import Path

import pytest

import xhs_scout.web as web_module
from xhs_scout.config import Settings
from xhs_scout.db import connect, utcnow
from xhs_scout.remediation import plan_remediation
from xhs_scout.remediation_approval import (
    build_approval_manifest,
    write_approval_manifest,
)
from xhs_scout.web import create_app


NOW = "2026-07-29T16:00:00+08:00"


def _route(settings):
    return next(
        route.endpoint
        for route in create_app(settings).routes
        if getattr(route, "path", None) == "/api/approval-manifest"
    )


def _seed_identity_product(settings, *, product_id=1, score=80):
    with connect(settings.db_path) as conn:
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(
                id, fingerprint, title, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                product_id,
                f"approval-web-{product_id}",
                f"Approval product {product_id}",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, raw_signals_json
            ) VALUES (?, ?, 'approval-web-test', '{}')
            """,
            (product_id, now),
        )
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score,
                reasons_json, status
            ) VALUES (?, ?, 'B', ?, '[]', 'candidate')
            """,
            (product_id, now, score),
        )


def _planner_from_database(settings, *, now=NOW):
    inputs = web_module._remediation_plan_inputs(settings)
    return plan_remediation(inputs["products"], now=now)


def _write_current_manifest(settings, *, decision="approve", policy=None):
    plan = _planner_from_database(settings)
    selections = [
        {
            "batch_id": batch.batch_id,
            "product_ids": [item.product_id for item in batch.items],
        }
        for batch in plan.batches
    ]
    manifest = build_approval_manifest(
        plan,
        selections,
        decision=decision,
        reviewer="t51-offline",
        reviewed_at=NOW,
        policy=policy,
    )
    return write_approval_manifest(
        settings.root / "approvals" / "remediation-approval.json",
        manifest,
    )


def _table_counts(path):
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        return {
            row[0]: conn.execute(
                f'SELECT COUNT(*) FROM "{row[0]}"'
            ).fetchone()[0]
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        }
    finally:
        conn.close()


def test_missing_manifest_returns_pending_missing_without_database_access(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    settings.db_path.unlink(missing_ok=True)

    def must_not_read_database(_settings):
        raise AssertionError("missing manifest must fail closed before DB access")

    monkeypatch.setattr(
        web_module, "_remediation_plan_inputs", must_not_read_database
    )
    result = _route(settings)()

    assert result["review_status"] == "pending"
    assert result["manifest_status"] == "missing"
    assert result["manifest_present"] is False
    assert result["is_current"] is False
    assert result["plan_approval_status"] == "pending_review"
    assert result["execution_status"] == "not_executed"
    assert result["authorizes_execution"] is False
    assert result["warnings"] == ["approval_manifest_missing"]


def test_current_manifest_is_strictly_validated_and_database_is_read_only(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    _seed_identity_product(settings)
    path = _write_current_manifest(settings)
    manifest_before = path.read_bytes()
    counts_before = _table_counts(settings.db_path)
    real_bounded_rows = web_module._bounded_rows
    real_sqlite_connect = sqlite3.connect
    captured = {}

    def inspect_connect(database, *args, **kwargs):
        captured["database_uri"] = str(database)
        captured["uri_enabled"] = kwargs.get("uri")
        return real_sqlite_connect(database, *args, **kwargs)

    def inspect_bounded_rows(conn, sql, limit):
        captured["query_only"] = conn.execute(
            "PRAGMA query_only"
        ).fetchone()[0]
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE forbidden_write(id INTEGER)")
        captured["write_blocked"] = True
        return real_bounded_rows(conn, sql, limit)

    monkeypatch.setattr(web_module.sqlite3, "connect", inspect_connect)
    monkeypatch.setattr(web_module, "_bounded_rows", inspect_bounded_rows)
    result = _route(settings)()

    assert result["review_status"] == "planned_approved"
    assert result["manifest_status"] == "current"
    assert result["is_current"] is True
    assert result["validation"] == {
        "integrity_valid": True,
        "semantic_valid": True,
        "planner_hash_matches": True,
    }
    assert result["approval"]["source_generated_at"] == NOW
    assert result["approval"]["selected_batches"][0]["stage"] == "identity"
    assert result["scope"]["database_access"] == "sqlite_mode_ro_query_only"
    assert result["scope"]["production_queue_write"] is False
    assert result["scope"]["approval_write"] is False
    assert result["scope"]["execution_endpoint"] is False
    assert captured["database_uri"].endswith(
        "/data/xhs_scout.sqlite3?mode=ro"
    )
    assert captured["uri_enabled"] is True
    assert captured["query_only"] == 1
    assert captured["write_blocked"] is True
    assert _table_counts(settings.db_path) == counts_before
    assert path.read_bytes() == manifest_before


def test_bad_json_fails_closed(tmp_path):
    settings = Settings.load(tmp_path)
    path = settings.root / "approvals" / "remediation-approval.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad json", encoding="utf-8")

    result = _route(settings)()

    assert result["manifest_status"] == "invalid"
    assert result["review_status"] == "pending"
    assert result["approval"] is None
    assert result["authorizes_execution"] is False
    assert result["warnings"] == [
        "approval_manifest_invalid:RemediationApprovalError"
    ]


def test_integrity_tampering_fails_closed(tmp_path):
    settings = Settings.load(tmp_path)
    _seed_identity_product(settings)
    path = _write_current_manifest(settings)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reviewer"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = _route(settings)()

    assert result["manifest_status"] == "invalid"
    assert result["validation"]["integrity_valid"] is False
    assert result["plan_approval_status"] == "pending_review"
    assert result["authorizes_execution"] is False


def test_rehashed_semantic_tampering_still_fails_closed(tmp_path):
    settings = Settings.load(tmp_path)
    _seed_identity_product(settings)
    path = _write_current_manifest(settings)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["manifest_id"] = "remediation-approval-forged"
    unsigned = dict(payload)
    unsigned.pop("manifest_hash")
    payload["manifest_hash"] = web_module.hashlib.sha256(
        json.dumps(
            unsigned,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = _route(settings)()

    assert result["manifest_status"] == "invalid"
    assert result["validation"] == {
        "integrity_valid": True,
        "semantic_valid": False,
        "planner_hash_matches": True,
    }
    assert result["review_status"] == "pending"
    assert result["authorizes_execution"] is False


def test_changed_database_makes_old_planner_hash_stale(tmp_path):
    settings = Settings.load(tmp_path)
    _seed_identity_product(settings, score=80)
    _write_current_manifest(settings)
    with connect(settings.db_path) as conn:
        conn.execute(
            "UPDATE candidate_assessments SET score=81 WHERE product_id=1"
        )

    result = _route(settings)()

    assert result["manifest_status"] == "stale"
    assert result["review_status"] == "pending"
    assert result["stored_plan_approval_status"] == "planned_approved"
    assert result["plan_approval_status"] == "pending_review"
    assert result["validation"]["planner_hash_matches"] is False
    assert result["authorizes_execution"] is False


def test_incomplete_database_snapshot_fails_closed(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    _seed_identity_product(settings)
    _write_current_manifest(settings)
    original = web_module._remediation_plan_inputs

    def incomplete_inputs(current_settings):
        result = original(current_settings)
        result["stats"]["source_rows_truncated"] = 1
        result["warnings"].append("remediation_products_truncated:2000")
        return result

    monkeypatch.setattr(
        web_module, "_remediation_plan_inputs", incomplete_inputs
    )
    result = _route(settings)()

    assert result["manifest_status"] == "unavailable"
    assert result["review_status"] == "pending"
    assert result["validation"]["integrity_valid"] is True
    assert result["validation"]["planner_hash_matches"] is None
    assert result["source_stats"]["source_rows_truncated"] == 1
    assert result["warnings"] == [
        "remediation_snapshot_incomplete:source_rows_truncated"
    ]
    assert result["authorizes_execution"] is False


@pytest.mark.parametrize(
    "policy",
    [
        {"per_batch_limit": 3},
        {"hourly_visit_limit": 7},
        {"quarantine_product_ids": []},
        {"low_follower_stop_product_ids": []},
    ],
)
def test_budget_and_isolation_policy_cannot_be_weakened(tmp_path, policy):
    settings = Settings.load(tmp_path)
    _seed_identity_product(settings)
    path = _write_current_manifest(settings)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["policy"].update(policy)
    unsigned = dict(payload)
    unsigned.pop("manifest_hash")
    payload["manifest_hash"] = web_module.hashlib.sha256(
        json.dumps(
            unsigned,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = _route(settings)()

    assert result["manifest_status"] == "invalid"
    assert result["review_status"] == "pending"
    assert result["authorizes_execution"] is False


def test_manifest_path_is_fixed_and_path_injection_is_rejected(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-approval.json"
    outside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        web_module,
        "_REMEDIATION_APPROVAL_RELATIVE",
        Path("..") / outside.name,
    )

    result = _route(settings)()

    assert result["manifest_status"] == "invalid"
    assert result["manifest_present"] is False
    assert result["warnings"] == ["approval_path_invalid:ValueError"]
    assert result["authorizes_execution"] is False


def test_remediation_approval_is_get_only_and_preserves_existing_routes(
    tmp_path,
):
    settings = Settings.load(tmp_path)
    paths = {
        "/api/keyword-suggestions",
        "/api/remediation-plan",
        "/api/approval-manifest",
        "/api/soak-readiness",
    }
    routes = [
        route
        for route in create_app(settings).routes
        if getattr(route, "path", "") in paths
    ]

    assert [(route.path, route.methods) for route in routes] == [
        ("/api/keyword-suggestions", {"GET"}),
        ("/api/remediation-plan", {"GET"}),
        ("/api/approval-manifest", {"GET"}),
        ("/api/soak-readiness", {"GET"}),
    ]
    endpoint = next(
        route.endpoint
        for route in routes
        if route.path == "/api/approval-manifest"
    )
    assert list(inspect.signature(endpoint).parameters) == []
