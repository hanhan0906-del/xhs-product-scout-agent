import json
from datetime import datetime

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    set_monitor_desired_state,
)
from xhs_scout.insights import ensure_portfolio_queue
from xhs_scout.monitor import (
    MonitorBlocked,
    MonitorLimits,
    _requeue_due_keywords,
    monitor_once,
)
from xhs_scout.run_control import current_monitor_lease
from xhs_scout.scheduler import MonitorScheduler


def _settings_with_portfolio(tmp_path, keywords):
    settings = Settings.load(tmp_path)
    (settings.root / "config" / "keyword_portfolio.json").write_text(
        json.dumps(
            {
                "version": 1,
                "policy": {
                    "hourly_budget": 10,
                    "per_round_budget": 10,
                    "keyword_cooldown_hours": 24,
                    "core_share": 1.0,
                },
                "categories": [
                    {
                        "id": "soak",
                        "label": "Soak",
                        "layer": "core",
                        "priority": 100,
                        "seed_terms": list(keywords),
                        "modifiers": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return settings


def _fake_report(settings, limit=20):
    return {
        "report_path": str(settings.reports_dir / "offline-soak.md"),
        "count": 0,
        "limit": limit,
    }


def test_scheduler_multiple_rounds_keep_one_by_one_limits_and_pause_cleanly(
    tmp_path, monkeypatch
):
    settings = _settings_with_portfolio(tmp_path, ("alpha", "beta", "gamma"))
    rounds = []

    def fake_monitor_once(called_settings, *, limits):
        assert called_settings == settings
        assert limits.max_keywords == 1
        assert limits.max_products_per_keyword == 1
        assert limits.requeue_due_keywords is False
        with connect(settings.db_path) as conn:
            pending = conn.execute(
                "SELECT id, keyword FROM search_tasks WHERE status='pending' ORDER BY id"
            ).fetchall()
            assert len(pending) == 1
            rounds.append(pending[0]["keyword"])
            conn.execute(
                """
                UPDATE search_tasks
                SET status='completed', last_started_at='2020-01-01T00:00:00+00:00',
                    last_finished_at='2020-01-01T00:00:00+00:00',
                    updated_at='2020-01-01T00:00:00+00:00'
                WHERE id=?
                """,
                (pending[0]["id"],),
            )
        return {
            "run_id": f"offline-{len(rounds)}",
            "captured_products": 1,
            "blocked": None,
            "busy": False,
        }

    class TwoRoundWake:
        def wait(self, timeout):
            assert timeout >= 60
            if len(rounds) == 1:
                return False
            with connect(settings.db_path) as conn:
                set_monitor_desired_state(conn, "paused")
            return True

        def clear(self):
            pass

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fake_monitor_once)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(settings, interval_seconds=60)
    scheduler._wake = TwoRoundWake()
    scheduler._run()

    with connect(settings.db_path) as conn:
        assert len(rounds) == 2
        assert len(set(rounds)) == 2
        assert set(rounds).issubset({"alpha", "beta", "gamma"})
        assert conn.execute("SELECT COUNT(*) FROM search_tasks").fetchone()[0] == 2
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["scheduler_running"] is False
        assert state["next_run_at"] is None


def test_repeated_failed_rounds_back_off_exhaust_and_release_every_lease(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
    )
    device_opens = []

    monkeypatch.setattr(
        "xhs_scout.monitor._device",
        lambda called_settings: device_opens.append(called_settings) or object(),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *args, **kwargs: {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        },
    )
    monkeypatch.setattr("xhs_scout.monitor.generate_candidate_report", _fake_report)

    with connect(settings.db_path) as conn:
        enqueue(conn, ["alpha"], source="soak")
        set_monitor_desired_state(conn, "running")

    cooldowns = []
    for expected_attempt in (1, 2, 3):
        output = monitor_once(settings, limits=limits)
        assert output["processed_tasks"] == 0
        assert len(output["skipped"]) == 1
        assert output["skipped"][0]["reason"] == "no product card found"

        with connect(settings.db_path) as conn:
            row = conn.execute(
                """
                SELECT status, attempts, next_run_at, last_finished_at,
                       run_owner, run_lease_expires_at
                FROM search_tasks WHERE keyword='alpha'
                """
            ).fetchone()
            assert row["attempts"] == expected_attempt
            assert row["run_owner"] is None
            assert row["run_lease_expires_at"] is None
            assert current_monitor_lease(conn) is None
            if expected_attempt < 3:
                cooldowns.append(
                    int(
                        (
                            datetime.fromisoformat(row["next_run_at"])
                            - datetime.fromisoformat(row["last_finished_at"])
                        ).total_seconds()
                    )
                )
                conn.execute(
                    "UPDATE search_tasks SET next_run_at=NULL WHERE keyword='alpha'"
                )
            else:
                assert row["status"] == "needs_manual_detail"
                assert row["next_run_at"] is None

    final_output = monitor_once(settings, limits=limits)
    assert final_output["skipped"] == ["no pending task"]
    assert cooldowns == [300, 600]
    assert len(device_opens) == 3
    with connect(settings.db_path) as conn:
        assert current_monitor_lease(conn) is None


def test_risk_stop_in_one_round_prevents_device_open_in_following_round(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
    )
    device_opens = []

    monkeypatch.setattr(
        "xhs_scout.monitor._device",
        lambda called_settings: device_opens.append(called_settings) or object(),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MonitorBlocked("risk stop: captcha detected", hard=True)
        ),
    )
    monkeypatch.setattr("xhs_scout.monitor.generate_candidate_report", _fake_report)

    with connect(settings.db_path) as conn:
        enqueue(conn, ["alpha"], source="soak")
        set_monitor_desired_state(conn, "running")

    first = monitor_once(settings, limits=limits)
    assert first["blocked"] == "risk stop: captcha detected"
    assert len(device_opens) == 1

    second = monitor_once(settings, limits=limits)
    assert second["blocked"] == "risk stop: captcha detected"
    assert second["skipped"] == ["risk stop requires explicit resume"]
    assert len(device_opens) == 1
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == "risk stop: captcha detected"
        assert current_monitor_lease(conn) is None


def test_portfolio_seed_blocks_same_keyword_recurrence_seed(tmp_path):
    settings = _settings_with_portfolio(tmp_path, ("alpha",))
    old = "2020-01-01T00:00:00+00:00"

    with connect(settings.db_path) as conn:
        enqueue(conn, ["alpha"], source="historical")
        conn.execute(
            """
            UPDATE search_tasks
            SET status='completed', last_started_at=?, last_finished_at=?, updated_at=?
            WHERE keyword='alpha'
            """,
            (old, old, old),
        )

        portfolio = ensure_portfolio_queue(conn, settings, max_keywords=1)
        recurring = _requeue_due_keywords(
            settings,
            limit=1,
            interval_hours=0,
        )
        rows = conn.execute(
            "SELECT status, source FROM search_tasks WHERE keyword='alpha' ORDER BY id"
        ).fetchall()

        assert portfolio["queued"] == 1
        assert recurring == 0
        assert [(row["status"], row["source"]) for row in rows] == [
            ("completed", "historical"),
            ("pending", "keyword_portfolio:core:soak"),
        ]
        assert MonitorScheduler(settings).limits.requeue_due_keywords is False
