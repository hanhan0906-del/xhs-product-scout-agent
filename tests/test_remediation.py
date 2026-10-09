import json
import sqlite3

import pytest

from xhs_scout.remediation import plan_remediation, read_fixture_rows


NOW = "2026-07-29T12:00:00+08:00"


def product(product_id, **overrides):
    row = {
        "product_id": product_id,
        "status": "candidate",
        "score": 50,
        "has_valid_search_attribution": 1,
        "has_supported_product_link": 1,
        "has_metrics_strip": 1,
        "has_note_evidence": 1,
        "has_profile_evidence": 1,
    }
    row.update(overrides)
    return row


def items_by_id(plan):
    return {
        item.product_id: item
        for batch in plan.batches
        for item in batch.items
    }


def test_identity_precedes_metrics_note_and_profile():
    plan = plan_remediation(
        [
            product(
                9,
                score=80,
                has_valid_search_attribution=0,
                has_supported_product_link=0,
                has_metrics_strip=0,
                has_note_evidence=0,
                has_profile_evidence=0,
            ),
            product(18, has_metrics_strip=0, has_note_evidence=0, has_profile_evidence=0),
            product(23, has_note_evidence=0, has_profile_evidence=0),
            product(
                30,
                has_profile_evidence=0,
                note_author_identifiable=1,
                note_published_days_ago=2,
                note_likes=120,
            ),
        ],
        now=NOW,
    )

    assert [batch.stage for batch in plan.batches] == [
        "identity",
        "metrics",
        "note",
        "profile",
    ]
    items = items_by_id(plan)
    assert items[9].actions == (
        "rediscover_valid_search_attribution",
        "capture_supported_product_link",
    )
    assert items[9].blocks == ("metrics", "note", "profile")
    assert items[18].required_before == (
        "valid_search_attribution",
        "supported_product_link",
    )
    assert items[23].blocks == ("profile",)
    assert items[30].stage == "profile"


def test_product_20_is_quarantined_and_never_enters_batches():
    plan = plan_remediation(
        [
            product(
                20,
                has_supported_product_link=0,
                has_metrics_strip=0,
                latest_search_attribution_valid=0,
            )
        ],
        now=NOW,
    )

    assert plan.batches == ()
    assert plan.isolated[0].product_id == 20
    assert plan.isolated[0].code == "search_attribution_quarantine"
    assert "new_valid_search_discovery" in plan.isolated[0].blocked_by


def test_missing_search_attribution_forces_rediscovery_even_with_high_score():
    plan = plan_remediation(
        [
            product(
                9,
                score=99,
                has_valid_search_attribution=0,
                has_metrics_strip=0,
                has_note_evidence=0,
            )
        ],
        now=NOW,
    )

    item = plan.batches[0].items[0]
    assert item.stage == "identity"
    assert item.actions[0] == "rediscover_valid_search_attribution"


def test_known_high_follower_is_not_sent_to_profile():
    plan = plan_remediation(
        [
            product(
                19,
                has_profile_evidence=0,
                known_follower_count=5600,
                note_author_identifiable=1,
                note_published_days_ago=1,
                note_likes=2000,
            )
        ],
        now=NOW,
    )

    assert plan.batches == ()
    assert plan.skipped[0].product_id == 19
    assert plan.skipped[0].code == "profile_skipped_known_high_follower"


@pytest.mark.parametrize(
    ("overrides", "expected_profile"),
    [
        (
            {
                "note_author_identifiable": 1,
                "note_published_days_ago": 2,
                "note_likes": 100,
                "potential_follower_ceiling": 199,
            },
            True,
        ),
        (
            {
                "note_author_identifiable": 1,
                "note_published_days_ago": 2,
                "note_likes": 999,
                "potential_follower_ceiling": 2000,
            },
            False,
        ),
        (
            {
                "note_author_identifiable": 1,
                "note_published_days_ago": 2,
                "note_likes": 1000,
                "potential_follower_ceiling": 2000,
            },
            True,
        ),
        (
            {
                "note_author_identifiable": 1,
                "note_published_days_ago": 8,
                "note_likes": 2000,
            },
            False,
        ),
    ],
)
def test_profile_requires_recent_identifiable_note_and_interaction_gate(
    overrides, expected_profile
):
    plan = plan_remediation(
        [product(31, has_profile_evidence=0, **overrides)],
        now=NOW,
    )

    assert bool(plan.batches) is expected_profile
    if expected_profile:
        assert plan.batches[0].stage == "profile"
    else:
        assert plan.skipped[0].product_id == 31


