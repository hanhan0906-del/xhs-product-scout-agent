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


def _insert_product_with_trend(conn, *, fingerprint: str, trend_label: str) -> int:
    now = utcnow()
    conn.execute(
        """
        INSERT INTO products(
            fingerprint, title, shop_name, first_seen_at, last_seen_at
        ) VALUES (?, '三年级电子学习资料', '学习资料店', ?, ?)
        """,
        (fingerprint, now, now),
    )
    product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO observations(
            product_id, observed_at, source, raw_signals_json
        ) VALUES (?, ?, 'latest-evidence-test', ?)
        """,
        (
            product_id,
            now,
            json.dumps({"trend_labels": [trend_label]}, ensure_ascii=False),
        ),
    )
    return product_id


def _insert_search_evidence(
    conn,
    *,
    product_id: int,
    keyword: str,
    recorded_at: str,
    valid: int,
) -> None:
    conn.execute(
        """
        INSERT INTO search_result_evidence(
            product_id, source_keyword, recorded_at, valid, invalid_reason
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            product_id,
            keyword,
            recorded_at,
            valid,
            None if valid else "keyword_mismatch",
        ),
    )


def test_keyword_review_uses_only_each_products_latest_search_evidence(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        invalidated_product_id = _insert_product_with_trend(
            conn,
            fingerprint="invalidated-search-chain",
            trend_label="暑假预习资料",
        )
        _insert_search_evidence(
            conn,
            product_id=invalidated_product_id,
            keyword="暑假预习资料",
            recorded_at="2026-07-29T11:00:00+08:00",
            valid=1,
        )
        _insert_search_evidence(
            conn,
            product_id=invalidated_product_id,
            keyword="错误关键词",
            recorded_at="2026-07-29T12:00:00+08:00",
            valid=0,
        )

        current_product_id = _insert_product_with_trend(
            conn,
            fingerprint="current-valid-search-chain",
            trend_label="同步练习资料",
        )
        _insert_search_evidence(
            conn,
            product_id=current_product_id,
            keyword="旧同步资料",
            recorded_at="2026-07-29T10:00:00+08:00",
            valid=1,
        )
        _insert_search_evidence(
            conn,
            product_id=current_product_id,
            keyword="同步练习资料",
            recorded_at="2026-07-29T12:00:00+08:00",
            valid=1,
        )

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
    result = _route(settings)(limit=10)

    assert result["scope"]["database_access"] == "read_only"
    assert result["scope"]["production_queue_write"] is False
    assert result["source_stats"]["valid_search_sources_read"] == 1
    assert len(captured["successful_searches"]) == 1
    assert captured["successful_searches"][0]["product_id"] == str(
        current_product_id
    )
    assert captured["successful_searches"][0]["keyword"] == "同步练习资料"
    trends_by_product = {
        item["product_id"]: item for item in captured["trend_labels"]
    }
    assert trends_by_product[str(invalidated_product_id)]["source_keyword"] is None
    assert (
        trends_by_product[str(current_product_id)]["source_keyword"]
        == "同步练习资料"
    )


def test_latest_invalid_search_cannot_promote_old_keyword_to_core(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        product_id = _insert_product_with_trend(
            conn,
            fingerprint="latest-invalid-layer",
            trend_label="暑假预习资料",
        )
        _insert_search_evidence(
            conn,
            product_id=product_id,
            keyword="暑假预习资料",
            recorded_at="2026-07-29T11:00:00+08:00",
            valid=1,
        )
        _insert_search_evidence(
            conn,
            product_id=product_id,
            keyword="错误关键词",
            recorded_at="2026-07-29T12:00:00+08:00",
            valid=0,
        )

    result = _route(settings)(limit=10)

    suggestion = next(
        item
        for item in result["candidates"]
        if item["normalized"] == "暑假预习资料"
    )
    assert result["source_stats"]["valid_search_sources_read"] == 0
    assert suggestion["support"]["source_types"] == ["trend_label"]
    assert suggestion["suggested_layer"] == "explore"
