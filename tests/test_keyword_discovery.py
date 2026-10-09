import json

from xhs_scout.keyword_discovery import (
    DiscoveryPolicy,
    discover_keyword_candidates,
)


def _products():
    return [
        {
            "id": 101,
            "title": "小学三年级数学暑假预习资料电子版",
            "shop_public_text": "三年级数学预习资料｜欢迎光临官方旗舰店",
            "source_keyword": "小学数学预习",
            "trend_labels": ["#暑假预习资料"],
        },
        {
            "id": 102,
            "title": "三年级数学预习资料 可打印",
            "shop_public_text": "小学数学学习资料",
            "source_keyword": "三年级数学资料",
            "trend_labels": ["暑假预习资料"],
        },
    ]


def test_discovery_is_pure_offline_and_json_serializable():
    result = discover_keyword_candidates(
        products=_products(),
        successful_searches=["数学暑假资料"],
        trend_labels=["期末复习资料"],
        existing_keywords=[],
    )

    assert result["scope"] == {
        "mode": "offline_keyword_suggestions",
        "database_access": False,
        "production_queue_write": False,
        "search_trigger": False,
        "human_review_required": True,
    }
    assert all(item["review_status"] == "pending_review" for item in result["candidates"])
    json.dumps(result, ensure_ascii=False)


def test_aggregates_product_keyword_and_trend_provenance():
    result = discover_keyword_candidates(
        products=_products(),
        successful_searches=[
            {"id": "search-1", "keyword": "暑假预习资料", "product_id": 103}
        ],
    )
    candidate = next(
        item for item in result["candidates"] if item["normalized"] == "暑假预习资料"
    )

    assert candidate["suggested_layer"] == "core"
    assert candidate["support"]["score"] >= 3
    assert candidate["support"]["distinct_products"] == 3
    assert candidate["support"]["source_types"] == [
        "successful_search",
        "trend_label",
    ]
    assert candidate["source_products"] == ["101", "102", "103"]
    assert "数学暑假资料" not in candidate["source_keywords"]
    assert "暑假预习资料" in candidate["source_keywords"]


def test_dedupes_against_t20_portfolio_normalization():
    result = discover_keyword_candidates(
        products=_products(),
        existing_keywords=[
            {"keyword": "小学 数学-预习"},
            {"normalized": "暑假预习资料"},
        ],
    )

    returned = {item["normalized"] for item in result["candidates"]}
    assert "小学数学预习" not in returned
    assert "暑假预习资料" not in returned
    assert result["stats"]["existing_portfolio_occurrences"] >= 2
    assert all(
        item["reason"] == "already_in_portfolio"
        for item in result["filtered"]
        if item["normalized"] in {"小学数学预习", "暑假预习资料"}
    )


def test_filters_transaction_piracy_marketing_and_store_noise():
    result = discover_keyword_candidates(
        successful_searches=[
            "加微信领取资料",
            "破解版软件",
            "限时优惠资料包",
            "欢迎光临官方旗舰店",
            "￥9.9",
            "正常学习资料",
        ],
    )

    assert [item["keyword"] for item in result["candidates"]] == ["正常学习资料"]
    reasons = {item["reason"] for item in result["filtered"]}
    assert {
        "contact_or_diversion",
        "piracy_or_evasion",
        "marketing_noise",
        "store_boilerplate",
        "price_or_count",
    }.issubset(reasons)


def test_soft_risk_stays_visible_but_cannot_be_core():
    result = discover_keyword_candidates(
        successful_searches=["免费领取学习资料"],
        trend_labels=["免费领取学习资料"],
    )
    candidate = result["candidates"][0]

    assert candidate["risk_flags"] == ["free_claim"]
    assert candidate["suggested_layer"] == "explore"
    assert candidate["review_status"] == "pending_review"


