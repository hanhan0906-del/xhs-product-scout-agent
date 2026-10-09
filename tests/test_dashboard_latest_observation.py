import json

from xhs_scout.db import connect, dashboard_stats


def test_dashboard_uses_latest_observation_and_assessment_per_product(tmp_path):
    db_path = tmp_path / "dashboard.sqlite3"

    with connect(db_path) as conn:
        products = [
            ("product-a", "商品 A", "https://www.xiaohongshu.com/goods/a"),
            ("product-b", "商品 B", "https://xhslink.com/a/product-b"),
            ("product-c", "商品 C", "https://www.xiaohongshu.com/goods/c"),
        ]
        product_ids = {}
        for fingerprint, title, share_url in products:
            cur = conn.execute(
                """
                INSERT INTO products(
                    fingerprint, title, share_url, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, '2026-07-28T08:00:00+08:00',
                                 '2026-07-28T10:00:00+08:00')
                """,
                (fingerprint, title, share_url),
            )
            product_ids[fingerprint] = cur.lastrowid

        observation_ids = {}
        for fingerprint, observed_at, sales in [
            ("product-a", "2026-07-28T08:00:00+08:00", 100),
            ("product-a", "2026-07-28T10:00:00+08:00", 300),
            ("product-b", "2026-07-28T09:00:00+08:00", 200),
            ("product-c", "2026-07-28T08:30:00+08:00", 50),
            ("product-c", "2026-07-28T11:00:00+08:00", 500),
        ]:
            cur = conn.execute(
                """
                INSERT INTO observations(
                    product_id, observed_at, source, cumulative_sales_min,
                    raw_signals_json
                ) VALUES (?, ?, 'test', ?, '{}')
                """,
                (product_ids[fingerprint], observed_at, sales),
            )
            observation_ids[(fingerprint, observed_at)] = cur.lastrowid

        for fingerprint, assessed_at, status in [
            ("product-a", "2026-07-28T08:05:00+08:00", "candidate"),
            ("product-a", "2026-07-28T10:05:00+08:00", "needs_review"),
            ("product-b", "2026-07-28T09:05:00+08:00", "needs_review"),
            ("product-b", "2026-07-28T10:05:00+08:00", "candidate"),
            ("product-c", "2026-07-28T11:05:00+08:00", "candidate"),
        ]:
            conn.execute(
                """
                INSERT INTO candidate_assessments(
                    product_id, assessed_at, evidence_grade, score,
                    reasons_json, status
                ) VALUES (?, ?, 'B', 60, '[]', ?)
                """,
                (product_ids[fingerprint], assessed_at, status),
            )

        stats = dashboard_stats(conn)

    recent_by_title = {row["title"]: row for row in stats["recent"]}

    assert len(stats["recent"]) == 3
    assert stats["candidates"] == 2
    assert stats["gray_qualified_candidates"] == 0
    assert stats["qualified_candidates"] == 0
    assert all(row["gray_metric_count"] == 0 for row in stats["recent"])
    assert recent_by_title["商品 A"]["assessment_status"] == "needs_review"
    assert recent_by_title["商品 A"]["collection_status"] == "partial"
    assert recent_by_title["商品 A"]["task_result_valid"] is False
    assert recent_by_title["商品 A"]["candidate_qualified"] is False
    assert recent_by_title["商品 A"]["observation_id"] == observation_ids[
        ("product-a", "2026-07-28T10:00:00+08:00")
    ]
    assert recent_by_title["商品 A"]["cumulative_sales_min"] == 300
    assert recent_by_title["商品 C"]["observation_id"] == observation_ids[
        ("product-c", "2026-07-28T11:00:00+08:00")
    ]
    assert recent_by_title["商品 C"]["cumulative_sales_min"] == 500
    assert {
        title: row["share_url"] for title, row in recent_by_title.items()
    } == {
        "商品 A": "https://www.xiaohongshu.com/goods/a",
        "商品 B": "https://xhslink.com/a/product-b",
        "商品 C": "https://www.xiaohongshu.com/goods/c",
    }


def test_dashboard_does_not_truncate_products_after_thirty(tmp_path):
    db_path = tmp_path / "dashboard-many.sqlite3"
    with connect(db_path) as conn:
        for number in range(35):
            cur = conn.execute(
                """
                INSERT INTO products(fingerprint, title, first_seen_at, last_seen_at)
                VALUES (?, ?, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z')
                """,
                (f"fp-{number}", f"商品 {number}"),
            )
            conn.execute(
                """
                INSERT INTO observations(product_id, observed_at, source, raw_signals_json)
                VALUES (?, ?, 'test', '{}')
                """,
                (cur.lastrowid, f"2026-08-01T00:{number:02d}:00Z"),
            )
        stats = dashboard_stats(conn)

    assert stats["products"] == 35
    assert len(stats["recent"]) == 35


