import pytest
from fastapi import HTTPException

from xhs_scout.config import Settings
from xhs_scout.db import connect
from xhs_scout.web import create_app


def _route(settings, path):
    return next(
        route
        for route in create_app(settings).routes
        if getattr(route, "path", None) == path
    )


def _seed_monitor_details(settings):
    now = "2026-07-30T18:00:00+08:00"
    with connect(settings.db_path) as conn:
        for task_id, keyword in ((1, "虚拟资料"), (2, "成长指南")):
            conn.execute(
                """
                INSERT INTO search_tasks(
                    id, keyword, source, status, created_at, updated_at
                ) VALUES (?, ?, 'manual', 'pending', ?, ?)
                """,
                (task_id, keyword, now, now),
            )
        for product_id, title in ((1, "达标商品"), (2, "普通商品")):
            conn.execute(
                """
                INSERT INTO products(
                    id, fingerprint, title, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (product_id, f"product-{product_id}", title, now, now),
            )
        conn.execute(
            """
            INSERT INTO observations(
                id, product_id, observed_at, source, cumulative_sales_display,
                raw_signals_json
            ) VALUES (
                1, 1, ?, 'test', '1.9万+',
                '{"metrics_strip":{"frames":[{"signals":{"sales_30d_min":1000,"positive_reviews_30d_min":900,"favorites_30d_min":200}}]}}'
            )
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO product_sales_follows(product_id, followed_at, followed_by)
            VALUES (1, ?, 'workbench')
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO observations(
                id, product_id, observed_at, source, cumulative_sales_display,
                raw_signals_json
            ) VALUES (2, 2, ?, 'test', '10', '{}')
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO note_observations(
                id, product_id, captured_at, source, page_kind,
                author_name, follower_count
            ) VALUES (
                1, 1, ?, 'seller_profile_from_product',
                'account_profile', '测试账号', 1888
            )
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO note_observations(
                id, product_id, captured_at, source, page_kind,
                follower_count, raw_json
            ) VALUES (
                2, 2, ?, 'seller_profile_from_product',
                'shop_product_list', NULL,
                '{"follower_display_status":"not_displayed"}'
            )
            """,
            (now,),
        )


def test_monitor_drilldown_returns_complete_read_only_lists(tmp_path):
    settings = Settings.load(tmp_path)
    _seed_monitor_details(settings)
    route = _route(settings, "/api/monitor/details/{kind}")

    assert route.methods == {"GET"}
    expected_counts = {
        "tasks": 2,
        "products": 2,
        "observations": 2,
        "evidence": 2,
        "candidates": 1,
        "followed": 1,
    }
    for kind, expected in expected_counts.items():
        result = route.endpoint(kind)
        assert result["count"] == expected
        assert len(result["items"]) == expected
        assert result["scope"] == {
            "access": "read_only",
            "database_write": False,
            "search_trigger": False,
            "monitor_trigger": False,
        }

    candidate = route.endpoint("candidates")["items"][0]
    assert candidate["title"] == "达标商品"
    assert candidate["detail_url"] == "/products/1/analysis"
    assert any(
        field["label"] == "灰色指标" and "近30天购买" in field["value"]
        for field in candidate["fields"]
    )
    ordinary = next(
        item for item in route.endpoint("products")["items"]
        if item["title"] == "普通商品"
    )
    assert any(
        field["label"] == "粉丝数" and field["value"] == "页面未显示"
        for field in ordinary["fields"]
    )


def test_monitor_drilldown_rejects_unknown_kind(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    route = _route(settings, "/api/monitor/details/{kind}")

    with pytest.raises(HTTPException) as exc_info:
        route.endpoint("unknown")
    assert exc_info.value.status_code == 404
