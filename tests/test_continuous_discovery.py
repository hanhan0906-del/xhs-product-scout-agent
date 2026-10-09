from datetime import datetime, timedelta, timezone
from pathlib import Path

from xhs_scout.config import Settings
from xhs_scout.continuous_discovery import (
    load_continuous_discovery_roots,
    plan_continuous_discovery_round,
)
from xhs_scout.db import connect, enqueue, set_monitor_state, utcnow
from xhs_scout.scheduler import ContinuousMonitorScheduler


NOW = datetime(2026, 7, 30, 22, 0, tzinfo=timezone(timedelta(hours=8)))

OPENING_ROOTS = (
    "开学第一课PPT", "收心主题班会", "新生入学教育PPT", "开学安全教育PPT",
    "开学家长会PPT", "开学第一周教案", "班主任工作手册", "班级管理手册",
    "班规班纪模板", "班级量化管理表", "班干部竞选PPT", "座位表模板",
    "值日表模板", "课程表模板", "学生信息登记表", "家校联系手册",
    "开学通知模板", "入学须知模板", "学期教学计划", "班主任工作计划",
    "教学进度表", "学情分析模板", "开学摸底试卷", "班级文化建设方案",
    "开学黑板报模板", "开学典礼方案", "幼儿园开学环创", "幼儿园新生入园手册",
    "幼儿园开学第一周教案", "幼儿园开学家长会",
)

HISTORICAL_ROOTS_70 = (
    "模板", "手册", "笔记", "指南", "食谱", "配方", "方案", "表格", "题库", "讲义",
    "导图", "清单", "话术", "脚本", "图纸", "线稿", "字帖", "课件", "范本", "例文",
    "合同", "协议", "预案", "规划", "流程", "台账", "问卷", "量表", "档案", "请柬",
    "海报", "封面", "打卡表", "报价单", "预算表", "合集", "教程", "攻略", "发言稿",
    "说课稿", "开题稿", "答辩稿", "述职稿", "排班表", "核对表", "施工图", "布局图",
    "纹样图", "笔刷", "预设", "滤镜", "提示词", "金句库", "标题库", "分镜", "台词",
    "采访稿", "养护表", "训练表", "作息表", "识字卡", "手抄报", "计划书", "复盘表",
    "测算表", "成长录", "测评表", "申请函", "搭配表", "索引表",
)


def _record_completed_rank(conn, keyword: str, rank: int, task_id: int) -> None:
    stamp = utcnow()
    conn.execute(
        """
        UPDATE search_tasks
        SET status='completed', last_finished_at=?, updated_at=?
        WHERE id=?
        """,
        (stamp, stamp, task_id),
    )
    product = conn.execute(
        """
        INSERT INTO products(fingerprint, title, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        (f"{keyword}-{rank}", f"商品{rank}", stamp, stamp),
    )
    product_id = int(product.lastrowid)
    observation = conn.execute(
        """
        INSERT INTO observations(product_id, observed_at, source)
        VALUES (?, ?, 'test')
        """,
        (product_id, stamp),
    )
    observation_id = int(observation.lastrowid)
    conn.execute(
        """
        INSERT INTO task_results(
            task_id, product_id, observation_id, captured_at, valid
        ) VALUES (?, ?, ?, ?, 1)
        """,
        (task_id, product_id, observation_id, stamp),
    )
    conn.execute(
        """
        INSERT INTO search_result_evidence(
            task_id, product_id, observation_id, source_keyword,
            result_rank, recorded_at, valid
        ) VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (task_id, product_id, observation_id, keyword, rank, stamp),
    )


def test_configured_hundred_roots_load_in_file_order():
    project_root = Path(__file__).resolve().parents[1]

    roots = load_continuous_discovery_roots(project_root)

    assert len(roots) == 100
    assert len(set(roots)) == 100
    assert roots[:30] == OPENING_ROOTS
    assert roots[30:] == HISTORICAL_ROOTS_70


def test_configured_hundred_roots_collect_five_ranks_before_next_keyword(tmp_path):
    settings = Settings.load(tmp_path)
    project_root = Path(__file__).resolve().parents[1]
    roots = load_continuous_discovery_roots(project_root)
    scheduler = ContinuousMonitorScheduler(
        settings,
        discovery_roots=roots,
        discovery_card_slots=5,
    )

    with connect(settings.db_path) as conn:
        selected = []
        for expected_rank in range(1, 6):
            payload, limits = scheduler._prepare_round(conn)
            selected.append(
                (
                    payload["continuous_discovery"]["keyword"],
                    limits.search_result_rank,
                )
            )
            _record_completed_rank(conn, roots[0], expected_rank, limits.task_id)
            scheduler._after_round(
                conn,
                payload,
                limits,
                {
                    "run_id": f"rank-{expected_rank}",
                    "captured_products": 1,
                    "blocked": None,
                    "busy": False,
                },
            )

        next_payload, next_limits = scheduler._prepare_round(conn)
        rows = conn.execute(
            """
            SELECT keyword, status FROM search_tasks
            WHERE source='continuous_24h_root' ORDER BY id
            """
        ).fetchall()

    assert selected == [(roots[0], rank) for rank in range(1, 6)]
    assert next_payload["continuous_discovery"]["keyword"] == roots[1]
    assert next_limits.search_result_rank == 1
    assert [(row["keyword"], row["status"]) for row in rows] == [
        *((roots[0], "completed") for _ in range(5)),
        (roots[1], "pending"),
    ]


