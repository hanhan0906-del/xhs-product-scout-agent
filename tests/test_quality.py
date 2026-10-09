from datetime import datetime, timezone

from xhs_scout.quality import audit_evidence_records


def codes(report):
    return [issue.code for issue in report.issues]


def test_missing_identity_fields_and_screenshot_flag_are_reported():
    report = audit_evidence_records(
        observations=[
            {
                "id": 1,
                "product_id": 10,
                "title": "",
                "price": None,
                "share_url": "",
                "screenshot_path": "captures/missing.png",
                "screenshot_exists": False,
                "observed_at": "2026-07-28T10:00:00+08:00",
            }
        ],
        now="2026-07-28T12:00:00+08:00",
    )

    assert "missing_title" in codes(report)
    assert "missing_price" in codes(report)
    assert "missing_link" in codes(report)
    assert "screenshot_missing" in codes(report)
    assert report.summary["by_severity"]["error"] == 3
    assert report.summary["by_severity"]["warning"] == 1
    assert report.summary["has_errors"] is True


def test_trend_metric_conflicts_and_abnormal_magnitudes_are_reported():
    report = audit_evidence_records(
        observations=[
            {
                "id": 2,
                "product_id": 11,
                "title": "小学阅读理解电子资料",
                "price": 29.9,
                "share_url": "https://xhs.example/item/11",
                "screenshot_path": "captures/ok.png",
                "observed_at": "2026-07-28T10:00:00+08:00",
                "cumulative_sales_min": 40,
                "sales_24h_min": 800,
                "sales_7d_min": 100,
                "sales_30d_min": 50,
                "new_30d_min": 300,
                "cart_24h_min": -1,
                "viewers_now": 1_500_000,
            }
        ],
        now="2026-07-28T12:00:00+08:00",
    )

    assert "metric_window_conflict" in codes(report)
    assert "metric_total_conflict" in codes(report)
    assert "negative_metric" in codes(report)
    assert "abnormal_viewer_count" in codes(report)
    assert report.summary["by_code"]["metric_window_conflict"] == 3


def test_ocr_half_pollution_is_conservative_warning():
    report = audit_evidence_records(
        observations=[
            {
                "id": 3,
                "product_id": 12,
                "title": "Notion 项目管理模板",
                "price": 19.9,
                "share_url": "https://xhs.example/item/12",
                "screenshot_path": "captures/ocr.png",
                "observed_at": "2026-07-28T10:00:00+08:00",
                "raw_text": "近30天新增\n首页 消息 加入购物车 立即购买 关注 粉丝 说点什么",
            }
        ],
        now="2026-07-28T12:00:00+08:00",
    )

    issue = next(issue for issue in report.issues if issue.code == "ocr_half_pollution")
    assert issue.severity == "warning"
    assert issue.details["parsed_metric_fields"] == 0


def test_duplicate_product_observation_and_note_evidence_are_reported():
    report = audit_evidence_records(
        products=[
            {
                "id": 20,
                "title": "英语高频词电子资料",
                "price": 9.9,
                "share_url": "https://xhs.example/item/same",
            },
            {
                "id": 21,
                "title": "英语高频词电子资料",
                "price": 9.9,
                "share_url": "https://xhs.example/item/same",
            },
        ],
        observations=[
            {
                "id": 4,
                "product_id": 20,
                "screenshot_path": "captures/same.png",
                "observed_at": "2026-07-28T10:00:00+08:00",
            },
            {
                "id": 5,
                "product_id": 20,
                "screenshot_path": "captures/same.png",
                "observed_at": "2026-07-28T10:01:00+08:00",
            },
        ],
        notes=[
            {
                "id": 30,
                "product_id": 20,
                "source": "related_note_card",
                "page_kind": "note_detail",
                "author_name": "Author A",
                "probe_dir": "probe-a",
            },
            {
                "id": 31,
                "product_id": 20,
                "source": "related_note_card",
                "page_kind": "note_detail",
                "author_name": "Author A",
                "probe_dir": "probe-a",
            },
        ],
        now="2026-07-28T12:00:00+08:00",
    )

    assert "duplicate_product_evidence" in codes(report)
    assert "duplicate_observation_evidence" in codes(report)
    assert "duplicate_note_evidence" in codes(report)