def test_single_source_suggestion_is_explore_even_with_trusted_weight():
    result = discover_keyword_candidates(
        successful_searches=["职场新人入门手册"],
    )

    assert result["candidates"][0]["support"]["score"] == 2.0
    assert result["candidates"][0]["suggested_layer"] == "explore"


def test_title_extraction_is_anchor_based_and_bounded():
    result = discover_keyword_candidates(
        products=[
            {
                "id": "p1",
                "title": "2026最新版小学三年级数学暑假预习资料电子版可打印",
                "shop_public_text": "没有领域锚点的普通品牌宣传文字",
            }
        ],
        policy={"max_output": 10, "max_keyword_chars": 18},
    )

    assert result["candidates"]
    assert all(len(item["normalized"]) <= 18 for item in result["candidates"])
    assert all("普通品牌宣传文字" not in item["keyword"] for item in result["candidates"])


def test_output_cap_prevents_candidate_explosion_and_reports_truncation():
    result = discover_keyword_candidates(
        successful_searches=[f"{name}学习资料" for name in "语数英物化生政史地"],
        policy=DiscoveryPolicy(max_output=3),
    )

    assert len(result["candidates"]) == 3
    assert result["stats"]["unique_candidates_before_cap"] == 9
    assert result["stats"]["truncated_candidates"] == 6


def test_duplicate_evidence_does_not_inflate_support():
    product = {
        "id": 1,
        "title": "小学数学学习资料",
        "source_keyword": "小学数学资料",
    }
    result = discover_keyword_candidates(products=[product, dict(product)])
    candidate = next(
        item for item in result["candidates"] if item["normalized"] == "小学数学资料"
    )

    assert candidate["support"]["evidence_count"] == 1
    assert candidate["support"]["score"] == 2.0


def test_same_source_display_variants_do_not_inflate_support():
    result = discover_keyword_candidates(
        successful_searches=[
            {
                "id": "same-row",
                "keyword": "职场 新人-周报模板",
                "product_id": "same-product",
            },
            {
                "id": "same-row",
                "keyword": "职场新人周报模板",
                "product_id": "same-product",
            },
        ]
    )
    candidate = next(
        item for item in result["candidates"] if item["normalized"] == "职场新人周报模板"
    )

    assert candidate["support"]["evidence_count"] == 1
    assert candidate["support"]["score"] == 2.0
    assert candidate["evidence"][0]["source_keyword"] == "职场 新人-周报模板"


def test_filters_narrow_ocr_confusion_patterns_without_blocking_normal_mixed_text():
    result = discover_keyword_candidates(
        successful_searches=[
            "资枓丨模扳丨课桯",
            "lI1|O0资料",
            "AI 101学习资料",
        ]
    )

    assert [item["normalized"] for item in result["candidates"]] == ["ai101学习资料"]
    assert [item["reason"] for item in result["filtered"]] == [
        "ocr_gibberish",
        "ocr_gibberish",
    ]


def test_overlong_title_window_drops_only_dangling_leading_function_word():
    result = discover_keyword_candidates(
        products=[
            {
                "id": "long-title",
                "title": (
                    "2026年新版这是一个很长的商品标题专为"
                    "小学三年级数学暑假预习资料电子版可打印"
                ),
            },
            {
                "id": "short-title",
                "title": "为小学生准备的学习资料",
            },
        ]
    )
    candidates = {
        item["normalized"]: item for item in result["candidates"]
    }

    assert (
        candidates["小学三年级数学暑假预习资料"]["keyword"]
        == "小学三年级数学暑假预习资料"
    )
    assert candidates["小学三年级数学暑假预习资料"]["review_status"] == "pending_review"
    assert "为小学生准备的学习资料" in candidates


def test_existing_normalized_mapping_is_supported():
    result = discover_keyword_candidates(
        successful_searches=["PDF 资料"],
        existing_keywords=[{"normalized": "pdf资料"}],
    )

    assert result["candidates"] == []
    assert result["filtered"][0]["reason"] == "already_in_portfolio"
