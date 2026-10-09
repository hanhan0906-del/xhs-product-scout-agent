from xhs_scout.config import Settings
from xhs_scout.db import connect
from xhs_scout.web import create_app


def _route(settings, path):
    return next(
        route
        for route in create_app(settings).routes
        if getattr(route, "path", None) == path
    )


def test_keyword_pool_groups_real_product_terms_and_is_get_only(tmp_path):
    settings = Settings.load(tmp_path)
    now = "2026-07-30T18:00:00+08:00"
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO search_tasks(id, keyword, source, status, created_at, updated_at)
            VALUES (89, '虚拟资料', 'manual', 'completed', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO products(
                id, fingerprint, title, first_seen_at, last_seen_at
            ) VALUES (30, 'product-30', ?, ?, ?)
            """,
            ("普通人社会化成长指南-i人社交技巧-人情世故保姆级攻略", now, now),
        )
        conn.execute(
            """
            INSERT INTO observations(id, product_id, observed_at, source)
            VALUES (31, 30, ?, 'market_search')
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO product_keyword_records(
                id, product_id, observation_id, task_id, run_id, source_root,
                source_keyword, raw_title, normalized_title, search_result_rank,
                search_context_recovered, evidence_path, evidence_json,
                decomposition_status, review_status, source_fingerprint,
                created_at, updated_at
            ) VALUES (
                1, 30, 31, 89, 'run-1', '虚拟资料', '虚拟资料', ?, ?, 1,
                1, 'evidence.json', '{}', 'complete', 'pending_review',
                'fingerprint-1', ?, ?
            )
            """,
            (
                "普通人社会化成长指南-i人社交技巧-人情世故保姆级攻略",
                "普通人社会化成长指南-i人社交技巧-人情世故保姆级攻略",
                now,
                now,
            ),
        )
        for dimension, raw_term, normalized_term, review_status in [
            ("audience", "普通人", "普通人", "approved"),
            ("audience", "I人", "i人", "approved"),
            ("function", "社交技巧", "社交技巧", "approved"),
            ("format", "成长指南", "成长指南", "approved"),
        ]:
            conn.execute(
                """
                INSERT INTO product_keyword_terms(
                    record_id, dimension, raw_term, normalized_term,
                    evidence_excerpt, review_status, created_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dimension,
                    raw_term,
                    normalized_term,
                    "普通人社会化成长指南-i人社交技巧-人情世故保姆级攻略",
                    review_status,
                    now,
                ),
            )

    route = _route(settings, "/api/keyword-pool")
    assert route.methods == {"GET"}
    result = route.endpoint()

    assert result["total_terms"] == 4
    assert result["source_product_count"] == 1
    categories = {item["dimension"]: item for item in result["categories"]}
    assert [item["term"] for item in categories["audience"]["terms"]] == [
        "I人",
        "普通人",
    ]
    assert categories["function"]["terms"][0]["term"] == "社交技巧"
    assert categories["format"]["terms"][0]["term"] == "成长指南"
    assert result["source_products"][0]["product_id"] == 30
    assert result["scope"]["production_queue_write"] is False
    assert result["scope"]["search_trigger"] is False
