import json
import sqlite3
import threading

from xhs_scout import db
from xhs_scout.config import Settings
from xhs_scout.db import connect, get_monitor_state, set_monitor_desired_state
from xhs_scout.scheduler import MonitorScheduler


def _settings_with_keywords(tmp_path, count=24):
    settings = Settings.load(tmp_path)
    config_path = settings.root / "config" / "keyword_portfolio.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "policy": {
                    "hourly_budget": count,
                    "per_round_budget": count,
                    "keyword_cooldown_hours": 24,
                    "core_share": 1.0,
                },
                "categories": [
                    {
                        "id": "offline-24-cycle",
                        "label": "Offline 24-cycle",
                        "layer": "core",
                        "priority": 100,
                        "seed_terms": [f"keyword-{index:02d}" for index in range(count)],
                        "modifiers": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return settings


def test_24_simulated_cycles_keep_one_keyword_budget_and_finish_paused(
    tmp_path, monkeypatch
):
    """Structural cycle coverage only; this is not evidence of 24 elapsed hours."""

    settings = _settings_with_keywords(tmp_path)
    rounds = []

    def fake_monitor_once(called_settings, *, limits):
        assert called_settings == settings
        assert limits.max_keywords == 1
        assert limits.max_products_per_keyword == 1
        with connect(settings.db_path) as conn:
            pending = conn.execute(
                "SELECT id, keyword FROM search_tasks WHERE status='pending' ORDER BY id"
            ).fetchall()
            assert len(pending) == 1
            rounds.append(pending[0]["keyword"])
            conn.execute(
                """
                UPDATE search_tasks
                SET status='completed', last_started_at='2026-01-01T00:00:00+00:00',
                    last_finished_at='2026-01-01T00:00:00+00:00',
                    updated_at='2026-01-01T00:00:00+00:00'
                WHERE id=?
                """,
                (pending[0]["id"],),
            )
        return {
            "run_id": f"offline-cycle-{len(rounds):02d}",
            "captured_products": 1,
            "blocked": None,
            "busy": False,
        }

    class TwentyFourCycleWake:
        def wait(self, timeout):
            assert timeout >= 60
            if len(rounds) < 24:
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
    scheduler._wake = TwentyFourCycleWake()
    scheduler._run()

    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        tasks = conn.execute(
            "SELECT keyword, status FROM search_tasks ORDER BY id"
        ).fetchall()

    assert len(rounds) == 24
    assert len(set(rounds)) == 24
    assert [(row["keyword"], row["status"]) for row in tasks] == [
        (keyword, "completed") for keyword in rounds
    ]
    assert state["desired_state"] == "paused"
    assert state["scheduler_running"] is False
    assert state["next_run_at"] is None


def test_second_sqlite_writer_waits_for_lock_then_commits(tmp_path, monkeypatch):
    db_path = tmp_path / "writer-contention.sqlite3"
    with connect(db_path):
        pass

    lock_conn = sqlite3.connect(db_path)
    lock_conn.execute("BEGIN IMMEDIATE")
    lock_conn.execute(
        """
        INSERT INTO search_tasks(keyword, source, created_at, updated_at)
        VALUES ('lock-holder', 'test', '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00')
        """
    )

    real_connect = sqlite3.connect
    writer_connected = threading.Event()
    writer_finished = threading.Event()
    errors = []

    def observed_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        writer_connected.set()
        return conn

    def second_writer():
        try:
            with connect(db_path) as conn:
                db.enqueue(conn, ["second-writer"], source="test")
        except Exception as exc:  # pragma: no cover - assertion reports the exception
            errors.append(exc)
        finally:
            writer_finished.set()

    monkeypatch.setattr(db.sqlite3, "connect", observed_connect)
    worker = threading.Thread(target=second_writer)
    worker.start()
    assert writer_connected.wait(timeout=2)
    assert not writer_finished.wait(timeout=0.1)

    lock_conn.commit()
    lock_conn.close()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert errors == []
    with connect(db_path) as conn:
        keywords = {
            row["keyword"] for row in conn.execute("SELECT keyword FROM search_tasks")
        }
    assert keywords == {"lock-holder", "second-writer"}
