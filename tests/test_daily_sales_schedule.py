from datetime import datetime

from xhs_scout.config import Settings
from xhs_scout.daily_sales_schedule import (
    midnight_cycle_date,
    run_due_daily_sales_cycle,
)
from xhs_scout.db import (
    connect,
    dashboard_stats,
    get_monitor_state,
    set_product_sales_follow,
)
from xhs_scout.db import set_monitor_desired_state
from xhs_scout.scheduler import ContinuousMonitorScheduler


def _setup_followed_product(settings):
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO products(
                title, shop_name, share_url, direct_url, fingerprint,
                first_seen_at, last_seen_at
            ) VALUES (
                '普通人社会化成长指南', '测试店铺',
                'https://xhslink.com/m/abc123',
                'xhsdiscover://page/goods/abc123',
                'midnight-product',
                '2026-07-29T00:00:00+08:00', '2026-07-29T00:00:00+08:00'
            )
            """
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, cumulative_sales_display,
                cumulative_sales_exact, cumulative_sales_min, raw_signals_json
            ) VALUES (?, '2026-07-29T00:05:00+08:00', 'test', '100', 100, 100, '{}')
            """,
            (product_id,),
        )
        set_product_sales_follow(conn, product_id=product_id, enabled=True)
        return product_id


def test_midnight_cycle_date_is_only_first_fifteen_minutes():
    assert midnight_cycle_date(datetime.fromisoformat("2026-07-30T00:00:00+08:00")) == "2026-07-30"
    assert midnight_cycle_date(datetime.fromisoformat("2026-07-30T00:15:59+08:00")) == "2026-07-30"
    assert midnight_cycle_date(datetime.fromisoformat("2026-07-30T00:16:00+08:00")) is None


def test_due_cycle_uses_followed_snapshot_and_persists_delta(tmp_path):
    settings = Settings.load(tmp_path)
    product_id = _setup_followed_product(settings)
    now = datetime.fromisoformat("2026-07-30T00:05:00+08:00")

    output = run_due_daily_sales_cycle(
        settings,
        now=now,
        collector_factory=lambda: (
            lambda **_kwargs: {
                "kind": "exact",
                "observed_product_id": product_id,
                "observed_at": now.isoformat(),
                "cumulative_sales_exact": 125,
                "cumulative_sales_display": "125",
            }
        ),
        owner="offline-midnight",
    )

    assert output["due"] is True
    assert output["summary"]["completed_exact"] == 1
    with connect(settings.db_path) as conn:
        plan = conn.execute(
            "SELECT status, daily_sales_delta FROM daily_sales_plans"
        ).fetchone()
        state = get_monitor_state(conn)
        recent = dashboard_stats(conn)["recent"][0]
    assert plan["status"] == "completed_exact"
    assert plan["daily_sales_delta"] == 25
    assert recent["cumulative_sales_display"] == "125"
    assert recent["daily_sales_delta"] == 25
    assert state["last_daily_sales_output"]["cycle_date"] == "2026-07-30"


def test_daily_hard_stop_pauses_discovery_scheduler(tmp_path):
    settings = Settings.load(tmp_path)
    product_id = _setup_followed_product(settings)
    now = datetime.fromisoformat("2026-07-30T00:05:00+08:00")

    run_due_daily_sales_cycle(
        settings,
        now=now,
        collector_factory=lambda: (
            lambda **_kwargs: {
                "kind": "hard_stop",
                "observed_at": now.isoformat(),
                "reason_code": "captcha",
            }
        ),
        owner="offline-midnight",
    )

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
    assert state["desired_state"] == "paused"
    assert state["risk_stop_reason"] == "daily sales tracking stopped: captcha"


def test_continuous_scheduler_runs_midnight_sales_before_discovery(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    product_id = _setup_followed_product(settings)
    now = datetime.fromisoformat("2026-07-30T00:05:00+08:00")

    def fail_if_discovery_runs(*_args, **_kwargs):
        raise AssertionError("daily hard stop must prevent discovery")

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fail_if_discovery_runs)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = ContinuousMonitorScheduler(
        settings,
        now_provider=lambda: now,
        daily_sales_collector_factory=lambda: (
            lambda **_kwargs: {
                "kind": "hard_stop",
                "observed_at": now.isoformat(),
                "reason_code": "captcha",
                "observed_product_id": product_id,
            }
        ),
    )
    scheduler._run()

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
    assert state["scheduler_running"] is False
    assert state["risk_stop_reason"] == "daily sales tracking stopped: captcha"
