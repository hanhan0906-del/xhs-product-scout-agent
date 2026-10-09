import json

import pytest

from xhs_scout.db import connect
from xhs_scout.product_keyword_terms import (
    ProductKeywordError,
    decompose_product_keywords,
    load_discovery_roots,
    load_product_keyword_decomposition,
    persist_product_keyword_decomposition,
)


ROOTS = ("模板", "手册", "复盘表", "表格", "资料")


def _decomposition(tmp_path, **overrides):
    evidence = tmp_path / "evidence" / "search.png"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"evidence")
    values = {
        "source_root": "模板",
        "source_keyword": "模板",
        "run_id": "root-run-1",
        "task_id": 1,
        "product_id": 1,
        "observation_id": 1,
        "raw_title": "新媒体运营月度复盘表 Excel 模板",
        "search_result_rank": 1,
        "search_context_recovered": True,
        "evidence_path": evidence,
        "evidence": {
            "search_probe_dir": str(evidence.parent),
            "search_screenshot_path": str(evidence),
            "page_kind": "search_results",
        },
        "discovery_roots": ROOTS,
        "share_url": "https://xhslink.com/m/example",
        "link_gap": None,
    }
    values.update(overrides)
    return decompose_product_keywords(**values)


def _database(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    ctx = connect(db_path)
    conn = ctx.__enter__()
    now = "2026-07-30T14:00:00+08:00"
    conn.execute(
        """
        INSERT INTO search_tasks(
            id, keyword, source, status, created_at, updated_at
        ) VALUES (1, '模板', 'discovery_root', 'pending', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO products(
            id, fingerprint, title, share_url, first_seen_at, last_seen_at
        ) VALUES (1, 'p1', '新媒体运营月度复盘表 Excel 模板',
                  'https://xhslink.com/m/example', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO observations(
            id, product_id, observed_at, source, screenshot_path
        ) VALUES (1, 1, ?, 'controlled_real', 'capture.png')
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT INTO search_result_evidence(
            id, task_id, product_id, observation_id, source_keyword,
            result_rank, page_kind, search_probe_dir, search_screenshot_path,
            recorded_at, valid
        ) VALUES (
            1, 1, 1, 1, '模板', 1, 'search_results',
            'probe', 'probe/search.png', ?, 1
        )
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT INTO run_events(
            run_id, event_at, phase, event, task_id, product_id,
            observation_id, data_json
        ) VALUES ('root-run-1', ?, 'monitor', 'task_completed', 1, 1, 1, '{}')
        """,
        (now,),
    )
    return ctx, conn


def test_load_discovery_roots_requires_exact_unique_normalized_terms(tmp_path):
    path = tmp_path / "roots.txt"
    path.write_text("# roots\n模板\n手册\n", encoding="utf-8")
    assert load_discovery_roots(path, expected_count=2) == ("模板", "手册")

    path.write_text("模板\n模 板\n", encoding="utf-8")
    with pytest.raises(ProductKeywordError, match="unique"):
        load_discovery_roots(path, expected_count=2)


def test_decomposition_extracts_only_title_supported_six_dimension_terms(tmp_path):
    result = _decomposition(tmp_path)

    assert result.source_root == "模板"
    assert result.normalized_title == "新媒体运营月度复盘表 Excel 模板"
    assert [item.raw_term for item in result.terms["domain"]] == [
        "新媒体运营",
        "运营",
    ]
    assert [item.raw_term for item in result.terms["scene"]] == [
        "月度复盘",
        "复盘",
    ]
    assert [item.raw_term for item in result.terms["stage"]] == ["月度"]
    assert "复盘表" in [item.raw_term for item in result.terms["format"]]
    assert "模板" in [item.raw_term for item in result.terms["format"]]
    assert [item.raw_term for item in result.terms["function"]] == ["复盘"]
    assert result.terms["audience"] == ()
    assert result.decomposition_status == "complete"
    assert result.review_status == "pending_review"
    assert result.scope["production_queue_write"] is False
    assert result.scope["search_trigger"] is False
    json.dumps(result.as_dict(), ensure_ascii=False)


def test_lost_search_context_and_unknown_root_fail_before_persistence(tmp_path):
    with pytest.raises(ProductKeywordError, match="search context"):
        _decomposition(tmp_path, search_context_recovered=False)
    with pytest.raises(ProductKeywordError, match="active discovery root"):
        _decomposition(tmp_path, source_root="旧关键词")


def test_missing_link_requires_explicit_gap_and_remains_evidence_gap(tmp_path):
    with pytest.raises(ProductKeywordError, match="explicit link_gap"):
        _decomposition(tmp_path, share_url=None, link_gap=None)

    result = _decomposition(
        tmp_path,
        share_url=None,
        link_gap="share_url_not_captured",
    )
    assert result.decomposition_status == "evidence_gap"
    assert result.link_gap == "share_url_not_captured"


def test_hard_risk_is_preserved_and_cannot_look_complete(tmp_path):
    result = _decomposition(
        tmp_path,
        raw_title="加微信领取新媒体运营复盘表模板",
    )
    assert result.decomposition_status == "risk_blocked"
    assert result.risk_flags == ("contact_or_diversion",)
    assert all(
        item.review_status == "pending_review"
        for terms in result.terms.values()
        for item in terms
    )


def test_persistence_validates_chain_is_atomic_idempotent_and_never_enqueues(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        decomposition = _decomposition(tmp_path)
        record_id = persist_product_keyword_decomposition(
            conn,
            decomposition,
            evidence_allowed_roots=[tmp_path / "evidence"],
        )
        repeated_id = persist_product_keyword_decomposition(
            conn,
            decomposition,
            evidence_allowed_roots=[tmp_path / "evidence"],
        )
        assert repeated_id == record_id
        assert conn.execute(
            "SELECT COUNT(*) FROM product_keyword_records"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM search_tasks"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT status FROM search_tasks WHERE id=1"
        ).fetchone()[0] == "pending"

        stored = load_product_keyword_decomposition(conn, record_id)
        assert stored["source_root"] == "模板"
        assert stored["review_status"] == "pending_review"
        assert stored["decomposition_status"] == "complete"
        assert stored["evidence"]["page_kind"] == "search_results"
        assert stored["terms"]["format"]
        assert stored["scope"] == {
            "production_queue_write": False,
            "approval_write": False,
            "search_trigger": False,
            "monitor_authorization": False,
        }
    finally:
        ctx.__exit__(None, None, None)


def test_persistence_rejects_invalid_search_identity_without_partial_rows(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        conn.execute(
            "UPDATE search_result_evidence SET valid=0, invalid_reason='bad identity'"
        )
        with pytest.raises(ProductKeywordError, match="valid search evidence"):
            persist_product_keyword_decomposition(
                conn,
                _decomposition(tmp_path),
                evidence_allowed_roots=[tmp_path / "evidence"],
            )
        assert conn.execute(
            "SELECT COUNT(*) FROM product_keyword_records"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM product_keyword_terms"
        ).fetchone()[0] == 0
    finally:
        ctx.__exit__(None, None, None)


def test_persistence_rejects_evidence_path_outside_allowed_root(tmp_path):
    ctx, conn = _database(tmp_path)
    try:
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"outside")
        decomposition = _decomposition(tmp_path, evidence_path=outside)
        with pytest.raises(ProductKeywordError, match="outside allowed roots"):
            persist_product_keyword_decomposition(
                conn,
                decomposition,
                evidence_allowed_roots=[tmp_path / "evidence"],
            )
        assert conn.execute(
            "SELECT COUNT(*) FROM product_keyword_records"
        ).fetchone()[0] == 0
    finally:
        ctx.__exit__(None, None, None)
