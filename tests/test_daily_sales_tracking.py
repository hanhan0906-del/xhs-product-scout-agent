from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xhs_scout.daily_sales_tracking import (
    DailySalesBatchHardStop,
    claim_daily_sales_task,
    get_daily_sales_cycle_summary,
    get_next_pending_daily_sales_task,
    hard_stop_daily_sales_cycle,
    initialize_daily_sales_tracking,
    plan_midnight_cycle,
    record_daily_sales_result,
    recover_expired_daily_sales_tasks,
)


CYCLE = "2026-07-30"
CLAIM_AT = "2026-07-29T16:00:00+00:00"
OBSERVED_AT = "2026-07-30T00:05:00+08:00"
ACTION_AT = "2026-07-29T16:05:00+00:00"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "daily-sales.sqlite"


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            title TEXT,
            share_url TEXT,
            last_seen_at TEXT
        );
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            cumulative_sales_display TEXT,
            cumulative_sales_exact INTEGER,
            cumulative_sales_min INTEGER,
            daily_sales_delta INTEGER,
            raw_signals_json TEXT
        );
        """
    )
    initialize_daily_sales_tracking(connection)
    yield connection
    connection.close()


def _add_products(conn: sqlite3.Connection, count: int, *, baseline: int | None = 100) -> None:
    for product_id in range(1, count + 1):
        conn.execute(
            "INSERT INTO products(id, title, share_url, last_seen_at) VALUES (?, ?, ?, ?)",
            (product_id, f"商品{product_id}", f"https://example.test/{product_id}", CLAIM_AT),
        )
        if baseline is not None:
            conn.execute(
                """
                INSERT INTO observations(
                    product_id, observed_at, cumulative_sales_display,
                    cumulative_sales_exact, cumulative_sales_min,
                    daily_sales_delta, raw_signals_json
                ) VALUES (?, '2026-07-29T00:04:00+08:00', ?, ?, ?, NULL, '{}')
                """,
                (product_id, str(baseline), baseline, baseline),
            )
    conn.commit()


def _plan_ids(conn: sqlite3.Connection) -> dict[int, int]:
    return {
        product_id: plan_id
        for plan_id, product_id in conn.execute(
            "SELECT id, product_id FROM daily_sales_plans ORDER BY sequence_no"
        ).fetchall()
    }


def _followed(*product_ids: int) -> list[dict[str, object]]:
    return [
        {
            "product_id": product_id,
            "verified_direct_url": (
                f"https://www.xiaohongshu.com/goods-detail/{product_id}"
            ),
        }
        for product_id in product_ids
    ]


def _claim(
    conn: sqlite3.Connection,
    plan_id: int,
    owner: str = "collector-a",
    *,
    now: str = CLAIM_AT,
    lease_seconds: int = 900,
) -> dict:
    return claim_daily_sales_task(
        conn,
        plan_id=plan_id,
        owner=owner,
        now=now,
        lease_seconds=lease_seconds,
    )


def _record(
    conn: sqlite3.Connection,
    plan_id: int,
    product_id: int,
    owner: str = "collector-a",
    **kwargs,
) -> dict:
    return record_daily_sales_result(
        conn,
        plan_id=plan_id,
        owner=owner,
        observed_product_id=product_id,
        observed_at=OBSERVED_AT,
        action_at=ACTION_AT,
        **kwargs,
    )


def test_daily_snapshot_contains_only_caller_followed_products_without_eligibility_filter(
    conn: sqlite3.Connection,
) -> None:
    _add_products(conn, 3)

    result = plan_midnight_cycle(
        conn,
        cycle_date=CYCLE,
        followed_products=_followed(3, 1),
        created_at=CLAIM_AT,
    )
    summary = get_daily_sales_cycle_summary(conn, cycle_date=CYCLE)
    next_task = get_next_pending_daily_sales_task(conn, cycle_date=CYCLE)
    claim = _claim(conn, next_task["plan_id"])

    assert result["code"] == "snapshot_created"
    assert result["snapshot_count"] == 2
    assert summary["snapshot_count"] == summary["total"] == 2
    assert [item["product_id"] for item in summary["items"]] == [3, 1]
    assert summary["pending"] == 2
    assert all("goods-detail" in item["verified_direct_url"] for item in summary["items"])
    assert next_task["verified_direct_url"].endswith("/3")
    assert claim["verified_direct_url"] == next_task["verified_direct_url"]


def test_empty_followed_snapshot_completes_empty_batch(conn: sqlite3.Connection) -> None:
    result = plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=[], created_at=CLAIM_AT
    )
    summary = get_daily_sales_cycle_summary(conn, cycle_date=CYCLE)

    assert result["snapshot_count"] == 0
    assert summary["batch_status"] == "completed"
    assert summary["total"] == 0
    assert summary["all_items_final"] is True


def test_expiring_xhslink_share_url_is_rejected_before_snapshot(
    conn: sqlite3.Connection,
) -> None:
    _add_products(conn, 1)
    short_url = "https://xhslink.com/m/7X9KDzX3Dxc"

    with pytest.raises(ValueError):
        plan_midnight_cycle(
            conn,
            cycle_date=CYCLE,
            followed_products=[
                {"product_id": 1, "verified_direct_url": short_url}
            ],
            created_at=CLAIM_AT,
        )

    assert conn.execute("SELECT COUNT(*) FROM daily_sales_batches").fetchone()[0] == 0


def test_documented_goods_deeplink_is_frozen_without_search_fallback(
    conn: sqlite3.Connection,
) -> None:
    _add_products(conn, 1)
    direct_url = "xhsdiscover://page/goods/64ff001"

    created = plan_midnight_cycle(
        conn,
        cycle_date=CYCLE,
        followed_products=[
            {"product_id": 1, "verified_direct_url": direct_url}
        ],
        created_at=CLAIM_AT,
    )
    task = get_next_pending_daily_sales_task(conn, cycle_date=CYCLE)

    assert created["code"] == "snapshot_created"
    assert task["verified_direct_url"] == direct_url


def test_snapshot_is_idempotent_and_frozen_against_later_changes(
    conn: sqlite3.Connection,
) -> None:
    _add_products(conn, 3)
    first = plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )
    duplicate = plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )
    changed = plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1), created_at=CLAIM_AT
    )

    assert first["created"] is True
    assert duplicate["code"] == "already_planned"
    assert changed["code"] == "snapshot_frozen_mismatch"
    assert conn.execute("SELECT COUNT(*) FROM daily_sales_plans").fetchone()[0] == 2


def test_cancel_following_does_not_rewrite_today_but_changes_next_day(
    conn: sqlite3.Connection,
) -> None:
    _add_products(conn, 2)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )
    same_day = plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1), created_at=CLAIM_AT
    )
    next_day = plan_midnight_cycle(
        conn,
        cycle_date="2026-07-31",
        followed_products=_followed(1),
        created_at="2026-07-30T16:00:00+00:00",
    )

    today = get_daily_sales_cycle_summary(conn, cycle_date=CYCLE)
    tomorrow = get_daily_sales_cycle_summary(conn, cycle_date="2026-07-31")
    assert same_day["code"] == "snapshot_frozen_mismatch"
    assert [item["product_id"] for item in today["items"]] == [1, 2]
    assert next_day["code"] == "snapshot_created"
    assert [item["product_id"] for item in tomorrow["items"]] == [1]


def test_snapshot_missing_product_fails_atomically(conn: sqlite3.Connection) -> None:
    _add_products(conn, 1)

    result = plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 999), created_at=CLAIM_AT
    )

    assert result["code"] == "snapshot_product_not_found"
    assert result["missing_product_ids"] == [999]
    assert conn.execute("SELECT COUNT(*) FROM daily_sales_batches").fetchone()[0] == 0


@pytest.mark.parametrize(
    "item",
    [
        {"product_id": 1},
        {"product_id": 1, "verified_direct_url": ""},
        {"product_id": 1, "verified_direct_url": "https://xhslink.com"},
        {"product_id": 1, "verified_direct_url": "https://xhslink.com/m/abc"},
        {"product_id": 1, "verified_direct_url": "http://www.xiaohongshu.com/goods-detail/1"},
        {"product_id": 1, "verified_direct_url": "https://evil.test/goods-detail/1"},
        {"product_id": 1, "verified_direct_url": "https://www.xiaohongshu.com/explore/1"},
    ],
)
def test_missing_or_invalid_verified_direct_url_fails_closed(
    conn: sqlite3.Connection, item: dict[str, object]
) -> None:
    _add_products(conn, 1)

    with pytest.raises(ValueError):
        plan_midnight_cycle(
            conn, cycle_date=CYCLE, followed_products=[item], created_at=CLAIM_AT
        )

    assert conn.execute("SELECT COUNT(*) FROM daily_sales_batches").fetchone()[0] == 0


def test_exact_and_fuzzy_results_and_complete_summary(conn: sqlite3.Connection) -> None:
    _add_products(conn, 2)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )
    plans = _plan_ids(conn)

    _claim(conn, plans[1], "owner-1")
    exact = _record(
        conn, plans[1], 1, "owner-1", cumulative_sales_exact=112, cumulative_sales_display="112"
    )
    _claim(conn, plans[2], "owner-2")
    fuzzy = _record(
        conn, plans[2], 2, "owner-2", cumulative_sales_display="已售1万+"
    )
    summary = get_daily_sales_cycle_summary(conn, cycle_date=CYCLE)

    assert exact["daily_sales_delta"] == 12
    assert fuzzy["status"] == "completed_fuzzy"
    assert summary["completed_exact"] == summary["completed_fuzzy"] == 1
    assert summary["batch_status"] == "completed"
    assert summary["all_items_final"] is True
    assert summary["items"][1]["daily_sales_delta"] is None


def test_completed_exact_result_is_used_as_next_days_baseline(
    conn: sqlite3.Connection,
) -> None:
    _add_products(conn, 1)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1), created_at=CLAIM_AT
    )
    first_plan = _plan_ids(conn)[1]
    _claim(conn, first_plan)
    _record(conn, first_plan, 1, cumulative_sales_exact=112)

    plan_midnight_cycle(
        conn,
        cycle_date="2026-07-31",
        followed_products=_followed(1),
        created_at="2026-07-30T16:00:00+00:00",
    )
    second_plan = conn.execute(
        "SELECT id FROM daily_sales_plans WHERE cycle_date='2026-07-31'"
    ).fetchone()[0]
    _claim(
        conn,
        second_plan,
        "collector-b",
        now="2026-07-30T16:00:00+00:00",
    )
    second = record_daily_sales_result(
        conn,
        plan_id=second_plan,
        owner="collector-b",
        observed_product_id=1,
        observed_at="2026-07-31T00:05:00+08:00",
        cumulative_sales_exact=120,
        action_at="2026-07-30T16:05:00+00:00",
    )

    assert second["status"] == "completed_exact"
    assert second["daily_sales_delta"] == 8


def test_ordinary_item_failure_isolated_and_next_product_continues(
    conn: sqlite3.Connection,
) -> None:
    _add_products(conn, 3)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2, 3), created_at=CLAIM_AT
    )
    plans = _plan_ids(conn)
    _claim(conn, plans[1])

    failed = _record(
        conn,
        plans[1],
        1,
        outcome="failed",
        reason_code="button_temporarily_missing",
    )
    next_task = get_next_pending_daily_sales_task(conn, cycle_date=CYCLE)
    second_claim = _claim(conn, plans[2], "collector-b")

    assert failed["status"] == "failed"
    assert failed["continue_batch"] is True
    assert next_task["product_id"] == 2
    assert second_claim["claimed"] is True


def test_ordinary_skip_is_terminal_and_not_repeated(conn: sqlite3.Connection) -> None:
    _add_products(conn, 2)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )
    plans = _plan_ids(conn)
    _claim(conn, plans[1])
    skipped = _record(
        conn, plans[1], 1, outcome="skipped", reason_code="product_unavailable"
    )
    retry = _claim(conn, plans[1], "collector-b")
    next_task = get_next_pending_daily_sales_task(conn, cycle_date=CYCLE)

    assert skipped["continue_batch"] is True
    assert retry["code"] == "terminal"
    assert next_task["product_id"] == 2


def test_process_restart_recovers_only_unfinished_and_never_repeats_completed(
    conn: sqlite3.Connection,
    db_path: Path,
) -> None:
    _add_products(conn, 3)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2, 3), created_at=CLAIM_AT
    )
    plans = _plan_ids(conn)
    _claim(conn, plans[1], lease_seconds=900)
    _record(conn, plans[1], 1, cumulative_sales_exact=101)
    _claim(conn, plans[2], "owner-before-restart", lease_seconds=60)
    conn.close()

    restarted = sqlite3.connect(db_path)
    recovery = recover_expired_daily_sales_tasks(
        restarted, now="2026-07-29T16:02:00+00:00", recovery_owner="restart"
    )
    next_task = get_next_pending_daily_sales_task(restarted, cycle_date=CYCLE)
    completed = restarted.execute(
        "SELECT status, claim_count FROM daily_sales_plans WHERE id=?", (plans[1],)
    ).fetchone()
    restarted.close()

    assert recovery == {"recovered_count": 1, "recovered_plan_ids": [plans[2]]}
    assert next_task["product_id"] == 2
    assert completed == ("completed_exact", 1)


def test_second_owner_cannot_steal_unexpired_lease(conn: sqlite3.Connection) -> None:
    _add_products(conn, 1)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1), created_at=CLAIM_AT
    )
    plan_id = _plan_ids(conn)[1]
    _claim(conn, plan_id, "collector-a")

    second = _claim(
        conn, plan_id, "collector-b", now="2026-07-29T16:01:00+00:00"
    )

    assert second["code"] == "lease_held"
    assert second["owner"] == "collector-a"


@pytest.mark.parametrize(
    "reason_code",
    ["captcha", "risk_control", "anr", "unknown_page", "database_lock_error"],
)
def test_safety_condition_hard_stops_whole_batch(
    conn: sqlite3.Connection, reason_code: str
) -> None:
    _add_products(conn, 2)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )
    plans = _plan_ids(conn)
    _claim(conn, plans[1])

    stopped = _record(
        conn, plans[1], 1, outcome="hard_stop", reason_code=reason_code
    )
    next_task = get_next_pending_daily_sales_task(conn, cycle_date=CYCLE)
    blocked_claim = _claim(conn, plans[2], "collector-b")
    recovery = recover_expired_daily_sales_tasks(
        conn, now="2026-07-30T01:00:00+08:00"
    )

    assert stopped["continue_batch"] is False
    assert stopped["status"] == "risk_stopped"
    assert next_task["code"] == "batch_hard_stopped"
    assert blocked_claim["code"] == "batch_hard_stopped"
    assert recovery["recovered_count"] == 0


def test_unknown_identity_hard_stops_batch(conn: sqlite3.Connection) -> None:
    _add_products(conn, 2)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )
    plans = _plan_ids(conn)
    _claim(conn, plans[1])

    stopped = record_daily_sales_result(
        conn,
        plan_id=plans[1],
        owner="collector-a",
        observed_product_id=None,
        observed_at=OBSERVED_AT,
        cumulative_sales_exact=120,
        action_at=ACTION_AT,
    )
    summary = get_daily_sales_cycle_summary(conn, cycle_date=CYCLE)

    assert stopped["reason_code"] == "identity_unknown"
    assert stopped["continue_batch"] is False
    assert summary["batch_status"] == "hard_stopped"
    assert summary["pending"] == 1


def test_external_hard_stop_blocks_batch_without_consuming_pending_item(
    conn: sqlite3.Connection,
) -> None:
    _add_products(conn, 2)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )

    stopped = hard_stop_daily_sales_cycle(
        conn,
        cycle_date=CYCLE,
        reason_code="unknown_page",
        owner="collector",
        action_at=ACTION_AT,
    )
    summary = get_daily_sales_cycle_summary(conn, cycle_date=CYCLE)

    assert stopped["code"] == "batch_hard_stopped"
    assert summary["pending"] == 2
    assert summary["all_items_final"] is False


def test_terminal_result_cannot_be_overwritten(conn: sqlite3.Connection) -> None:
    _add_products(conn, 1)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1), created_at=CLAIM_AT
    )
    plan_id = _plan_ids(conn)[1]
    _claim(conn, plan_id)
    first = _record(conn, plan_id, 1, cumulative_sales_exact=101)
    duplicate = _record(conn, plan_id, 1, cumulative_sales_exact=999)

    assert first["status"] == "completed_exact"
    assert duplicate["code"] == "already_final"
    assert conn.execute(
        "SELECT cumulative_sales_exact FROM daily_sales_plans WHERE id=?", (plan_id,)
    ).fetchone()[0] == 101


@pytest.mark.parametrize(
    ("baseline", "observed_at", "exact", "expected_reason"),
    [
        (100, OBSERVED_AT, 99, "sales_decreased"),
        (None, OBSERVED_AT, 101, "missing_previous_exact_baseline"),
        (100, "2026-07-30T00:16:00+08:00", 101, "outside_midnight_window"),
    ],
)
def test_invalid_sample_is_ordinary_item_failure_and_batch_can_continue(
    conn: sqlite3.Connection,
    baseline: int | None,
    observed_at: str,
    exact: int,
    expected_reason: str,
) -> None:
    _add_products(conn, 2, baseline=baseline)
    plan_midnight_cycle(
        conn, cycle_date=CYCLE, followed_products=_followed(1, 2), created_at=CLAIM_AT
    )
    plan_id = _plan_ids(conn)[1]
    _claim(conn, plan_id)

    result = record_daily_sales_result(
        conn,
        plan_id=plan_id,
        owner="collector-a",
        observed_product_id=1,
        observed_at=observed_at,
        cumulative_sales_exact=exact,
        action_at=ACTION_AT,
    )

    assert result["status"] == "failed"
    assert result["reason_code"] == expected_reason
    assert result["continue_batch"] is True
    assert get_next_pending_daily_sales_task(conn, cycle_date=CYCLE)["product_id"] == 2


def test_sqlite_lock_is_raised_as_batch_hard_stop_signal(
    conn: sqlite3.Connection, db_path: Path
) -> None:
    _add_products(conn, 1)
    blocker = sqlite3.connect(db_path, timeout=0)
    contender = sqlite3.connect(db_path, timeout=0)
    blocker.execute("BEGIN EXCLUSIVE")

    with pytest.raises(DailySalesBatchHardStop) as captured:
        plan_midnight_cycle(
            contender,
            cycle_date=CYCLE,
            followed_products=_followed(1),
            created_at=CLAIM_AT,
        )

    blocker.rollback()
    blocker.close()
    contender.close()
    assert captured.value.reason_code == "database_lock_error"
