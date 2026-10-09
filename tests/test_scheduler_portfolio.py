import json

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    set_monitor_desired_state,
    set_monitor_state,
    utcnow,
)
from xhs_scout.insights import ensure_portfolio_queue
from xhs_scout.scheduler import MonitorScheduler


def _settings_with_portfolio(tmp_path, *, keywords=("alpha course",)):
    settings = Settings.load(tmp_path)
    config_dir = settings.root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "keyword_portfolio.json").write_text(
        json.dumps(
            {
                "version": 1,
                "policy": {
                    "hourly_budget": 6,
                    "per_round_budget": 6,
                    "keyword_cooldown_hours": 24,
                    "core_share": 1.0,
                },
                "categories": [
                    {
                        "id": "offline",
                        "label": "Offline",
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


def _task_keywords(conn):
    return [
        row["keyword"]
        for row in conn.execute("SELECT keyword FROM search_tasks ORDER BY id")
    ]


def test_runnable_task_prevents_portfolio_refill(tmp_path):
    settings = _settings_with_portfolio(tmp_path, keywords=("alpha course", "beta course"))

    with connect(settings.db_path) as conn:
        enqueue(conn, ["manual task"], source="test")
        result = ensure_portfolio_queue(conn, settings, max_keywords=2)

        assert result["queued"] == 0
        assert result["queue_reason"] == "runnable_tasks_exist"
        assert _task_keywords(conn) == ["manual task"]


def test_empty_queue_refills_only_one_keyword_by_scheduler_limit(tmp_path):
    settings = _settings_with_portfolio(tmp_path, keywords=("alpha course", "beta course"))

    with connect(settings.db_path) as conn:
        result = ensure_portfolio_queue(conn, settings, max_keywords=1)

        assert result["queued"] == 1
        assert _task_keywords(conn) == ["alpha course"]


def test_recent_completed_keyword_stays_under_24h_cooldown(tmp_path):
    settings = _settings_with_portfolio(tmp_path, keywords=("alpha course",))

    with connect(settings.db_path) as conn:
        enqueue(conn, ["alpha course"], source="test")
        conn.execute(
            """
            UPDATE search_tasks
            SET status='completed', last_started_at=?, last_finished_at=?, updated_at=?
            WHERE keyword='alpha course'
            """,
            (utcnow(), utcnow(), utcnow()),
        )

        result = ensure_portfolio_queue(conn, settings, max_keywords=1)

        assert result["queued"] == 0
        assert result["queue_reason"] == "no_eligible_keyword"
        assert _task_keywords(conn) == ["alpha course"]
        assert result["selected"] == []
        assert result["deferred"][0]["keyword"] == "alpha course"
        assert result["deferred"][0]["reason"] == "keyword_cooldown"


def test_risk_stop_blocks_portfolio_refill(tmp_path):
    settings = _settings_with_portfolio(tmp_path, keywords=("alpha course",))

    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", "captcha detected")
        result = ensure_portfolio_queue(conn, settings, max_keywords=1)

        assert result["queued"] == 0
        assert result["queue_reason"] == "no_eligible_keyword"
        assert result["paused"] is True
        assert result["pause"]["severity"] == "risk"
        assert _task_keywords(conn) == []


def test_scheduler_output_records_portfolio_queued(tmp_path, monkeypatch):
    settings = _settings_with_portfolio(tmp_path, keywords=("alpha course",))
    calls = []

    def fake_monitor_once(called_settings, *, limits):
        calls.append((called_settings, limits))
        return {
            "run_id": "offline-run",
            "captured_products": 0,
            "blocked": "offline stop",
            "busy": False,
        }

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fake_monitor_once)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    MonitorScheduler(settings)._run()

    assert len(calls) == 1
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["last_scheduler_output"] == {
            "run_id": "offline-run",
            "captured_products": 0,
            "blocked": "offline stop",
            "busy": False,
            "portfolio_queued": 1,
        }
        assert state["scheduler_running"] is False
        assert state["next_run_at"] is None
        assert _task_keywords(conn) == ["alpha course"]


def test_paused_scheduler_wake_does_not_create_task(tmp_path, monkeypatch):
    settings = _settings_with_portfolio(tmp_path, keywords=("alpha course",))

    def fail_if_monitor_starts(*args, **kwargs):
        raise AssertionError("paused scheduler must not start a monitor round")

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fail_if_monitor_starts)
    scheduler = MonitorScheduler(settings)
    scheduler.wake()

    scheduler._run()

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["scheduler_running"] is False
        assert state["next_run_at"] is None
        assert _task_keywords(conn) == []


def test_pause_after_wake_stops_before_second_portfolio_refill(tmp_path, monkeypatch):
    settings = _settings_with_portfolio(tmp_path, keywords=("alpha course", "beta course"))
    calls = []

    def fake_monitor_once(called_settings, *, limits):
        calls.append((called_settings, limits))
        return {
            "run_id": f"offline-run-{len(calls)}",
            "captured_products": 0,
            "blocked": None,
            "busy": False,
        }

    class PauseWake:
        def wait(self, timeout):
            with connect(settings.db_path) as conn:
                set_monitor_desired_state(conn, "paused")
            return True

        def clear(self):
            pass

    monkeypatch.setattr("xhs_scout.scheduler.monitor_once", fake_monitor_once)
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    scheduler = MonitorScheduler(settings)
    scheduler._wake = PauseWake()
    scheduler._run()

    with connect(settings.db_path) as conn:
        assert len(calls) == 1
        assert _task_keywords(conn) == ["alpha course"]
        assert get_monitor_state(conn)["next_run_at"] is None
