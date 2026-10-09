from pathlib import Path

from xhs_scout.config import Settings
from xhs_scout.db import connect, enqueue, record_note_observation, record_search_result_evidence, utcnow
from xhs_scout.reports import generate_candidate_report
from xhs_scout.workflow import complete_task_from_observation, start_task


def test_generate_candidate_report_includes_search_source(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["virtual-materials"])
        task_id = conn.execute("SELECT id FROM search_tasks").fetchone()[0]
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, shop_name, price, is_virtual,
                virtual_confidence, first_seen_at, last_seen_at
            ) VALUES ('fp-report', 'Interview template pack', 'Test shop', 39.9, 1, 1, ?, ?)
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, screenshot_path, raw_text,
                cumulative_sales_min, sales_30d_min, raw_signals_json
            ) VALUES (?, ?, 'test', 'shot.png', 'raw', 1000, 300, '{}')
            """,
            (product_id, now),
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score, reasons_json, status
            ) VALUES (?, ?, 'B', 66.0, '["trend"]', 'candidate')
            """,
            (product_id, now),
        )
        start_task(conn, task_id)
        complete_task_from_observation(conn, task_id, observation_id)
        record_search_result_evidence(
            conn,
            task_id=task_id,
            product_id=product_id,
            observation_id=observation_id,
            source_keyword="virtual-materials",
            result_rank=1,
            search_probe_dir="data/probes/probe-report",
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="related_note_card",
            screenshot_path="note.png",
            probe_dir="data/probes/note-report",
            page_kind="note_detail",
            raw_text="Author A\n2天前\n1200\n评论",
            author_name="Author A",
            likes=1200,
            comments=55,
            published_days_ago=2,
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="author_profile_from_note",
            screenshot_path="profile.png",
            probe_dir="data/probes/profile-report",
            page_kind="account_profile",
            raw_text="Author A\n188 粉丝",
            author_name="Author A",
            follower_count=188,
            likes=9000,
        )

    result = generate_candidate_report(settings, limit=5)
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert result["candidate_count"] == 1
    assert "Interview template pack" in report
    assert "virtual-materials" in report
    assert "data/probes/probe-report" in report
    assert "### 事实证据" in report
    assert "### 推断" in report
    assert "### 证据缺口" in report
    assert "### 置信度" in report
    assert "分析标签：职场求职" in report
    assert "单条公开笔记：作者 Author A，点赞 1200" in report
    assert "发布距今 2 天" in report
    assert "公开账号主页：作者 Author A，粉丝 188，账号累计获赞与收藏 9000" in report
    assert "按岗位和阶段拆分" in report


def test_report_includes_needs_review_and_does_not_revive_stale_search_evidence(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, shop_name, price, is_virtual,
                virtual_confidence, first_seen_at, last_seen_at
            ) VALUES ('fp-review', '职场新人资料包', '复核店铺', 19.9, 1, 1, ?, ?)
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, screenshot_path, raw_text,
                sales_30d_min, raw_signals_json
            ) VALUES (?, ?, 'test', 'review.png', 'raw', 700, '{bad-json')
            """,
            (product_id, now),
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score, reasons_json, status
            ) VALUES (?, ?, 'B', 61.0, '{bad-json', 'needs_review')
            """,
            (product_id, now),
        )
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                product_id, observation_id, source_keyword, result_rank,
                search_probe_dir, recorded_at, valid
            ) VALUES (?, ?, '旧有效关键词', 1, 'old-valid-probe', ?, 1)
            """,
            (product_id, observation_id, now),
        )
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                product_id, observation_id, source_keyword, result_rank,
                search_probe_dir, recorded_at, valid, invalid_reason
            ) VALUES (?, ?, '后续错误关键词', 2, 'latest-invalid-probe', ?, 0, 'keyword_mismatch')
            """,
            (product_id, observation_id, now),
        )

    result = generate_candidate_report(settings, limit=5)
    report = Path(result["report_path"]).read_text(encoding="utf-8")

    assert result["candidate_count"] == 1
    assert result["active_candidate_count"] == 0
    assert result["needs_review_count"] == 1
    assert "当前评估状态：人工复核（needs_review）" in report
    assert "候选理由数据格式异常，需人工复核" in report
    assert "已失效，不作为当前归属（keyword_mismatch）" in report
    assert "后续错误关键词" in report
    assert "latest-invalid-probe" in report
    assert "old-valid-probe" not in report
    assert "不能沿用更早记录作为当前关键词归属" in report