def test_dashboard_candidate_requires_complete_task_hot_metrics_and_low_follower(tmp_path):
    db_path = tmp_path / "dashboard-qualified.sqlite3"
    metrics = json.dumps(
        {
            "metrics_strip": {
                "frames": [
                    {
                        "signals": {
                            "sales_30d_min": 1000,
                            "positive_reviews_30d_min": 500,
                            "favorites_30d_min": 200,
                        }
                    }
                ]
            }
        }
    )
    with connect(db_path) as conn:
        product_ids = []
        observation_ids = []
        for number in range(4):
            product = conn.execute(
                """
                INSERT INTO products(fingerprint, title, first_seen_at, last_seen_at)
                VALUES (?, ?, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z')
                """,
                (f"qualified-{number}", f"资格商品 {number}"),
            ).lastrowid
            observation = conn.execute(
                """
                INSERT INTO observations(product_id, observed_at, source, raw_signals_json)
                VALUES (?, ?, 'test', ?)
                """,
                (product, f"2026-08-01T00:0{number}:00Z", metrics if number != 2 else "{}"),
            ).lastrowid
            product_ids.append(product)
            observation_ids.append(observation)
        for number, (product, observation) in enumerate(zip(product_ids, observation_ids)):
            task = conn.execute(
                """
                INSERT INTO search_tasks(keyword, created_at, updated_at)
                VALUES (?, '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z')
                """,
                (f"关键词{number}",),
            ).lastrowid
            if number != 1:
                conn.execute(
                    """
                    INSERT INTO task_results(task_id, product_id, observation_id, captured_at, valid)
                    VALUES (?, ?, ?, '2026-08-01T00:00:00Z', 1)
                    """,
                    (task, product, observation),
                )
            if number != 3:
                followers = 188 if number != 2 else 5000
                conn.execute(
                    """
                    INSERT INTO note_observations(
                        product_id, captured_at, source, follower_count, raw_json
                    ) VALUES (?, '2026-08-01T00:00:00Z',
                              'seller_profile_from_product', ?, '{}')
                    """,
                    (product, followers),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO note_observations(
                        product_id, captured_at, source, follower_count, raw_json
                    ) VALUES (?, '2026-08-01T00:00:00Z',
                              'seller_profile_from_product', NULL,
                              '{"follower_display_status":"not_displayed"}')
                    """,
                    (product,),
                )
        stats = dashboard_stats(conn)

    by_title = {row["title"]: row for row in stats["recent"]}
    assert stats["qualified_candidates"] == 1
    assert by_title["资格商品 0"]["candidate_qualified"] is True
    assert by_title["资格商品 0"]["collection_status"] == "complete"
    assert by_title["资格商品 1"]["collection_status"] == "partial"
    assert "最新观察缺少有效任务结果" in by_title["资格商品 1"]["qualification_reasons"]
    assert by_title["资格商品 2"]["hot_metrics_qualified"] is False
    assert by_title["资格商品 2"]["low_follower_qualified"] is False
    assert by_title["资格商品 3"]["collection_status"] == "complete"
    assert by_title["资格商品 3"]["seller_follower_count"] is None
    assert by_title["资格商品 3"]["seller_follower_display_status"] == "not_displayed"
    assert by_title["资格商品 3"]["low_follower_qualified"] is False
    assert by_title["资格商品 3"]["candidate_qualified"] is False
    assert "店铺页面未显示粉丝数，按非低粉处理" in by_title["资格商品 3"]["qualification_reasons"]


def test_dashboard_does_not_fall_back_to_older_seller_evidence(tmp_path):
    db_path = tmp_path / "dashboard-latest-seller.sqlite3"
    metrics = json.dumps(
        {
            "metrics_strip": {
                "frames": [
                    {
                        "signals": {
                            "sales_30d_min": 1000,
                            "positive_reviews_30d_min": 500,
                            "favorites_30d_min": 200,
                        }
                    }
                ]
            }
        }
    )
    with connect(db_path) as conn:
        product_id = conn.execute(
            """
            INSERT INTO products(fingerprint, title, first_seen_at, last_seen_at)
            VALUES ('seller-latest', '店铺证据只看最新',
                    '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z')
            """
        ).lastrowid
        observation_id = conn.execute(
            """
            INSERT INTO observations(product_id, observed_at, source, raw_signals_json)
            VALUES (?, '2026-08-01T00:00:00Z', 'test', ?)
            """,
            (product_id, metrics),
        ).lastrowid
        task_id = conn.execute(
            """
            INSERT INTO search_tasks(keyword, created_at, updated_at)
            VALUES ('店铺证据', '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z')
            """
        ).lastrowid
        conn.execute(
            """
            INSERT INTO task_results(task_id, product_id, observation_id, captured_at, valid)
            VALUES (?, ?, ?, '2026-08-01T00:00:00Z', 1)
            """,
            (task_id, product_id, observation_id),
        )
        conn.execute(
            """
            INSERT INTO note_observations(
                product_id, captured_at, source, follower_count, raw_json
            ) VALUES (?, '2026-08-01T00:00:01Z',
                      'seller_profile_from_product', 188, '{}')
            """,
            (product_id,),
        )
        conn.execute(
            """
            INSERT INTO note_observations(
                product_id, captured_at, source, follower_count, raw_json
            ) VALUES (?, '2026-08-01T00:00:02Z',
                      'seller_profile_from_product', NULL, '{}')
            """,
            (product_id,),
        )
        stats = dashboard_stats(conn)

    row = stats["recent"][0]
    assert row["seller_follower_count"] is None
    assert row["seller_follower_display_status"] == "missing"
    assert row["collection_status"] == "partial"
    assert row["low_follower_qualified"] is False
    assert row["candidate_qualified"] is False
    assert "缺少商品店铺粉丝证据" in row["qualification_reasons"]