def test_fifth_rank_failure_does_not_advance_keyword_cursor(tmp_path):
    settings = Settings.load(tmp_path)
    scheduler = ContinuousMonitorScheduler(
        settings,
        discovery_roots=("关键词一", "关键词二"),
        discovery_card_slots=5,
    )
    with connect(settings.db_path) as conn:
        _payload, initial_limits = scheduler._prepare_round(conn)
        for rank in range(1, 5):
            _record_completed_rank(conn, "关键词一", rank, initial_limits.task_id)
        payload, limits = scheduler._prepare_round(conn)
        scheduler._after_round(
            conn,
            payload,
            limits,
            {
                "run_id": "rank-5-failed",
                "captured_products": 0,
                "blocked": None,
                "busy": False,
            },
        )
        cursor = int(
            conn.execute(
                "SELECT value FROM monitor_state WHERE key='continuous_discovery_cursor'"
            ).fetchone()[0]
        )

    assert limits.expected_keyword == "关键词一"
    assert limits.search_result_rank == 5
    assert cursor == 0


def test_continuous_discovery_ignores_legacy_pending_queue(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["旧词一", "旧词二"], source="seed_workbook")
        plan = plan_continuous_discovery_round(conn, now=NOW)

        task = conn.execute(
            "SELECT keyword, source, status FROM search_tasks WHERE id=?",
            (plan.task_id,),
        ).fetchone()

    assert plan.selected is True
    assert plan.keyword == "虚拟资料"
    assert plan.search_result_rank == 1
    assert task["source"] == "continuous_24h_root"
    assert task["status"] == "pending"


def test_only_human_approved_keyword_joins_root_rotation(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["人情世故攻略"], source="approved_discovery_keyword")
        conn.execute(
            """
            UPDATE search_tasks SET status='completed',
                last_finished_at='2026-07-28T00:00:00+08:00',
                updated_at='2026-07-28T00:00:00+08:00'
            WHERE keyword='人情世故攻略'
            """
        )
        set_monitor_state(conn, "continuous_discovery_cursor", 1)
        plan = plan_continuous_discovery_round(conn, now=NOW)

    assert plan.selected is True
    assert plan.keyword == "人情世故攻略"
    assert plan.allowed_keyword_count == 2


