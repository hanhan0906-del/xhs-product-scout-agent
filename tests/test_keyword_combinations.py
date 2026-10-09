import json

import pytest

from xhs_scout.db import connect
from xhs_scout.keyword_combinations import (
    analyze_keyword_combinations,
    persist_keyword_combination_analysis,
)


def _database(tmp_path):
    ctx = connect(tmp_path / "state.sqlite3")
    conn = ctx.__enter__()
    return ctx, conn


def _seed_record(
    conn,
    *,
    index,
    root,
    title,
    shop=None,
    risk_flags=(),
    noise_reasons=(),
    traceable=True,
):
    now = "2026-07-30T14:00:00+08:00"
    run_id = f"run-{index}"
    conn.execute(
        """
        INSERT INTO search_tasks(
            id, keyword, source, status, created_at, updated_at
        ) VALUES (?, ?, 'discovery_root', 'completed', ?, ?)
        """,
        (index, root, now, now),
    )
    conn.execute(
        """
        INSERT INTO products(
            id, fingerprint, title, shop_name, share_url,
            first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            index,
            f"product-{index}",
            title,
            shop or f"shop-{index}",
            f"https://xhslink.com/m/{index}",
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO observations(id, product_id, observed_at, source)
        VALUES (?, ?, ?, 'controlled_real')
        """,
        (index, index, now),
    )
    if traceable:
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                task_id, product_id, observation_id, source_keyword,
                result_rank, page_kind, recorded_at, valid
            ) VALUES (?, ?, ?, ?, 1, 'search_results', ?, 1)
            """,
            (index, index, index, root, now),
        )
        conn.execute(
            """
            INSERT INTO run_events(
                run_id, event_at, phase, event, task_id, product_id,
                observation_id, data_json
            ) VALUES (?, ?, 'monitor', 'task_completed', ?, ?, ?, '{}')
            """,
            (run_id, now, index, index, index),
        )
    conn.execute(
        """
        INSERT INTO product_keyword_records(
            product_id, observation_id, task_id, run_id, source_root,
            source_keyword, raw_title, normalized_title, search_result_rank,
            search_context_recovered, share_url, evidence_path, evidence_json,
            risk_flags_json, noise_reasons_json, decomposition_status,
            review_status, source_fingerprint, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, '{}', ?, ?, 'complete',
                  'pending_review', ?, ?, ?)
        """,
        (
            index,
            index,
            index,
            run_id,
            root,
            root,
            title,
            title,
            f"https://xhslink.com/m/{index}",
            f"evidence/{index}.png",
            json.dumps(list(risk_flags), ensure_ascii=False),
            json.dumps(list(noise_reasons), ensure_ascii=False),
            f"fingerprint-{index}",
            now,
            now,
        ),
    )
    record_id = conn.execute(
        "SELECT id FROM product_keyword_records WHERE product_id=?",
        (index,),
    ).fetchone()[0]
    terms = (
        ("domain", "新媒体运营"),
        ("scene", "月度复盘"),
        ("format", "模板"),
    )
    for dimension, term in terms:
        conn.execute(
            """
            INSERT INTO product_keyword_terms(
                record_id, dimension, raw_term, normalized_term,
                evidence_excerpt, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record_id, dimension, term, term, title, now),
        )


