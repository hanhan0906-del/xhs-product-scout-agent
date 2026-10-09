from xhs_scout.config import Settings
from xhs_scout.db import connect, enqueue, utcnow
from xhs_scout.insights import (
    digest_snapshot,
    ensure_portfolio_queue,
    portfolio_snapshot,
    quality_snapshot,
)


def test_empty_insight_snapshots_are_json_ready(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        quality = quality_snapshot(conn, settings)
        digest = digest_snapshot(conn)
        portfolio = portfolio_snapshot(conn, settings)

    assert quality["summary"]["issue_count"] == 0
    assert digest["stats"]["period"] == "daily"
    assert isinstance(digest["window"]["start_at"], str)
    assert portfolio["selected"] == []


def test_portfolio_queue_does_not_compete_with_existing_task(tmp_path):
    settings = Settings.load(tmp_path)
    config_dir = settings.root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "keyword_portfolio.json").write_text(
        """
        {
          "version": 1,
          "policy": {"keyword_cooldown_hours": 24},
          "categories": [{
            "id": "test",
            "label": "测试",
            "layer": "core",
            "priority": 100,
            "seed_terms": ["测试资料"],
            "modifiers": []
          }]
        }
        """,
        encoding="utf-8",
    )
    with connect(settings.db_path) as conn:
        enqueue(conn, ["已有任务"])
        result = ensure_portfolio_queue(conn, settings)
        keywords = [
            row["keyword"]
            for row in conn.execute("SELECT keyword FROM search_tasks ORDER BY id")
        ]

    assert result["queued"] == 0
    assert result["queue_reason"] == "runnable_tasks_exist"
    assert keywords == ["已有任务"]


def test_portfolio_queue_seeds_one_keyword_when_queue_is_empty(tmp_path):
    settings = Settings.load(tmp_path)
    config_dir = settings.root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "keyword_portfolio.json").write_text(
        """
        {
          "version": 1,
          "policy": {"keyword_cooldown_hours": 24},
          "categories": [{
            "id": "test",
            "label": "测试",
            "layer": "core",
            "priority": 100,
            "seed_terms": ["测试资料"],
            "modifiers": []
          }]
        }
        """,
        encoding="utf-8",
    )
    with connect(settings.db_path) as conn:
        result = ensure_portfolio_queue(conn, settings)
        row = conn.execute(
            "SELECT keyword, source, status, created_at FROM search_tasks"
        ).fetchone()

    assert result["queued"] == 1
    assert row["keyword"] == "测试资料"
    assert row["source"] == "keyword_portfolio:core:test"
    assert row["status"] == "pending"
    assert row["created_at"] <= utcnow()
