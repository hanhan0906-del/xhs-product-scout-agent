from dataclasses import replace
from datetime import datetime, timezone

import pytest

from xhs_scout.approved_keyword_enqueue import (
    apply_approved_keyword_queue_plan,
    discovery_root_source_fingerprint,
    plan_approved_keyword_enqueue,
    plan_approved_root_keyword_enqueue,
)
from xhs_scout.db import connect, set_monitor_desired_state
from xhs_scout.keyword_combinations import (
    CombinationAnalysis,
    CombinationCandidate,
)
from xhs_scout.product_keyword_terms import ProductKeywordError


NOW = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)


def _analysis():
    candidates = tuple(
        CombinationCandidate(
            phrase=phrase,
            candidate_stage="sample",
            product_count=2,
            root_count=2,
            shop_count=2,
            context_count=2,
            support=(),
            risk_flags=(),
            review_status="pending_review",
            source_fingerprint=f"fingerprint-{index}",
        )
        for index, phrase in enumerate(("运营复盘模板", "年度计划表"), 1)
    )
    return CombinationAnalysis(
        generation_stage="sample",
        product_count=30,
        root_count=10,
        domain_scene_count=3,
        shop_count=20,
        context_count=30,
        gates={
            "all_records_traceable": True,
            "small_products": True,
            "small_roots": True,
            "small_domain_or_scene": True,
            "stable_products": False,
            "stable_roots": False,
        },
        candidates=candidates,
        dataset_fingerprint="dataset-current",
    )


def _manifest(analysis=None):
    analysis = analysis or _analysis()
    return {
        "version": 1,
        "dataset_fingerprint": analysis.dataset_fingerprint,
        "scope": {
            "human_review_only": True,
            "writes_queue": False,
            "search_execution": False,
            "monitor_authorization": False,
            "soak_authorization": False,
        },
        "entries": [
            {
                "phrase": item.phrase,
                "status": "approved" if index == 0 else "rejected",
                "source_fingerprint": item.source_fingerprint,
            }
            for index, item in enumerate(analysis.candidates)
        ],
    }


def test_stale_dataset_and_candidate_evidence_fail_closed(tmp_path):
    analysis = _analysis()
    with connect(tmp_path / "state.sqlite3") as conn:
        stale = _manifest(analysis)
        stale["dataset_fingerprint"] = "old"
        with pytest.raises(ProductKeywordError, match="dataset fingerprint"):
            plan_approved_keyword_enqueue(
                conn,
                approval_manifest=stale,
                analysis=analysis,
                now=NOW,
            )
        stale = _manifest(analysis)
        stale["entries"][0]["source_fingerprint"] = "old"
        with pytest.raises(ProductKeywordError, match="evidence is stale"):
            plan_approved_keyword_enqueue(
                conn,
                approval_manifest=stale,
                analysis=analysis,
                now=NOW,
            )


def test_dry_run_never_writes_queue(tmp_path):
    analysis = _analysis()
    with connect(tmp_path / "state.sqlite3") as conn:
        plan = plan_approved_keyword_enqueue(
            conn,
            approval_manifest=_manifest(analysis),
            analysis=analysis,
            now=NOW,
        )
        result = apply_approved_keyword_queue_plan(conn, plan)
        assert result["execution_status"] == "not_executed"
        assert result["scope"]["writes_queue"] is False
        assert result["selected"] == ["运营复盘模板"]
        assert conn.execute("SELECT COUNT(*) FROM search_tasks").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM keyword_queue_audits"
        ).fetchone()[0] == 0


