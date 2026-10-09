from __future__ import annotations

import json

from xhs_scout.config import Settings
from xhs_scout.db import connect, utcnow
from xhs_scout.web import create_app


def _route(settings):
    return next(
        route.endpoint
        for route in create_app(settings).routes
        if getattr(route, "path", None) == "/api/keyword-suggestions"
    )


def _seed_review_sources(settings):
    with connect(settings.db_path) as conn:
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, shop_name, first_seen_at, last_seen_at
            ) VALUES ('review-product', '三年级暑假预习资料电子版', '学习资料店', ?, ?)
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, raw_signals_json
            ) VALUES (?, ?, 'test', ?)
            """,
            (
                product_id,
                now,
                json.dumps({"trend_labels": ["暑假预习资料"]}, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, raw_signals_json
            ) VALUES (?, ?, 'test-bad-json', '{bad json')
            """,
            (product_id, now),
        )
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                product_id, source_keyword, recorded_at, valid
            ) VALUES (?, '暑假预习资料', ?, 1)
            """,
            (product_id, now),
        )
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                product_id, source_keyword, recorded_at, valid, invalid_reason
            ) VALUES (?, '加微信领取资料', ?, 0, 'invalid fixture')
            """,
            (product_id, now),
        )
    return product_id


def test_keyword_suggestions_are_pending_review_and_never_write_queue(tmp_path):
    settings = Settings.load(tmp_path)
    _seed_review_sources(settings)
    with connect(settings.db_path) as conn:
        tasks_before = conn.execute("SELECT COUNT(*) FROM search_tasks").fetchone()[0]

    result = _route(settings)(limit=10)

    assert result["scope"] == {
        "mode": "database_backed_keyword_review",
        "database_access": "read_only",
        "production_queue_write": False,
        "keyword_config_write": False,
        "auto_approval": False,
        "search_trigger": False,
        "human_review_required": True,
    }
    candidate = next(
        item for item in result["candidates"] if item["normalized"] == "暑假预习资料"
    )
    assert candidate["review_status"] == "pending_review"
    assert candidate["suggested_layer"] == "explore"
    assert candidate["support"]["source_types"] == ["trend_label"]
    assert candidate["support"]["score"] == 1.25
    assert candidate["source_products"]
    assert candidate["evidence"]
    assert result["source_stats"]["valid_search_sources_read"] == 0
    assert result["source_stats"]["trend_labels_read"] == 1
    assert result["source_stats"]["malformed_trend_fields"] == 1
    assert result["warnings"] == ["malformed_trend_fields:1"]
    assert all(item["keyword"] != "加微信领取资料" for item in result["filtered"])
    with connect(settings.db_path) as conn:
        tasks_after = conn.execute("SELECT COUNT(*) FROM search_tasks").fetchone()[0]
    assert tasks_after == tasks_before == 0


def test_keyword_suggestions_pass_plain_mappings_to_t25(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    _seed_review_sources(settings)
    captured = {}

    def fake_discovery(**kwargs):
        captured.update(kwargs)
        return {
            "version": 1,
            "scope": {},
            "policy": {"max_output": kwargs["policy"]["max_output"]},
            "stats": {},
            "candidates": [],
            "filtered": [],
        }

    monkeypatch.setattr("xhs_scout.web.discover_keyword_candidates", fake_discovery)
    result = _route(settings)(limit=999)

    assert result["policy"]["max_output"] == 50
    assert captured["products"] and type(captured["products"][0]) is dict
    assert captured["successful_searches"] == []
    assert captured["trend_labels"] and type(captured["trend_labels"][0]) is dict
    assert captured["trend_labels"][0]["source_keyword"] is None
    assert result["scope"]["production_queue_write"] is False


def test_keyword_suggestions_filter_existing_portfolio_without_modifying_it(tmp_path):
    settings = Settings.load(tmp_path)
    _seed_review_sources(settings)
    config_path = settings.root / "config" / "keyword_portfolio.json"
    config = {
        "version": 1,
        "categories": [
            {
                "id": "summer",
                "label": "暑假",
                "layer": "core",
                "priority": 100,
                "seed_terms": ["暑假预习资料"],
                "modifiers": [],
            }
        ],
    }
    before = json.dumps(config, ensure_ascii=False)
    config_path.write_text(before, encoding="utf-8")

    result = _route(settings)()

    assert all(
        item["normalized"] != "暑假预习资料" for item in result["candidates"]
    )
    assert result["stats"]["existing_portfolio_occurrences"] == 1
    assert config_path.read_text(encoding="utf-8") == before


def test_latest_valid_search_restores_current_attribution_after_invalid_history(
    tmp_path,
):
    settings = Settings.load(tmp_path)
    product_id = _seed_review_sources(settings)
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                product_id, source_keyword, recorded_at, valid
            ) VALUES (?, '暑假预习资料', ?, 1)
            """,
            (product_id, utcnow()),
        )

    result = _route(settings)(limit=10)

    candidate = next(
        item for item in result["candidates"] if item["normalized"] == "暑假预习资料"
    )
    assert result["source_stats"]["valid_search_sources_read"] == 1
    assert candidate["support"]["source_types"] == [
        "successful_search",
        "trend_label",
    ]
    assert candidate["support"]["score"] == 3.25
    assert candidate["suggested_layer"] == "core"


def test_keyword_suggestions_degrade_safely_when_database_is_missing(tmp_path):
    settings = Settings.load(tmp_path)
    settings.db_path.unlink(missing_ok=True)

    result = _route(settings)()

    assert result["candidates"] == []
    assert result["filtered"] == []
    assert result["scope"]["production_queue_write"] is False
    assert result["warnings"] == ["readonly_database_unavailable:OperationalError"]