def test_invalid_search_keyword_attribution_is_structured():
    report = audit_evidence_records(
        search_evidence=[
            {
                "id": 40,
                "source_keyword": "仿写训练",
                "task_keyword": "阅读理解",
                "valid": False,
                "invalid_reason": "query mismatch",
                "search_screenshot_path": "captures/search.png",
                "search_screenshot_exists": False,
            }
        ],
        allowed_keywords=["阅读理解"],
    )

    assert report.summary["by_code"]["invalid_search_keyword_attribution"] == 2
    assert "search_keyword_mismatch" in codes(report)
    assert "screenshot_missing" in codes(report)


def test_low_follower_verified_requires_note_profile_closure():
    missing = audit_evidence_records(
        products=[
            {
                "id": 50,
                "title": "高中英语作文模板电子资料",
                "price": 19.9,
                "share_url": "https://xhs.example/item/50",
                "evidence_grade": "A",
                "low_follower_verified": 1,
            }
        ]
    )
    assert missing.summary["by_code"]["low_follower_evidence_gap"] == 2
    assert missing.summary["by_severity"]["error"] == 2

    mismatch = audit_evidence_records(
        products=[
            {
                "id": 51,
                "title": "高中英语作文模板电子资料",
                "price": 19.9,
                "share_url": "https://xhs.example/item/51",
                "evidence_grade": "A",
                "low_follower_verified": 1,
            }
        ],
        notes=[
            {
                "id": 60,
                "product_id": 51,
                "source": "related_note_card",
                "page_kind": "note_detail",
                "author_name": "Author A",
                "likes": 1200,
                "published_days_ago": 2,
            },
            {
                "id": 61,
                "product_id": 51,
                "source": "author_profile_from_note",
                "page_kind": "account_profile",
                "author_name": "Author B",
                "follower_count": 188,
            },
        ],
    )
    assert "low_follower_author_mismatch" in codes(mismatch)


def test_clean_low_follower_candidate_has_no_quality_issues():
    report = audit_evidence_records(
        products=[
            {
                "id": 70,
                "title": "小学作文30次小练笔电子资料",
                "price": 9.9,
                "share_url": "https://xhs.example/item/70",
                "evidence_grade": "A",
                "low_follower_verified": 1,
            }
        ],
        observations=[
            {
                "id": 71,
                "product_id": 70,
                "screenshot_path": "captures/70.png",
                "screenshot_exists": True,
                "observed_at": "2026-07-28T10:00:00+08:00",
                "cumulative_sales_min": 1100,
                "sales_24h_min": 100,
                "sales_7d_min": 500,
                "sales_30d_min": 900,
            }
        ],
        notes=[
            {
                "id": 72,
                "product_id": 70,
                "source": "related_note_card",
                "page_kind": "note_detail",
                "author_name": "小红点点",
                "likes": 120,
                "published_days_ago": 2,
            },
            {
                "id": 73,
                "product_id": 70,
                "source": "author_profile_from_note",
                "page_kind": "account_profile",
                "author_name": "小红点点",
                "follower_count": 188,
            },
        ],
        search_evidence=[
            {
                "id": 74,
                "product_id": 70,
                "observation_id": 71,
                "source_keyword": "小学作文",
                "task_keyword": "小学作文",
                "valid": True,
                "search_screenshot_exists": True,
            }
        ],
        allowed_keywords=["小学作文"],
        now=datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
    )

    assert report.issues == []
    assert report.summary["issue_count"] == 0
    assert report.summary["has_errors"] is False


def test_stale_observation_is_reported_against_supplied_now():
    report = audit_evidence_records(
        observations=[
            {
                "id": 80,
                "product_id": 80,
                "title": "职场 SOP 模板",
                "price": 39.9,
                "share_url": "https://xhs.example/item/80",
                "screenshot_path": "captures/80.png",
                "observed_at": "2026-06-01T10:00:00+08:00",
            }
        ],
        now="2026-07-28T12:00:00+08:00",
    )

    issue = next(issue for issue in report.issues if issue.code == "observation_stale")
    assert issue.severity == "warning"
    assert issue.details["age_days"] > 30
