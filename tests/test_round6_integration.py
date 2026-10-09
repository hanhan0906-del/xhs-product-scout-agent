from __future__ import annotations

import json
from pathlib import Path

import xhs_scout.scheduler as scheduler_module
import xhs_scout.web as web_module
from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    set_monitor_desired_state,
    set_monitor_state,
    utcnow,
)
from xhs_scout.keyword_discovery import discover_keyword_candidates
from xhs_scout.keyword_portfolio import build_keyword_candidates, build_rotation_plan
from xhs_scout.monitor import MonitorLimits, monitor_once
from xhs_scout.remediation import plan_remediation
from xhs_scout.reports import generate_candidate_report
from xhs_scout.run_control import (
    RetryPolicy,
    acquire_monitor_lease,
    check_lease_safety,
    current_monitor_lease,
    renew_lease_safety,
    reserve_next_runnable_task,
)
from xhs_scout.scheduler import MonitorScheduler


NOW = "2026-07-29T12:00:00+08:00"


def _route(settings: Settings, path: str):
    return next(
        route.endpoint
        for route in web_module.create_app(settings).routes
        if getattr(route, "path", None) == path
    )


def _task_snapshot(settings: Settings) -> list[tuple]:
    with connect(settings.db_path) as conn:
        columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(search_tasks)").fetchall()
        ]
        rows = conn.execute("SELECT * FROM search_tasks ORDER BY id").fetchall()
    return [tuple(row[column] for column in columns) for row in rows]


def _seed_readonly_contract(settings: Settings) -> int:
    with connect(settings.db_path) as conn:
        enqueue(conn, ["只读哨兵任务"], source="round6-contract")
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, shop_name, price, is_virtual,
                virtual_confidence, first_seen_at, last_seen_at
            ) VALUES (
                'round6-review', '三年级暑假预习资料电子版', '学习资料店',
                19.9, 1, 1, ?, ?
            )
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, screenshot_path, raw_text,
                sales_30d_min, raw_signals_json
            ) VALUES (?, ?, 'round6-contract', 'round6.png', '公开页面文本', 700, ?)
            """,
            (
                product_id,
                now,
                json.dumps(
                    {
                        "trend_labels": ["暑假预习资料"],
                        "metrics_strip": {"frames": [{"path": "frame-1.png"}]},
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score, reasons_json, status
            ) VALUES (?, ?, 'B', 61.0, '["待人工确认来源"]', 'needs_review')
            """,
            (product_id, now),
        )
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                product_id, observation_id, source_keyword, result_rank,
                search_probe_dir, recorded_at, valid
            ) VALUES (?, ?, '暑假预习资料', 1, 'old-valid-probe', ?, 1)
            """,
            (product_id, observation_id, now),
        )
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                product_id, observation_id, source_keyword, result_rank,
                search_probe_dir, recorded_at, valid, invalid_reason
            ) VALUES (
                ?, ?, '错误关键词', 2, 'latest-invalid-probe',
                '2026-07-29T12:01:00+08:00', 0, 'keyword_mismatch'
            )
            """,
            (product_id, observation_id),
        )
    return product_id


def test_round6_readonly_modules_share_contract_without_queue_or_config_writes(
    tmp_path,
):
    settings = Settings.load(tmp_path)
    portfolio_path = settings.root / "config" / "keyword_portfolio.json"
    portfolio_config = {
        "version": 1,
        "policy": {
            "hourly_budget": 2,
            "per_round_budget": 2,
            "max_total_candidates": 10,
            "min_explore_per_round": 1,
        },
        "categories": [
            {
                "id": "existing",
                "label": "既有词",
                "layer": "core",
                "priority": 80,
                "seed_terms": ["现有资料"],
                "modifiers": [],
                "explore_terms": ["探索资料"],
            }
        ],
    }
    portfolio_path.write_text(
        json.dumps(portfolio_config, ensure_ascii=False),
        encoding="utf-8",
    )
    product_id = _seed_readonly_contract(settings)
    tasks_before = _task_snapshot(settings)
    config_before = portfolio_path.read_bytes()

    report_path = tmp_path / "round6-report.md"
    report_result = generate_candidate_report(
        settings,
        output_path=report_path,
        limit=10,
    )
    report = report_path.read_text(encoding="utf-8")
    assert report_result["candidate_count"] == 1
    assert report_result["needs_review_count"] == 1
    assert "当前评估状态：人工复核（needs_review）" in report
    assert "已失效，不作为当前归属（keyword_mismatch）" in report
    assert "latest-invalid-probe" in report
    assert "old-valid-probe" not in report

    portfolio_candidates = build_keyword_candidates(portfolio_config)
    rotation = build_rotation_plan(portfolio_config, now=NOW)
    assert {item.layer for item in portfolio_candidates} == {"core", "explore"}
    assert rotation["scope"]["production_queue_write"] is False
    assert len(rotation["selected"]) == 2

    discovery = discover_keyword_candidates(
        products=[
            {
                "id": product_id,
                "title": "三年级暑假预习资料电子版",
                "source_keyword": "暑假预习资料",
                "trend_labels": ["暑假预习资料"],
            }
        ],
        successful_searches=[
            {
                "id": "round6-search",
                "product_id": product_id,
                "keyword": "暑假预习资料",
            }
        ],
        existing_keywords=[item.to_dict() for item in portfolio_candidates],
    )
    suggestion = next(
        item
        for item in discovery["candidates"]
        if item["normalized"] == "暑假预习资料"
    )
    assert discovery["scope"]["production_queue_write"] is False
    assert suggestion["review_status"] == "pending_review"
    assert suggestion["suggested_layer"] == "core"

    assert web_module.discover_keyword_candidates is discover_keyword_candidates
    api_result = _route(settings, "/api/keyword-suggestions")(limit=10)
    api_suggestion = next(
        item
        for item in api_result["candidates"]
        if item["normalized"] == "暑假预习资料"
    )
    assert api_result["scope"]["database_access"] == "read_only"
    assert api_result["scope"]["production_queue_write"] is False
    assert api_result["scope"]["keyword_config_write"] is False
    assert api_suggestion["review_status"] == "pending_review"

    remediation = plan_remediation(
        [
            {
                "product_id": product_id,
                "status": "needs_review",
                "score": 61,
                "has_valid_search_attribution": 1,
                "latest_search_attribution_valid": 0,
                "has_supported_product_link": 0,
                "has_metrics_strip": 1,
                "has_note_evidence": 0,
                "has_profile_evidence": 0,
            },
            {
                "product_id": product_id + 100,
                "status": "needs_review",
                "score": 50,
                "has_valid_search_attribution": 1,
                "latest_search_attribution_valid": 1,
                "has_supported_product_link": 1,
                "has_metrics_strip": 0,
                "has_note_evidence": 0,
                "has_profile_evidence": 0,
            },
        ],
        now=NOW,
    )
    assert remediation.isolated[0].product_id == product_id
    assert remediation.isolated[0].code == "search_attribution_quarantine"
    assert remediation.batches[0].stage == "metrics"
    assert remediation.batches[0].items[0].product_id == product_id + 100

    assert _task_snapshot(settings) == tasks_before
    assert portfolio_path.read_bytes() == config_before


