from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xhs_scout.daily_sales_runner import (
    prepare_daily_sales_cycle,
    run_prepared_daily_sales_cycle,
)
from xhs_scout.daily_sales_tracking import (
    claim_daily_sales_task,
    get_daily_sales_cycle_summary,
)


CYCLE = "2026-07-30"
RUN_NOW = "2026-07-30T00:05:00+08:00"
BASELINE_AT = "2026-07-29T00:04:00+08:00"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "daily-sales-runner.sqlite")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            title TEXT,
            shop_name TEXT,
            share_url TEXT,
            direct_url TEXT,
            last_seen_at TEXT
        );
        CREATE TABLE product_sales_follows (
            product_id INTEGER PRIMARY KEY,
            followed_at TEXT NOT NULL,
            followed_by TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id)
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
    yield connection
    connection.close()


def _add_product(
    conn: sqlite3.Connection,
    product_id: int,
    *,
    followed: bool = True,
    url: str | None = None,
    baseline: int | None = 100,
) -> None:
    direct_url = url or f"https://www.xiaohongshu.com/goods-detail/{product_id}"
    conn.execute(
        """
        INSERT INTO products(
            id, title, shop_name, share_url, direct_url, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            f"商品{product_id}",
            "测试店铺",
            f"https://xhslink.com/m/share-{product_id}",
            direct_url,
            RUN_NOW,
        ),
    )
    if followed:
        conn.execute(
            """
            INSERT INTO product_sales_follows(product_id, followed_at, followed_by)
            VALUES (?, ?, 'operator')
            """,
            (product_id, f"2026-07-29T12:00:{product_id % 60:02d}+08:00"),
        )
    if baseline is not None:
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, cumulative_sales_display,
                cumulative_sales_exact, cumulative_sales_min,
                daily_sales_delta, raw_signals_json
            ) VALUES (?, ?, ?, ?, ?, NULL, '{}')
            """,
            (product_id, BASELINE_AT, str(baseline), baseline, baseline),
        )
    conn.commit()


def _exact(product_id: int, value: int = 110) -> dict:
    return {
        "kind": "exact",
        "observed_product_id": product_id,
        "observed_at": RUN_NOW,
        "cumulative_sales_exact": value,
        "cumulative_sales_display": str(value),
    }


def _fuzzy(product_id: int, display: str = "已售1万+") -> dict:
    return {
        "kind": "fuzzy",
        "observed_product_id": product_id,
        "observed_at": RUN_NOW,
        "cumulative_sales_display": display,
    }


def test_prepare_reads_only_followed_snapshot_and_passes_durable_target_unchanged(
    conn: sqlite3.Connection,
) -> None:
    url_30 = "xhsdiscover://page/goods/7X9KDzX3Dxc"
    _add_product(conn, 30, followed=True, url=url_30)
    _add_product(conn, 31, followed=False)
    prepared = prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    calls: list[tuple[int, str]] = []

    def collector(*, product_id: int, verified_direct_url: str) -> dict:
        calls.append((product_id, verified_direct_url))
        return _exact(product_id)

    summary = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )

    assert prepared["snapshot_count"] == prepared["current_followed_count"] == 1
    assert calls == [(30, url_30)]
    assert summary["total"] == 1
    assert summary["completed_exact"] == 1


def test_empty_followed_snapshot_is_valid_completed_cycle(
    conn: sqlite3.Connection,
) -> None:
    _add_product(conn, 1, followed=False)
    prepared = prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    called = False

    def collector(**_kwargs) -> dict:
        nonlocal called
        called = True
        return {}

    summary = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )

    assert prepared["snapshot_count"] == 0
    assert summary["batch_status"] == "completed"
    assert summary["total"] == summary["remaining"] == 0
    assert called is False


def test_same_day_snapshot_stays_frozen_after_follow_is_removed(
    conn: sqlite3.Connection,
) -> None:
    _add_product(conn, 1)
    _add_product(conn, 2)
    first = prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    conn.execute("DELETE FROM product_sales_follows WHERE product_id=2")
    conn.commit()

    repeated = prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    frozen = get_daily_sales_cycle_summary(conn, cycle_date=CYCLE)

    assert first["code"] == "snapshot_created"
    assert repeated["code"] == "snapshot_frozen_mismatch"
    assert repeated["current_followed_count"] == 1
    assert [item["product_id"] for item in frozen["items"]] == [1, 2]


def test_two_items_complete_exact_then_fuzzy(conn: sqlite3.Connection) -> None:
    _add_product(conn, 1)
    _add_product(conn, 2)
    prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)

    def collector(*, product_id: int, verified_direct_url: str) -> dict:
        assert verified_direct_url
        return _exact(product_id, 112) if product_id == 1 else _fuzzy(product_id)

    summary = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )

    assert summary["completed_exact"] == 1
    assert summary["completed_fuzzy"] == 1
    assert summary["processed_this_run"] == summary["collector_calls"] == 2
    assert summary["remaining"] == 0
    stored = conn.execute(
        """
        SELECT product_id, daily_sales_delta FROM daily_sales_plans
        ORDER BY sequence_no
        """
    ).fetchall()
    assert [tuple(row) for row in stored] == [(1, 12), (2, None)]


