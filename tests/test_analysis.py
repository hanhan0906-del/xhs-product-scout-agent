from xhs_scout.analysis import analyze_candidate, extract_trend_metrics


def test_analyze_candidate_builds_specific_learning_material_directions():
    row = {
        "title": "小学语文二升三阅读理解暑假讲义",
        "shop_name": "资料店",
        "price": 29.9,
        "screenshot_path": "shot.png",
        "share_url": "https://example.test/product",
        "evidence_grade": "B",
        "score": 56.2,
        "cumulative_sales_min": 4067,
        "sales_30d_min": 3000,
        "positive_reviews_30d_min": 2000,
        "interested_30d_min": 9000,
        "search_source_keyword": "阅读理解",
        "search_result_rank": 1,
        "search_probe_dir": "data/probes/search",
        "latest_note_author_name": "小红点点",
        "latest_note_likes": 6460,
        "latest_note_published_days_ago": 240,
        "latest_profile_author_name": "小红点点",
        "latest_profile_follower_count": 5600,
        "low_follower_verified": 0,
    }

    result = analyze_candidate(row, ["近30天购买强"])

    assert "学习资料" in result["tags"]
    assert "近30天购买下限：3000" in result["trend_metrics"]
    assert any("近30天新增指标突出" in item for item in result["inferences"])
    assert any("版权、年份版本、题源" in item for item in result["risks"])
    assert any("发布距今 240 天" in item for item in result["risks"])
    assert any("不能自动升 A" in item for item in result["gaps"])
    assert any("错题归因表" in item for item in result["originality_directions"])
    assert any("答案解析步骤" in item for item in result["originality_directions"])
    assert result["confidence"]["level"] == "中"


def test_analyze_candidate_marks_missing_low_follower_chain_as_gap():
    row = {
        "title": "飞书人生管理系统模板",
        "evidence_grade": "C",
        "score": 42.8,
        "sales_30d_min": 700,
        "favorites_30d_min": 100,
        "sales_surging": 1,
    }

    result = analyze_candidate(row)

    assert {"模板工具", "效率管理"}.issubset(set(result["tags"]))
    assert any(metric["key"] == "sales_surging" for metric in extract_trend_metrics(row))
    assert any("缺少关联公开笔记证据" in item for item in result["gaps"])
    assert any("模板类商品同质化强" in item for item in result["risks"])
    assert any("组合工作流" in item for item in result["originality_directions"])
    assert result["confidence"]["score"] < 70


def test_analyze_candidate_marks_latest_invalid_search_and_manual_review():
    row = {
        "title": "职场新人 SOP 模板",
        "assessment_status": "needs_review",
        "evidence_grade": "B",
        "score": 61,
        "sales_30d_min": 700,
        "search_source_keyword": "职场资料",
        "search_result_rank": 2,
        "search_evidence_valid": 0,
        "search_invalid_reason": "keyword_mismatch",
    }

    result = analyze_candidate(row)

    assert any("最新搜索证据已失效" in item for item in result["gaps"])
    assert any("不能沿用更早记录" in item for item in result["gaps"])
    assert any("必须由人工复核" in item for item in result["risks"])
    assert any("禁止用更早有效记录替代" in item for item in result["risks"])
    assert any("状态 已失效" in item for item in result["facts"])