def test_active_duplicate_and_recent_history_are_deferred(tmp_path):
    analysis = _analysis()
    manifest = _manifest(analysis)
    manifest["entries"][1]["status"] = "approved"
    with connect(tmp_path / "state.sqlite3") as conn:
        conn.execute(
            """
            INSERT INTO search_tasks(
                keyword, source, status, created_at, updated_at
            ) VALUES ('运营复盘模板', 'test', 'pending', ?, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        conn.execute(
            """
            INSERT INTO search_tasks(
                keyword, source, status, created_at, updated_at
            ) VALUES ('年度计划表', 'test', 'completed', ?, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        plan = plan_approved_keyword_enqueue(
            conn,
            approval_manifest=manifest,
            analysis=analysis,
            now=NOW,
        )
        assert plan.selected == ()
        assert {item["reason"] for item in plan.deferred} == {
            "active_duplicate",
            "keyword_cooldown",
        }


def test_execute_requires_exact_plan_hash_and_paused_monitor(tmp_path):
    analysis = _analysis()
    with connect(tmp_path / "state.sqlite3") as conn:
        plan = plan_approved_keyword_enqueue(
            conn,
            approval_manifest=_manifest(analysis),
            analysis=analysis,
            now=NOW,
        )
        with pytest.raises(ProductKeywordError, match="exact plan hash"):
            apply_approved_keyword_queue_plan(conn, plan, execute=True)
        set_monitor_desired_state(conn, "running")
        with pytest.raises(ProductKeywordError, match="monitor must be paused"):
            apply_approved_keyword_queue_plan(
                conn,
                plan,
                execute=True,
                confirm_plan_hash=plan.plan_hash,
            )


def test_confirmed_execute_is_atomic_audited_and_one_shot(tmp_path):
    analysis = _analysis()
    with connect(tmp_path / "state.sqlite3") as conn:
        set_monitor_desired_state(conn, "paused")
        plan = plan_approved_keyword_enqueue(
            conn,
            approval_manifest=_manifest(analysis),
            analysis=analysis,
            now=NOW,
        )
        result = apply_approved_keyword_queue_plan(
            conn,
            plan,
            execute=True,
            confirm_plan_hash=plan.plan_hash,
        )
        assert result["execution_status"] == "executed"
        assert result["inserted_count"] == 1
        row = conn.execute(
            "SELECT keyword, source, status FROM search_tasks"
        ).fetchone()
        assert tuple(row) == (
            "运营复盘模板",
            "approved_discovery_keyword",
            "pending",
        )
        assert conn.execute(
            "SELECT inserted_count FROM keyword_queue_audits"
        ).fetchone()[0] == 1
        with pytest.raises(ProductKeywordError, match="already been executed"):
            apply_approved_keyword_queue_plan(
                conn,
                plan,
                execute=True,
                confirm_plan_hash=plan.plan_hash,
            )


def test_not_ready_analysis_and_unsafe_scope_never_plan(tmp_path):
    analysis = _analysis()
    with connect(tmp_path / "state.sqlite3") as conn:
        with pytest.raises(ProductKeywordError, match="sample gate"):
            plan_approved_keyword_enqueue(
                conn,
                approval_manifest=_manifest(analysis),
                analysis=replace(analysis, generation_stage="not_ready"),
                now=NOW,
            )
        manifest = _manifest(analysis)
        manifest["scope"]["writes_queue"] = True
        with pytest.raises(ProductKeywordError, match="scope"):
            plan_approved_keyword_enqueue(
                conn,
                approval_manifest=manifest,
                analysis=analysis,
                now=NOW,
            )


def _root_manifest(roots, dataset_fingerprint="root-dataset"):
    return {
        "version": 1,
        "approval_kind": "discovery_root_pilot",
        "dataset_fingerprint": dataset_fingerprint,
        "scope": {
            "human_review_only": True,
            "writes_queue": False,
            "search_execution": False,
            "monitor_authorization": False,
            "soak_authorization": False,
        },
        "entries": [
            {
                "phrase": phrase,
                "status": "approved",
                "source_fingerprint": discovery_root_source_fingerprint(
                    dataset_fingerprint,
                    phrase,
                ),
            }
            for phrase in roots
        ],
    }


def test_approved_root_pilot_plans_explicit_five_word_batch(tmp_path):
    roots = ["模板", "清单", "表格", "手册", "话术", "食谱"]
    manifest = _root_manifest(roots)
    with connect(tmp_path / "state.sqlite3") as conn:
        plan = plan_approved_root_keyword_enqueue(
            conn,
            approval_manifest=manifest,
            allowed_roots=roots,
            root_dataset_fingerprint="root-dataset",
            batch_phrases=["模板", "话术", "食谱"],
            now=NOW,
        )

    assert plan.selected == ("模板", "话术", "食谱")
    assert plan.deferred == (
        {"phrase": "清单", "reason": "future_batch"},
        {"phrase": "表格", "reason": "future_batch"},
        {"phrase": "手册", "reason": "future_batch"},
    )


def test_approved_root_pilot_rejects_stale_or_unapproved_batch(tmp_path):
    roots = ["模板", "食谱"]
    manifest = _root_manifest(roots)
    with connect(tmp_path / "state.sqlite3") as conn:
        with pytest.raises(ProductKeywordError, match="dataset fingerprint"):
            plan_approved_root_keyword_enqueue(
                conn,
                approval_manifest=manifest,
                allowed_roots=roots,
                root_dataset_fingerprint="changed",
                batch_phrases=["模板"],
                now=NOW,
            )
        manifest["entries"][0]["status"] = "pending_review"
        with pytest.raises(ProductKeywordError, match="not approved"):
            plan_approved_root_keyword_enqueue(
                conn,
                approval_manifest=manifest,
                allowed_roots=roots,
                root_dataset_fingerprint="root-dataset",
                batch_phrases=["模板"],
                now=NOW,
            )
