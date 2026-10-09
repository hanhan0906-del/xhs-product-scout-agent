from datetime import datetime, timedelta, timezone

from xhs_scout.digest import (
    CandidateSnapshot,
    MonitorSnapshot,
    ProductObservation,
    TaskSnapshot,
    build_daily_digest,
    build_weekly_digest,
    render_digest_markdown,
)


TZ = timezone(timedelta(hours=8))


def test_daily_digest_separates_facts_inferences_risks_gaps_and_alerts(tmp_path):
    generated_at = datetime(2026, 7, 28, 12, 0, tzinfo=TZ)
    evidence_root = tmp_path / "data"
    (evidence_root / "probes" / "note").mkdir(parents=True)
    (evidence_root / "probes" / "profile").mkdir(parents=True)
    observations = [
        ProductObservation(
            product_id=1,
            title="阅读理解暑假讲义",
            observed_at=generated_at - timedelta(days=2),
            metrics={"sales_30d_min": 1000, "interested_7d_min": 1000},
        ),
        ProductObservation(
            product_id=1,
            title="阅读理解暑假讲义",
            observed_at=generated_at - timedelta(hours=2),
            metrics={"sales_30d_min": 1800, "interested_7d_min": 2500},
        ),
        ProductObservation(
            product_id=2,
            title="效率系统模板",
            observed_at=generated_at - timedelta(days=2),
            metrics={"sales_7d_min": 800},
        ),
        ProductObservation(
            product_id=2,
            title="效率系统模板",
            observed_at=generated_at - timedelta(hours=1),
            metrics={"sales_7d_min": 300, "sales_surging": True},
        ),
    ]
    candidates = [
        CandidateSnapshot(
            product_id=1,
            title="阅读理解暑假讲义",
            assessed_at=generated_at - timedelta(hours=1),
            evidence_grade="B",
            score=78.7,
            is_new=True,
            note_author_name="小红点点",
            note_likes=1200,
            note_published_days_ago=2,
            note_evidence_path="data/probes/note",
            profile_author_name="小红点点",
            profile_follower_count=188,
            profile_evidence_path="data/probes/profile",
        ),
        CandidateSnapshot(
            product_id=2,
            title="效率系统模板",
            assessed_at=generated_at - timedelta(hours=3),
            evidence_grade="C",
            score=42.8,
            is_new=True,
            note_author_name="模板作者",
            note_likes=80,
            note_published_days_ago=15,
            profile_author_name="模板作者",
            profile_follower_count=12000,
        ),
    ]
    tasks = [
        TaskSnapshot(task_id=1, keyword="阅读理解", status="completed", attempts=1),
        TaskSnapshot(
            task_id=2,
            keyword="古诗文",
            status="needs_manual_detail",
            attempts=3,
            max_attempts=3,
            last_error="opened page is unknown",
        ),
    ]
    monitor = MonitorSnapshot(
        desired_state="paused",
        risk_stop_reason="captcha page detected",
        last_block_reason="app returned to home feed",
        last_skip_reason="task 2 skipped",
        scheduler_running=False,
        last_heartbeat=generated_at - timedelta(minutes=30),
    )

    digest = build_daily_digest(
        observations=observations,
        candidates=candidates,
        tasks=tasks,
        monitor=monitor,
        generated_at=generated_at,
        timezone_label="Asia/Shanghai",
        evidence_root=evidence_root,
    )
    markdown = render_digest_markdown(digest)

    assert digest.stats["new_candidates"] == 2
    assert digest.stats["low_follower_complete"] == 1
    assert digest.stats["failed_tasks"] == 1
    assert any("新增候选" in fact and "阅读理解暑假讲义" in fact for fact in digest.facts)
    assert any("从 1000 增至 1800" in fact for fact in digest.facts)
    assert any("增长明显" in item for item in digest.inferences)
    assert any("回落" in item for item in digest.risks)
    assert any("作者粉丝不少于1万" in item for item in digest.risks)
    assert any("缺少公开笔记证据目录" in item for item in digest.evidence_gaps)
    assert [alert.severity for alert in digest.alerts][:1] == ["critical"]
    assert any(alert.title == "风控停机" for alert in digest.alerts)
    assert any(alert.title == "任务失败率偏高" for alert in digest.alerts)
    assert any(item.task_id == 2 for item in digest.review_items)
    assert "## 事实" in markdown
    assert "## 推断" in markdown
    assert "## 风险" in markdown
    assert "## 证据缺口" in markdown
    assert "## 下一步人工复核清单" in markdown
    assert "时间口径" in markdown


def test_weekly_digest_accepts_mapping_inputs_and_marks_stale_data():
    generated_at = datetime(2026, 7, 28, 12, 0, tzinfo=TZ)
    digest = build_weekly_digest(
        observations=[
            {
                "product_id": 9,
                "title": "职场新人知识库",
                "observed_at": (generated_at - timedelta(days=5)).isoformat(),
                "sales_30d_min": 200,
                "search_source_keyword": "职场新人",
            }
        ],
        candidates=[
            {
                "product_id": 9,
                "title": "职场新人知识库",
                "assessed_at": (generated_at - timedelta(days=1)).isoformat(),
                "evidence_grade": "B",
                "score": "66",
                "latest_note_author_name": "作者A",
                "latest_note_likes": "6460",
                "latest_note_published_days_ago": "240",
                "latest_profile_author_name": "作者A",
                "latest_profile_follower_count": "5600",
            }
        ],
        tasks=[
            {
                "id": 5,
                "keyword": "职场新人",
                "status": "pending",
                "attempts": 0,
            }
        ],
        monitor={
            "desired_state": "paused",
            "scheduler_running": False,
            "last_heartbeat": (generated_at - timedelta(days=5)).isoformat(),
        },
        generated_at=generated_at,
        timezone_label="Asia/Shanghai",
    )
    markdown = render_digest_markdown(digest)

    assert digest.stats["period"] == "weekly"
    assert digest.stats["new_candidates"] == 1
    assert any(alert.title == "商品观察数据陈旧" for alert in digest.alerts)
    assert any(alert.title == "调度心跳陈旧" for alert in digest.alerts)
    assert any("发布距今 240 天" in item for item in digest.risks)
    assert any("本窗口没有可比较的趋势变化" in item for item in digest.evidence_gaps)
    assert "# 小红书选品监控每周摘要" in markdown
    assert "职场新人知识库" in markdown


def test_digest_does_not_treat_9000_followers_as_low_follower_complete():
    generated_at = datetime(2026, 7, 28, 12, 0, tzinfo=TZ)
    digest = build_daily_digest(
        candidates=[
            CandidateSnapshot(
                product_id=1,
                title="高粉反例",
                assessed_at=generated_at,
                evidence_grade="B",
                note_author_name="作者",
                profile_author_name="作者",
                note_likes=1500,
                note_published_days_ago=1,
                profile_follower_count=9000,
                note_evidence_path="note",
                profile_evidence_path="profile",
            )
        ],
        generated_at=generated_at,
    )

    assert digest.stats["low_follower_complete"] == 0