@pytest.mark.parametrize("first_kind", ["failed", "skipped"])
def test_ordinary_item_result_continues_to_second_item(
    conn: sqlite3.Connection, first_kind: str
) -> None:
    _add_product(conn, 1)
    _add_product(conn, 2)
    prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    calls: list[int] = []

    def collector(*, product_id: int, verified_direct_url: str) -> dict:
        calls.append(product_id)
        if product_id == 1:
            return {
                "kind": first_kind,
                "observed_product_id": 1,
                "observed_at": RUN_NOW,
                "reason_code": "ordinary_known_blocker",
            }
        return _exact(product_id)

    summary = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )

    assert calls == [1, 2]
    assert summary[first_kind] == 1
    assert summary["completed_exact"] == 1
    assert summary["remaining"] == 0


@pytest.mark.parametrize(
    "reason_code",
    [
        "captcha",
        "risk_control",
        "anr",
        "unknown_page",
        "identity_unknown",
        "database_lock_error",
    ],
)
def test_hard_stop_never_calls_second_item(
    conn: sqlite3.Connection, reason_code: str
) -> None:
    _add_product(conn, 1)
    _add_product(conn, 2)
    prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    calls: list[int] = []

    def collector(*, product_id: int, verified_direct_url: str) -> dict:
        calls.append(product_id)
        return {
            "kind": "hard_stop",
            "observed_at": RUN_NOW,
            "reason_code": reason_code,
        }

    summary = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )

    assert calls == [1]
    assert summary["batch_status"] == "hard_stopped"
    assert summary["hard_stop_reason"] == reason_code
    assert summary["hard_stopped"] == 1
    assert summary["pending"] == 1


def test_identity_mismatch_hard_stops_before_second_item(
    conn: sqlite3.Connection,
) -> None:
    _add_product(conn, 1)
    _add_product(conn, 2)
    prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    calls: list[int] = []

    def collector(*, product_id: int, verified_direct_url: str) -> dict:
        calls.append(product_id)
        result = _exact(product_id)
        result["observed_product_id"] = 999
        return result

    summary = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )

    assert calls == [1]
    assert summary["hard_stop_reason"] == "identity_unknown"
    assert summary["remaining"] == 1


def test_completed_items_are_not_collected_twice(conn: sqlite3.Connection) -> None:
    _add_product(conn, 1)
    prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    calls = 0

    def collector(*, product_id: int, verified_direct_url: str) -> dict:
        nonlocal calls
        calls += 1
        return _exact(product_id)

    first = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )
    second = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )

    assert calls == 1
    assert first["processed_this_run"] == 1
    assert second["processed_this_run"] == second["collector_calls"] == 0
    assert second["completed_exact"] == 1


def test_expired_lease_is_recovered_before_resume(conn: sqlite3.Connection) -> None:
    _add_product(conn, 1)
    _add_product(conn, 2)
    prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    plan_id = conn.execute(
        "SELECT id FROM daily_sales_plans ORDER BY sequence_no LIMIT 1"
    ).fetchone()[0]
    claim_daily_sales_task(
        conn,
        plan_id=plan_id,
        owner="crashed-runner",
        now="2026-07-30T00:00:00+08:00",
        lease_seconds=60,
    )
    calls: list[int] = []

    def collector(*, product_id: int, verified_direct_url: str) -> dict:
        calls.append(product_id)
        return _exact(product_id)

    summary = run_prepared_daily_sales_cycle(
        conn,
        CYCLE,
        owner="resumed-runner",
        collector=collector,
        now=RUN_NOW,
        recovery_now=RUN_NOW,
    )

    assert summary["recovered_this_run"] == 1
    assert calls == [1, 2]
    assert summary["completed_exact"] == 2
    recovered = conn.execute(
        "SELECT recovery_count FROM daily_sales_plans WHERE id=?", (plan_id,)
    ).fetchone()[0]
    assert recovered == 1


def test_unexpected_collector_exception_is_failed_not_success_and_continues(
    conn: sqlite3.Connection,
) -> None:
    _add_product(conn, 1)
    _add_product(conn, 2)
    prepare_daily_sales_cycle(conn, CYCLE, created_at=RUN_NOW)
    calls: list[int] = []

    def collector(*, product_id: int, verified_direct_url: str) -> dict:
        calls.append(product_id)
        if product_id == 1:
            raise RuntimeError("fake collector crashed")
        return _exact(product_id)

    summary = run_prepared_daily_sales_cycle(
        conn, CYCLE, owner="runner", collector=collector, now=RUN_NOW
    )
    first = conn.execute(
        """
        SELECT status, reason_code, cumulative_sales_exact
        FROM daily_sales_plans WHERE product_id=1
        """
    ).fetchone()

    assert calls == [1, 2]
    assert tuple(first) == ("failed", "collector_exception", None)
    assert summary["failed"] == 1
    assert summary["completed_exact"] == 1