def test_product_cooldown_is_exactly_24_hours():
    cooling = plan_remediation(
        [product(40, has_metrics_strip=0, last_remediation_at="2026-07-28T12:00:01+08:00")],
        now=NOW,
    )
    eligible = plan_remediation(
        [product(40, has_metrics_strip=0, last_remediation_at="2026-07-28T12:00:00+08:00")],
        now=NOW,
    )

    assert cooling.isolated[0].code == "product_cooldown"
    assert cooling.isolated[0].retry_at == "2026-07-29T12:00:01+08:00"
    assert eligible.batches[0].items[0].product_id == 40


def test_limits_are_clamped_and_batches_are_deterministic():
    rows = [
        product(i, score=100 - i, has_supported_product_link=0)
        for i in (5, 2, 4, 1, 3, 6, 7)
    ]
    plan = plan_remediation(
        reversed(rows),
        now=NOW,
        policy={"per_batch_limit": 99, "hourly_visit_limit": 99},
    )

    assert [len(batch.items) for batch in plan.batches] == [2, 2, 2, 1]
    assert [batch.hour_window for batch in plan.batches] == [1, 1, 1, 2]
    assert [
        item.product_id for batch in plan.batches for item in batch.items
    ] == [1, 2, 3, 4, 5, 6, 7]
    assert all(batch.max_items == 2 for batch in plan.batches)


def test_sqlite_fixture_is_select_only_input():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE remediation_products (
            product_id INTEGER,
            status TEXT,
            score REAL,
            has_valid_search_attribution INTEGER,
            has_supported_product_link INTEGER,
            has_metrics_strip INTEGER,
            has_note_evidence INTEGER,
            has_profile_evidence INTEGER
        )
        """
    )
    connection.execute(
        "INSERT INTO remediation_products VALUES (18, 'candidate', 67.7, 1, 1, 0, 0, 0)"
    )
    connection.commit()
    before = connection.total_changes

    rows = read_fixture_rows(connection)
    plan = plan_remediation(connection, now=NOW)

    assert rows[0]["product_id"] == 18
    assert plan.batches[0].stage == "metrics"
    assert connection.total_changes == before


def test_invalid_fixture_table_and_duplicate_ids_fail_closed():
    connection = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="simple SQLite identifier"):
        read_fixture_rows(connection, table="items; DROP TABLE items")
    with pytest.raises(ValueError, match="duplicate product_id"):
        plan_remediation([product(1), product(1)], now=NOW)


def test_non_candidate_rows_are_excluded_and_complete_rows_are_reported():
    plan = plan_remediation(
        [product(50, status="observed"), product(51)],
        now=NOW,
    )

    assert plan.excluded_product_ids == (50,)
    assert plan.completed_product_ids == (51,)
    assert plan.as_dict()["policy"]["per_batch_limit"] == 2
    assert json.loads(json.dumps(plan.as_dict()))["completed_product_ids"] == [51]


def test_product_20_can_only_reenter_after_explicit_release_with_new_search():
    plan = plan_remediation(
        [
            product(
                20,
                quarantine_released=1,
                latest_search_attribution_valid=1,
                has_supported_product_link=0,
            )
        ],
        now=NOW,
    )

    assert plan.isolated == ()
    assert plan.batches[0].stage == "identity"
    assert plan.batches[0].items[0].actions == ("capture_supported_product_link",)


def test_needs_review_sorts_before_higher_scoring_candidates():
    plan = plan_remediation(
        [
            product(19, score=90, has_supported_product_link=0),
            product(22, status="needs_review", score=10, has_supported_product_link=0),
        ],
        now=NOW,
    )

    assert [item.product_id for item in plan.batches[0].items] == [22, 19]


def test_t18_snapshot_routes_20_to_quarantine_and_batches_other_identity_gaps():
    scores = {
        1: 35.0,
        2: 30.0,
        3: 53.0,
        9: 80.0,
        11: 61.0,
        12: 56.9,
        13: 57.7,
        16: 40.7,
        17: 42.8,
        18: 67.7,
        19: 78.7,
        20: 44.2,
        22: 56.2,
        23: 61.0,
    }
    rows = [
        product(
            product_id,
            status="needs_review" if product_id == 22 else "candidate",
            score=score,
            has_supported_product_link=0,
            has_valid_search_attribution=product_id not in {1, 2, 3, 9, 11, 12},
        )
        for product_id, score in scores.items()
    ]

    plan = plan_remediation(rows, now=NOW)

    assert [item.product_id for item in plan.isolated] == [20]
    flattened = [item for batch in plan.batches for item in batch.items]
    assert len(flattened) == 13
    assert flattened[0].product_id == 22
    assert all(item.stage == "identity" for item in flattened)
    rediscovery_ids = {
        item.product_id
        for item in flattened
        if "rediscover_valid_search_attribution" in item.actions
    }
    assert rediscovery_ids == {1, 2, 3, 9, 11, 12}