def test_keyword_review_does_not_revive_search_invalidated_by_latest_evidence(
    tmp_path,
):
    settings = Settings.load(tmp_path)
    _seed_readonly_contract(settings)

    result = _route(settings, "/api/keyword-suggestions")(limit=10)
    suggestion = next(
        item
        for item in result["candidates"]
        if item["normalized"] == "暑假预习资料"
    )

    assert result["source_stats"]["valid_search_sources_read"] == 0
    assert suggestion["support"]["source_types"] == ["trend_label"]
    assert suggestion["suggested_layer"] == "explore"


class _ImmediateWake:
    def __init__(self):
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)
        return False

    def clear(self):
        pass


def test_scheduler_recovery_preserves_lease_fail_closed_contract(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    owner = "round6-owner"
    policy = RetryPolicy(task_lease_seconds=120, base_cooldown_seconds=1)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["round6 recovery"], source="round6-contract")
        task_id = conn.execute(
            "SELECT id FROM search_tasks WHERE keyword='round6 recovery'"
        ).fetchone()[0]
        acquire_monitor_lease(conn, owner=owner, ttl_seconds=120, now=NOW)
        reserved = reserve_next_runnable_task(
            conn,
            owner=owner,
            policy=policy,
            now=NOW,
        )
        assert reserved["id"] == task_id
        renewed = renew_lease_safety(
            conn,
            task_id=task_id,
            owner=owner,
            monitor_ttl_seconds=120,
            policy=policy,
            now="2026-07-29T12:00:30+08:00",
        )
        assert renewed.safe_to_continue is True
        assert renewed.renewed is True
        set_monitor_state(conn, "last_run_id", owner)
        set_monitor_desired_state(conn, "running")

    assert scheduler_module.monitor_once is monitor_once
    assert MonitorLimits().max_keywords == 1
    calls = []

    monkeypatch.setattr(
        scheduler_module,
        "ensure_portfolio_queue",
        lambda *args, **kwargs: {"queued": 0},
    )

    def flaky_monitor(*args, **kwargs):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("round6 injected scheduler failure")
        with connect(settings.db_path) as conn:
            task = conn.execute(
                """
                SELECT status, run_owner, run_lease_expires_at
                FROM search_tasks WHERE id=?
                """,
                (task_id,),
            ).fetchone()
            assert task["status"] == "pending"
            assert task["run_owner"] is None
            assert task["run_lease_expires_at"] is None
            assert current_monitor_lease(conn) is None
            safety = check_lease_safety(
                conn,
                task_id=task_id,
                owner=owner,
                now="2026-07-29T12:00:31+08:00",
            )
            assert safety.safe_to_continue is False
            assert safety.reason == "monitor_lease_missing"
            set_monitor_desired_state(conn, "paused")
        return {
            "run_id": "round6-recovered",
            "captured_products": 0,
            "blocked": "round6 contract complete",
            "busy": False,
        }

    monkeypatch.setattr(scheduler_module, "monitor_once", flaky_monitor)
    scheduler = MonitorScheduler(
        settings,
        recovery_initial_seconds=1,
        recovery_max_seconds=2,
        max_consecutive_failures=3,
    )
    wake = _ImmediateWake()
    scheduler._wake = wake
    scheduler._run()

    assert calls == [1, 2]
    assert wake.waits == [1]
    snapshot = scheduler.snapshot()
    assert snapshot["worker_state"] == "stopped"
    assert snapshot["recovery_count"] == 1
    assert snapshot["consecutive_failures"] == 0
    assert snapshot["last_exception"]["run_id"] == owner
    assert len(snapshot["last_exception"]["recovered_tasks"]) == 1
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
    assert state["desired_state"] == "paused"
    assert state["scheduler_running"] is False
