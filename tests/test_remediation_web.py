from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from xhs_scout.config import Settings
from xhs_scout.db import connect, utcnow
from xhs_scout.web import create_app


def _route(settings):
    return next(
        route.endpoint
        for route in create_app(settings).routes
        if getattr(route, "path", None) == "/api/remediation-plan"
    )


def _insert_product(
    conn,
    *,
    product_id: int,
    status: str = "candidate",
    score: float = 50,
    share_url: str | None = None,
    raw_signals_json: str = "{}",
):
    now = utcnow()
    conn.execute(
        """
        INSERT INTO products(
            id, fingerprint, title, share_url, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            f"remediation-product-{product_id}",
            f"Product {product_id}",
            share_url,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO observations(
            product_id, observed_at, source, raw_signals_json
        ) VALUES (?, ?, 'remediation-test', ?)
        """,
        (product_id, now, raw_signals_json),
    )
    observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO candidate_assessments(
            product_id, assessed_at, evidence_grade, score, reasons_json, status
        ) VALUES (?, ?, 'B', ?, '[]', ?)
        """,
        (product_id, now, score, status),
    )
    return observation_id


def _insert_search_chain(
    conn,
    *,
    product_id: int,
    observation_id: int,
    task_keyword: str,
    evidence_keyword: str | None = None,
    valid: int = 1,
):
    now = utcnow()
    conn.execute(
        """
        INSERT INTO search_tasks(
            keyword, source, status, created_at, updated_at
        ) VALUES (?, 'test', 'completed', ?, ?)
        """,
        (task_keyword, now, now),
    )
    task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO search_result_evidence(
            task_id, product_id, observation_id, source_keyword,
            result_rank, recorded_at, valid
        ) VALUES (?, ?, ?, ?, 1, ?, ?)
        """,
        (
            task_id,
            product_id,
            observation_id,
            evidence_keyword or task_keyword,
            now,
            valid,
        ),
    )
    return task_id


def _table_counts(path):
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return {
            row[0]: conn.execute(f'SELECT COUNT(*) FROM "{row[0]}"').fetchone()[0]
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


def test_remediation_plan_reads_current_evidence_and_never_writes(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        identity_observation = _insert_product(
            conn,
            product_id=1,
            score=80,
            raw_signals_json="{bad json",
        )
        metrics_observation = _insert_product(
            conn,
            product_id=2,
            score=70,
            share_url="https://xhslink.com/a/remediation-2",
        )
        _insert_search_chain(
            conn,
            product_id=2,
            observation_id=metrics_observation,
            task_keyword="二年级资料",
        )
        note_observation = _insert_product(
            conn,
            product_id=3,
            score=60,
            share_url="https://xhslink.com/a/remediation-3",
            raw_signals_json=json.dumps(
                {"metrics_strip": {"frames": [{"frame": 1}]}}
            ),
        )
        _insert_search_chain(
            conn,
            product_id=3,
            observation_id=note_observation,
            task_keyword="三年级资料",
        )
        cooling_observation = _insert_product(
            conn,
            product_id=4,
            score=90,
            share_url="https://xhslink.com/a/remediation-4",
        )
        cooling_task = _insert_search_chain(
            conn,
            product_id=4,
            observation_id=cooling_observation,
            task_keyword="四年级资料",
        )
        now = utcnow()
        conn.execute(
            """
            INSERT INTO run_events(
                run_id, event_at, phase, event, task_id, product_id
            ) VALUES ('remediation-run', ?, 'remediation', 'finished', ?, 4)
            """,
            (now, cooling_task),
        )
        assert identity_observation

    before = _table_counts(settings.db_path)
    result = _route(settings)()
    after = _table_counts(settings.db_path)

    assert before == after
    assert result["scope"] == {
        "mode": "database_backed_remediation_plan",
        "database_access": "read_only",
        "production_queue_write": False,
        "collection_trigger": False,
        "approval_write": False,
        "execution_endpoint": False,
        "human_review_required": True,
    }
    assert result["earliest_executable_stage"] == "identity"
    assert result["next_batch"]["batch_id"] == "identity-01"
    assert result["next_batch"]["items"][0]["product_id"] == 1
    assert [batch["stage"] for batch in result["batches"]] == [
        "identity",
        "metrics",
        "note",
    ]
    isolated = {item["product_id"]: item for item in result["isolated"]}
    assert isolated[4]["code"] == "product_cooldown"
    assert isolated[4]["retry_at"]
    assert result["budget"] == {
        "per_batch_limit": 2,
        "hourly_visit_limit": 6,
        "product_cooldown_hours": 24,
        "planned_product_visits": 3,
        "next_batch_items": 1,
    }
    assert result["source_stats"]["products_read"] == 4
    assert result["source_stats"]["malformed_metrics_json"] == 1
    assert result["warnings"] == ["malformed_metrics_json:1"]


def test_latest_invalid_search_chain_is_quarantined_despite_valid_history(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        observation_id = _insert_product(
            conn,
            product_id=5,
            share_url="https://xhslink.com/a/remediation-5",
        )
        _insert_search_chain(
            conn,
            product_id=5,
            observation_id=observation_id,
            task_keyword="有效关键词",
        )
        _insert_search_chain(
            conn,
            product_id=5,
            observation_id=observation_id,
            task_keyword="任务关键词",
            evidence_keyword="污染关键词",
        )

    result = _route(settings)()

    assert result["batches"] == []
    assert result["isolated"][0]["product_id"] == 5
    assert result["isolated"][0]["code"] == "search_attribution_quarantine"
    assert result["blocking_dependencies"][0]["blocked_by"] == [
        "new_valid_search_discovery",
        "manual_release",
    ]


def test_remediation_plan_passes_plain_mappings_to_planner(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        _insert_product(conn, product_id=6)

    captured = {}
    from xhs_scout import remediation

    def capturing_plan(products, **kwargs):
        captured["products"] = products
        captured["now"] = kwargs["now"]
        return remediation.plan_remediation(products, **kwargs)

    monkeypatch.setattr("xhs_scout.web.plan_remediation", capturing_plan)
    result = _route(settings)()

    assert captured["products"] and type(captured["products"][0]) is dict
    assert captured["products"][0]["product_id"] == 6
    assert isinstance(captured["now"], datetime)
    assert result["scope"]["production_queue_write"] is False
    assert result["scope"]["collection_trigger"] is False


def test_remediation_plan_degrades_safely_when_database_is_missing(tmp_path):
    settings = Settings.load(tmp_path)
    settings.db_path.unlink(missing_ok=True)

    result = _route(settings)()

    assert result["batches"] == []
    assert result["isolated"] == []
    assert result["earliest_executable_stage"] is None
    assert result["next_batch"] is None
    assert result["scope"]["production_queue_write"] is False
    assert result["scope"]["collection_trigger"] is False
    assert result["warnings"] == ["readonly_database_unavailable:OperationalError"]


def test_remediation_surface_exposes_get_plan_only(tmp_path):
    settings = Settings.load(tmp_path)
    routes = [
        route
        for route in create_app(settings).routes
        if "remediation" in getattr(route, "path", "")
    ]

    assert [(route.path, route.methods) for route in routes] == [
        ("/api/remediation-plan", {"GET"})
    ]