def test_recent_keyword_is_not_requeued_inside_cooldown(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["虚拟资料"], source="continuous_24h_root")
        conn.execute(
            """
            UPDATE search_tasks SET status='completed',
                last_finished_at=?, updated_at=?
            WHERE keyword='虚拟资料'
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        plan = plan_continuous_discovery_round(conn, now=NOW)

    assert plan.selected is False
    assert plan.reason == "all_allowed_keywords_cooling_down"
    assert plan.deferred[0]["reason"] == "keyword_cooldown"


def test_cooling_root_is_skipped_and_next_root_is_created(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["模板"], source="continuous_24h_root")
        conn.execute(
            """
            UPDATE search_tasks SET status='completed',
                last_finished_at=?, updated_at=? WHERE keyword='模板'
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        plan = plan_continuous_discovery_round(
            conn,
            roots=("模板", "手册"),
            now=NOW,
        )

    assert plan.selected is True
    assert plan.keyword == "手册"
    assert plan.deferred == (
        {"keyword": "模板", "reason": "keyword_cooldown", "last_at": NOW.isoformat()},
    )


def test_manual_detail_conflict_is_preserved_and_next_root_is_created(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["模板"], source="continuous_24h_root")
        conn.execute(
            """
            UPDATE search_tasks SET status='needs_manual_detail', attempts=2,
                last_error='manual evidence required' WHERE keyword='模板'
            """
        )
        blocked_id = conn.execute(
            "SELECT id FROM search_tasks WHERE keyword='模板'"
        ).fetchone()[0]

        plan = plan_continuous_discovery_round(
            conn,
            roots=("模板", "手册", "笔记"),
            now=NOW,
        )
        blocked = conn.execute(
            """
            SELECT status, attempts, last_error FROM search_tasks WHERE id=?
            """,
            (blocked_id,),
        ).fetchone()
        tasks = conn.execute(
            "SELECT keyword, status FROM search_tasks ORDER BY id"
        ).fetchall()

    assert plan.selected is True
    assert plan.keyword == "手册"
    assert plan.created is True
    assert plan.deferred == (
        {
            "keyword": "模板",
            "reason": "enqueue_conflict",
            "task_id": blocked_id,
            "status": "needs_manual_detail",
            "attempts": 2,
        },
    )
    assert dict(blocked) == {
        "status": "needs_manual_detail",
        "attempts": 2,
        "last_error": "manual evidence required",
    }
    assert [(row["keyword"], row["status"]) for row in tasks] == [
        ("模板", "needs_manual_detail"),
        ("手册", "pending"),
    ]


def test_all_non_reusable_conflicts_defer_without_mutating_history(tmp_path):
    settings = Settings.load(tmp_path)
    statuses = ("needs_manual_detail", "risk_stopped", "paused")
    with connect(settings.db_path) as conn:
        for index, (keyword, status) in enumerate(zip(("模板", "手册", "笔记"), statuses), 1):
            enqueue(conn, [keyword], source="continuous_24h_root")
            conn.execute(
                "UPDATE search_tasks SET status=?, attempts=? WHERE keyword=?",
                (status, index, keyword),
            )
        plan = plan_continuous_discovery_round(
            conn,
            roots=("模板", "手册", "笔记"),
            now=NOW,
        )
        rows = conn.execute(
            "SELECT keyword, status, attempts FROM search_tasks ORDER BY id"
        ).fetchall()

    assert plan.selected is False
    assert plan.reason == "all_allowed_keywords_deferred"
    assert [item["reason"] for item in plan.deferred] == [
        "enqueue_conflict",
        "enqueue_conflict",
        "enqueue_conflict",
    ]
    assert [(row["keyword"], row["status"], row["attempts"]) for row in rows] == [
        ("模板", "needs_manual_detail", 1),
        ("手册", "risk_stopped", 2),
        ("笔记", "paused", 3),
    ]


def test_existing_allowed_task_is_selected_by_exact_id(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["虚拟资料"], source="manual")
        task_id = conn.execute(
            "SELECT id FROM search_tasks WHERE keyword='虚拟资料'"
        ).fetchone()[0]
        plan = plan_continuous_discovery_round(conn, now=NOW)

    assert plan.selected is True
    assert plan.task_id == task_id
    assert plan.created is False
    assert plan.reason == "existing_allowed_task"


def test_valid_search_evidence_rotates_visible_card_rank(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["虚拟资料"], source="manual")
        task_id = int(
            conn.execute(
                "SELECT id FROM search_tasks WHERE keyword='虚拟资料'"
            ).fetchone()[0]
        )
        _record_completed_rank(conn, "虚拟资料", 1, task_id)
        _record_completed_rank(conn, "虚拟资料", 2, task_id)
        plan = plan_continuous_discovery_round(conn, now=NOW)

    assert plan.search_result_rank == 3


def test_search_evidence_without_valid_task_result_does_not_advance_rank(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["虚拟资料"], source="manual")
        task_id = int(
            conn.execute(
                "SELECT id FROM search_tasks WHERE keyword='虚拟资料'"
            ).fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO search_result_evidence(
                task_id, source_keyword, result_rank, recorded_at, valid
            ) VALUES (?, '虚拟资料', 1, ?, 1)
            """,
            (task_id, utcnow()),
        )
        plan = plan_continuous_discovery_round(conn, now=NOW)

    assert plan.search_result_rank == 1


def test_risk_stop_blocks_new_continuous_task(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", "captcha")
        plan = plan_continuous_discovery_round(conn, now=NOW)
        count = conn.execute("SELECT COUNT(*) FROM search_tasks").fetchone()[0]

    assert plan.selected is False
    assert plan.reason == "risk_stop_active"
    assert count == 0


def test_continuous_scheduler_exact_binds_allowed_task_and_card_rank(tmp_path):
    settings = Settings.load(tmp_path)
    scheduler = ContinuousMonitorScheduler(
        settings,
        discovery_roots=("虚拟资料",),
        discovery_card_slots=3,
    )

    with connect(settings.db_path) as conn:
        enqueue(conn, ["旧的待搜索任务"], source="seed_workbook")
        enqueue(conn, ["虚拟资料"], source="manual")
        task_id = int(
            conn.execute(
                "SELECT id FROM search_tasks WHERE keyword='虚拟资料'"
            ).fetchone()[0]
        )
        _record_completed_rank(conn, "虚拟资料", 1, task_id)
        payload, limits = scheduler._prepare_round(conn)

        selected = conn.execute(
            "SELECT keyword FROM search_tasks WHERE id=?",
            (limits.task_id,),
        ).fetchone()

    assert payload["continuous_discovery"]["keyword"] == "虚拟资料"
    assert limits.expected_keyword == "虚拟资料"
    assert limits.search_result_rank == 2
    assert limits.search_card_scan_limit == 3
    assert selected["keyword"] == "虚拟资料"


def test_continuous_scheduler_loads_configured_root_file_by_default(tmp_path):
    settings = Settings.load(tmp_path)
    root_file = settings.root / "config" / "discovery_root_terms.txt"
    root_file.write_text(
        "\n".join(f"根词{i:03d}" for i in range(1, 101)),
        encoding="utf-8",
    )

    scheduler = ContinuousMonitorScheduler(settings)

    assert len(scheduler.discovery_roots) == 100
    assert scheduler.discovery_roots[0] == "根词001"
    assert scheduler.discovery_roots[-1] == "根词100"