def test_below_small_gate_returns_no_candidates_and_no_authority(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        for index in range(1, 30):
            _seed_record(
                conn,
                index=index,
                root=f"根词-{index % 10}",
                title="新媒体运营月度复盘模板",
            )
        analysis = analyze_keyword_combinations(conn)
        assert analysis.generation_stage == "not_ready"
        assert analysis.product_count == 29
        assert analysis.candidates == ()
        assert analysis.scope["production_queue_write"] is False
        assert analysis.scope["search_trigger"] is False
    finally:
        ctx.__exit__(None, None, None)


def test_small_gate_uses_title_phrases_not_cartesian_products(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        for index in range(1, 31):
            _seed_record(
                conn,
                index=index,
                root=f"根词-{index % 10}",
                title="新媒体运营月度复盘模板",
            )
        analysis = analyze_keyword_combinations(conn)
        assert analysis.generation_stage == "not_ready"
        assert analysis.product_count == 30
        assert analysis.root_count == 10
        assert analysis.domain_scene_count == 2
        assert analysis.gates["small_domain_or_scene"] is False
        assert analysis.candidates == ()
    finally:
        ctx.__exit__(None, None, None)


def test_small_gate_emits_only_observed_pending_review_phrases(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        for index in range(1, 31):
            title = (
                "新媒体运营月度复盘模板"
                if index < 30
                else "新媒体运营年度复盘模板"
            )
            _seed_record(
                conn,
                index=index,
                root=f"根词-{index % 10}",
                title=title,
            )
            if index == 30:
                record_id = conn.execute(
                    "SELECT id FROM product_keyword_records WHERE product_id=30"
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO product_keyword_terms(
                        record_id, dimension, raw_term, normalized_term,
                        evidence_excerpt, created_at
                    ) VALUES (?, 'scene', '年度复盘', '年度复盘', ?, ?)
                    """,
                    (
                        record_id,
                        title,
                        "2026-07-30T14:00:00+08:00",
                    ),
                )
        analysis = analyze_keyword_combinations(conn)
        assert analysis.generation_stage == "sample"
        assert analysis.gates["small_domain_or_scene"] is True
        assert analysis.candidates
        assert all(item.review_status == "pending_review" for item in analysis.candidates)
        assert all(item.candidate_stage == "sample" for item in analysis.candidates)
        assert all(item.phrase in {
            "新媒体运营月度复盘",
            "月度复盘模板",
            "新媒体运营年度复盘",
            "年度复盘模板",
        } for item in analysis.candidates)
        assert "新媒体运营模板" not in {
            item.phrase for item in analysis.candidates
        }
    finally:
        ctx.__exit__(None, None, None)


def test_untraceable_or_risky_records_do_not_unlock_gate(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        for index in range(1, 32):
            _seed_record(
                conn,
                index=index,
                root=f"根词-{index % 10}",
                title="新媒体运营月度复盘模板",
                risk_flags=("contact_or_diversion",) if index == 31 else (),
                traceable=index != 30,
            )
        analysis = analyze_keyword_combinations(conn)
        assert analysis.product_count == 30
        assert analysis.gates["all_records_traceable"] is False
        assert analysis.generation_stage == "not_ready"
        assert analysis.candidates == ()
    finally:
        ctx.__exit__(None, None, None)


def test_stable_candidate_requires_two_products_and_preserves_independence(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        for index in range(1, 101):
            title = (
                "新媒体运营年度复盘模板"
                if index == 100
                else "新媒体运营月度复盘模板"
            )
            _seed_record(
                conn,
                index=index,
                root=f"根词-{index % 30}",
                title=title,
                shop=f"shop-{index % 3}",
            )
            if index == 100:
                record_id = conn.execute(
                    "SELECT id FROM product_keyword_records WHERE product_id=100"
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO product_keyword_terms(
                        record_id, dimension, raw_term, normalized_term,
                        evidence_excerpt, created_at
                    ) VALUES (?, 'scene', '年度复盘', '年度复盘', ?, ?)
                    """,
                    (
                        record_id,
                        title,
                        "2026-07-30T14:00:00+08:00",
                    ),
                )
        analysis = analyze_keyword_combinations(conn)
        assert analysis.generation_stage == "stable"
        common = next(
            item
            for item in analysis.candidates
            if item.phrase == "新媒体运营月度复盘"
        )
        rare = next(
            item
            for item in analysis.candidates
            if item.phrase == "新媒体运营年度复盘"
        )
        assert common.candidate_stage == "stable"
        assert common.product_count == 99
        assert common.shop_count == 3
        assert common.context_count == 99
        assert rare.candidate_stage == "sample"
        assert rare.product_count == 1
    finally:
        ctx.__exit__(None, None, None)


def test_snapshot_persistence_is_idempotent_and_never_enqueues(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        for index in range(1, 31):
            title = (
                "新媒体运营年度复盘模板"
                if index == 30
                else "新媒体运营月度复盘模板"
            )
            _seed_record(
                conn,
                index=index,
                root=f"根词-{index % 10}",
                title=title,
            )
            if index == 30:
                record_id = conn.execute(
                    "SELECT id FROM product_keyword_records WHERE product_id=30"
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO product_keyword_terms(
                        record_id, dimension, raw_term, normalized_term,
                        evidence_excerpt, created_at
                    ) VALUES (?, 'scene', '年度复盘', '年度复盘', ?, ?)
                    """,
                    (
                        record_id,
                        title,
                        "2026-07-30T14:00:00+08:00",
                    ),
                )
        before_tasks = conn.execute(
            "SELECT COUNT(*) FROM search_tasks"
        ).fetchone()[0]
        analysis = analyze_keyword_combinations(conn)
        first = persist_keyword_combination_analysis(conn, analysis)
        second = persist_keyword_combination_analysis(conn, analysis)
        assert first == second
        assert conn.execute(
            "SELECT COUNT(*) FROM keyword_combination_snapshots"
        ).fetchone()[0] == 1
        assert conn.execute(
            """
            SELECT COUNT(*) FROM keyword_combination_candidates
            WHERE review_status='pending_review'
            """
        ).fetchone()[0] == len(analysis.candidates)
        assert conn.execute(
            "SELECT COUNT(*) FROM search_tasks"
        ).fetchone()[0] == before_tasks
    finally:
        ctx.__exit__(None, None, None)
