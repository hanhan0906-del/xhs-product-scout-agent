import sqlite3
from pathlib import Path

import pytest

from xhs_scout.db import (
    connect,
    dashboard_stats,
    enqueue,
    get_monitor_state,
    recent_run_events,
    record_run_event,
    record_search_result_evidence,
    set_monitor_desired_state,
    set_monitor_state,
    utcnow,
)
from xhs_scout.monitor import _keyword_matches_search_page
from xhs_scout.workflow import (
    _persist_product_link_result,
    complete_task_from_observation,
    keyword_visible_on_page,
    start_task,
    stop_task,
)


def build_db(path: Path, keyword: str = "virtual-materials") -> tuple[int, int]:
    with connect(path) as conn:
        enqueue(conn, [keyword])
        task_id = conn.execute("SELECT id FROM search_tasks").fetchone()[0]
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, first_seen_at, last_seen_at,
                is_virtual, virtual_confidence
            ) VALUES ('fp', 'test knowledge pack', ?, ?, 1, 1)
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, raw_signals_json
            ) VALUES (?, ?, 'test', '{}')
            """,
            (product_id, now),
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return task_id, observation_id


def test_task_state_and_result_link(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    task_id, observation_id = build_db(db_path)
    with connect(db_path) as conn:
        start_task(conn, task_id)
        result = complete_task_from_observation(conn, task_id, observation_id)
        assert result["status"] == "completed"
        assert conn.execute(
            "SELECT COUNT(*) FROM task_results WHERE task_id=?",
            (task_id,),
        ).fetchone()[0] == 1
        row = conn.execute(
            "SELECT status, attempts FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(row) == ("completed", 1)
        with pytest.raises(ValueError):
            start_task(conn, task_id)


def test_direct_product_url_is_persisted_without_overwriting_existing_share_url(
    tmp_path,
):
    db_path = tmp_path / "test.sqlite3"
    _, observation_id = build_db(db_path)
    with connect(db_path) as conn:
        product_id = conn.execute(
            "SELECT product_id FROM observations WHERE id=?",
            (observation_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE products SET share_url=? WHERE id=?",
            ("https://xhslink.com/m/existing", product_id),
        )

        assert _persist_product_link_result(
            conn,
            product_id,
            {
                "share_url": None,
                "direct_url": "xhsdiscover://goods_detail/64ff009",
            },
        ) is True
        row = conn.execute(
            "SELECT share_url, direct_url FROM products WHERE id=?",
            (product_id,),
        ).fetchone()

    assert tuple(row) == (
        "https://xhslink.com/m/existing",
        "xhsdiscover://goods_detail/64ff009",
    )


def test_same_keyword_can_be_monitored_again_after_completion(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    task_id, observation_id = build_db(db_path, keyword="repeat-keyword")
    with connect(db_path) as conn:
        start_task(conn, task_id)
        complete_task_from_observation(conn, task_id, observation_id)

        assert enqueue(conn, ["repeat-keyword"]) == 1
        task_id_2 = conn.execute(
            "SELECT id FROM search_tasks WHERE status='pending' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        start_task(conn, task_id_2)
        complete_task_from_observation(conn, task_id_2, observation_id)

        assert conn.execute(
            "SELECT COUNT(*) FROM search_tasks WHERE keyword='repeat-keyword' AND status='completed'"
        ).fetchone()[0] == 2


def test_same_keyword_still_dedupes_active_tasks(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    with connect(db_path) as conn:
        assert enqueue(conn, ["repeat-keyword"]) == 1
        assert enqueue(conn, ["repeat-keyword"]) == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM search_tasks WHERE keyword='repeat-keyword'"
        ).fetchone()[0] == 1


def test_legacy_keyword_status_unique_schema_is_migrated(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(db_path)
    now = utcnow()
    legacy.executescript(
        """
        CREATE TABLE search_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            priority INTEGER NOT NULL DEFAULT 50,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(keyword, status)
        );
        """
    )
    legacy.execute(
        """
        INSERT INTO search_tasks(keyword, source, status, created_at, updated_at)
        VALUES ('repeat-keyword', 'test', 'completed', ?, ?)
        """,
        (now, now),
    )
    legacy.commit()
    legacy.close()

    with connect(db_path) as conn:
        assert enqueue(conn, ["repeat-keyword"]) == 1
        conn.execute(
            "UPDATE search_tasks SET status='completed' WHERE keyword='repeat-keyword'"
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM search_tasks WHERE keyword='repeat-keyword' AND status='completed'"
        ).fetchone()[0] == 2


def test_task_can_pause_for_manual_detail(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    task_id, _ = build_db(db_path)
    with connect(db_path) as conn:
        start_task(conn, task_id)
        stop_task(conn, task_id, "needs_manual_detail", "not a product detail page")
        row = conn.execute(
            "SELECT status, last_error FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(row) == ("needs_manual_detail", "not a product detail page")


def test_keyword_visible_on_page_uses_compact_text():
    assert keyword_visible_on_page("study material", "study material detail page")
    assert not keyword_visible_on_page("essay template", "business course page")


def test_search_page_keyword_owner_uses_fixed_screenshot_roi():
    xml = """<hierarchy>
      <node text="公务员备考管理系统飞书模板" content-desc="" clickable="true" bounds="[41,78][506,91]" />
      <node text="虚拟资料" content-desc="" clickable="true" focusable="true" bounds="[166,89][786,210]" />
    </hierarchy>"""
    probe = {
        "text": "虚拟资料 公务员备考管理系统飞书模板",
        "ocr": [
            {
                "text": "虚拟资料",
                "confidence": 0.99,
                "box": [[166, 127], [440, 127], [440, 170], [166, 170]],
            },
            {
                "text": "公务员备考管理系统飞书模板",
                "confidence": 0.99,
                "box": [[40, 350], [500, 350], [500, 410], [40, 410]],
            },
        ],
    }
    assert _keyword_matches_search_page("虚拟资料", probe, xml)
    assert not _keyword_matches_search_page("飞书模板", probe, xml)


def test_run_event_logging(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    task_id, observation_id = build_db(db_path)
    with connect(db_path) as conn:
        event_id = record_run_event(
            conn,
            run_id="run-1",
            phase="current_detail",
            event="task_completed",
            task_id=task_id,
            observation_id=observation_id,
            message="done",
            data={"ok": True},
        )
        assert event_id > 0
        events = recent_run_events(conn)
        assert events[0]["run_id"] == "run-1"
        assert events[0]["event"] == "task_completed"
        assert events[0]["message"] == "done"


def test_search_result_evidence_is_visible_in_dashboard(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    task_id, observation_id = build_db(db_path)
    with connect(db_path) as conn:
        start_task(conn, task_id)
        result = complete_task_from_observation(conn, task_id, observation_id)
        evidence_id = record_search_result_evidence(
            conn,
            task_id=task_id,
            product_id=result["product_id"],
            observation_id=observation_id,
            source_keyword="virtual-materials",
            result_rank=1,
            page_kind="shop_product_list",
            search_probe_dir="data/probes/probe-test",
            search_screenshot_path="data/probes/probe-test/current.png",
            text_excerpt="first result card",
        )
        assert evidence_id > 0

        recent = dashboard_stats(conn)["recent"][0]
        assert recent["search_source_keyword"] == "virtual-materials"
        assert recent["search_result_rank"] == 1
        assert recent["search_probe_dir"] == "data/probes/probe-test"


def test_invalid_search_evidence_is_not_reactivated_by_duplicate_record(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    task_id, observation_id = build_db(db_path)
    with connect(db_path) as conn:
        start_task(conn, task_id)
        result = complete_task_from_observation(conn, task_id, observation_id)
        evidence_id = record_search_result_evidence(
            conn,
            task_id=task_id,
            product_id=result["product_id"],
            observation_id=observation_id,
            source_keyword="virtual-materials",
            result_rank=1,
        )
        conn.execute(
            """
            UPDATE search_result_evidence
            SET valid=0, invalid_reason='keyword mismatch'
            WHERE id=?
            """,
            (evidence_id,),
        )
        record_search_result_evidence(
            conn,
            task_id=task_id,
            product_id=result["product_id"],
            observation_id=observation_id,
            source_keyword="virtual-materials",
            result_rank=1,
            text_excerpt="duplicate write",
        )
        row = conn.execute(
            "SELECT valid, invalid_reason FROM search_result_evidence WHERE id=?",
            (evidence_id,),
        ).fetchone()

    assert row["valid"] == 0
    assert row["invalid_reason"] == "keyword mismatch"


def test_monitor_state_defaults_and_updates(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    with connect(db_path) as conn:
        assert get_monitor_state(conn)["desired_state"] == "paused"
        set_monitor_desired_state(conn, "running")
        set_monitor_state(conn, "last_report_path", "data/reports/latest.md")
        state = get_monitor_state(conn)
        assert state["desired_state"] == "running"
        assert state["risk_stop_reason"] is None
        assert state["last_report_path"] == "data/reports/latest.md"
