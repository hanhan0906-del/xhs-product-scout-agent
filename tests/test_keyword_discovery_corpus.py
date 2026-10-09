from __future__ import annotations

import builtins
import sqlite3

import pytest

from xhs_scout.keyword_discovery import (
    DiscoveryPolicy,
    discover_keyword_candidates,
)


def _candidate_by_normalized(result, normalized):
    return next(
        item for item in result["candidates"] if item["normalized"] == normalized
    )


def test_business_corpus_extracts_supported_virtual_product_shapes():
    result = discover_keyword_candidates(
        products=[
            {
                "id": "k12-title",
                "title": "2026小学三年级数学暑假预习资料电子版可打印",
            },
            {
                "id": "shop-segments",
                "shop_public_text": "欢迎光临官方旗舰店｜Excel项目进度表模板",
            },
        ],
        successful_searches=[
            "小学三年级数学暑假预习资料",
            "职场新人周报模板",
            "教资笔试真题题库",
            "AI提示词工作流",
            "短视频剪辑视频课程",
        ],
        trend_labels=[
            "职场新人周报模板",
            "教资笔试真题题库",
            "AI提示词工作流",
        ],
    )

    normalized = {item["normalized"] for item in result["candidates"]}
    assert {
        "小学三年级数学暑假预习资料",
        "职场新人周报模板",
        "教资笔试真题题库",
        "ai提示词工作流",
        "短视频剪辑视频课程",
        "excel项目进度表模板",
    }.issubset(normalized)
    assert all(
        item["review_status"] == "pending_review" for item in result["candidates"]
    )
    assert _candidate_by_normalized(
        result, "职场新人周报模板"
    )["suggested_layer"] == "core"
    assert _candidate_by_normalized(
        result, "短视频剪辑视频课程"
    )["suggested_layer"] == "explore"
    assert all("欢迎光临" not in item["keyword"] for item in result["candidates"])


def test_global_dedupe_aggregates_sources_and_counts_support_once_per_source():
    result = discover_keyword_candidates(
        products=[
            {
                "id": "product-1",
                "title": "职场新人周报模板",
                "trend_labels": ["职场新人周报模板"],
            }
        ],
        successful_searches=[
            {
                "id": "search-1",
                "keyword": "职场 新人-周报模板",
                "product_id": "product-1",
            },
            {
                "id": "search-1",
                "keyword": "职场 新人-周报模板",
                "product_id": "product-1",
            },
        ],
        trend_labels=[
            {
                "id": "external-trend-1",
                "label": "职场新人周报模板",
                "product_id": "product-2",
            }
        ],
    )

    matches = [
        item
        for item in result["candidates"]
        if item["normalized"] == "职场新人周报模板"
    ]
    assert len(matches) == 1
    candidate = matches[0]
    assert candidate["suggested_layer"] == "core"
    assert candidate["support"] == {
        "score": 5.5,
        "evidence_count": 4,
        "distinct_products": 2,
        "distinct_source_types": 3,
        "source_types": [
            "product_title",
            "successful_search",
            "trend_label",
        ],
    }
    assert candidate["source_products"] == ["product-1", "product-2"]
    assert len(
        {
            (
                item["source_type"],
                item["source_id"],
                item["product_id"],
                item["source_keyword"],
            )
            for item in candidate["evidence"]
        }
    ) == candidate["support"]["evidence_count"]


@pytest.mark.parametrize(
    ("keyword", "reason"),
    [
        ("欢迎光临本店资料包", "store_boilerplate"),
        ("客服在线点击查看课程", "store_boilerplate"),
        ("￥9.9资料包", "price_or_count"),
        ("www.x.cn/资料", "url"),
        ("AI工具破解版", "piracy_or_evasion"),
        ("盗版课程资料", "piracy_or_evasion"),
        ("免登录提示词", "piracy_or_evasion"),
        ("加微信领取资料", "contact_or_diversion"),
        ("购买链接自动发货题库", "transaction_prompt"),
        ("这是一个超过十八个汉字的超长直接搜索关键词资料", "too_long"),
    ],
)
def test_high_risk_noise_and_invalid_direct_keywords_are_filtered(keyword, reason):
    result = discover_keyword_candidates(successful_searches=[keyword])

    assert result["candidates"] == []
    assert len(result["filtered"]) == 1
    assert result["filtered"][0]["reason"] == reason


@pytest.mark.parametrize(
    ("keyword", "risk_flag"),
    [
        ("内部资料全套合集", "copyright_unclear"),
        ("独家整理全网合集", "copyright_unclear"),
        ("免费领取学习资料", "free_claim"),
    ],
)
def test_soft_risk_corpus_stays_pending_but_is_forced_to_explore(
    keyword,
    risk_flag,
):
    result = discover_keyword_candidates(
        successful_searches=[keyword],
        trend_labels=[keyword],
    )

    candidate = _candidate_by_normalized(result, keyword)
    assert candidate["support"]["score"] == 3.25
    assert candidate["support"]["distinct_source_types"] == 2
    assert candidate["risk_flags"] == [risk_flag]
    assert candidate["suggested_layer"] == "explore"
    assert candidate["review_status"] == "pending_review"


def test_existing_portfolio_dedupes_globally_across_all_source_shapes():
    result = discover_keyword_candidates(
        products=[
            {
                "id": "p1",
                "title": "PDF资料",
                "source_keyword": "PDF 资料",
                "trend_labels": ["pdf-资料"],
            }
        ],
        successful_searches=["ＰＤＦ资料"],
        trend_labels=["PDF｜资料"],
        existing_keywords=[{"normalized": "pdf资料"}],
    )

    assert result["candidates"] == []
    assert result["stats"]["existing_portfolio_occurrences"] == 5
    assert {
        item["reason"] for item in result["filtered"]
    } == {"already_in_portfolio"}
    assert {item["normalized"] for item in result["filtered"]} == {"pdf资料"}


def test_per_round_cap_reports_truncation_and_never_writes_or_opens_a_database(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    real_open = builtins.open

    def reject_writes(file, mode="r", *args, **kwargs):
        if any(marker in mode for marker in ("w", "a", "x", "+")):
            pytest.fail(f"unexpected file write: {file!s} mode={mode}")
        return real_open(file, mode, *args, **kwargs)

    def reject_database(*args, **kwargs):
        pytest.fail("offline discovery must not open SQLite")

    monkeypatch.setattr(builtins, "open", reject_writes)
    monkeypatch.setattr(sqlite3, "connect", reject_database)
    result = discover_keyword_candidates(
        successful_searches=[
            "语文学习资料",
            "数学学习资料",
            "英语学习资料",
            "物理学习资料",
            "化学学习资料",
            "生物学习资料",
        ],
        policy=DiscoveryPolicy(max_output=3),
    )

    assert len(result["candidates"]) == 3
    assert result["stats"]["unique_candidates_before_cap"] == 6
    assert result["stats"]["truncated_candidates"] == 3
    assert result["scope"] == {
        "mode": "offline_keyword_suggestions",
        "database_access": False,
        "production_queue_write": False,
        "search_trigger": False,
        "human_review_required": True,
    }
    assert list(tmp_path.iterdir()) == []


def test_same_source_normalization_variants_should_not_inflate_support():
    result = discover_keyword_candidates(
        successful_searches=[
            {
                "id": "same-search-row",
                "keyword": "职场 新人-周报模板",
                "product_id": "same-product",
            },
            {
                "id": "same-search-row",
                "keyword": "职场新人周报模板",
                "product_id": "same-product",
            },
        ]
    )

    candidate = _candidate_by_normalized(result, "职场新人周报模板")
    assert candidate["support"]["evidence_count"] == 1
    assert candidate["support"]["score"] == 2.0


def test_ocr_gibberish_should_be_filtered_instead_of_becoming_explore_candidates():
    result = discover_keyword_candidates(
        successful_searches=[
            "资枓丨模扳丨课桯",
            "lI1|O0资料",
        ]
    )

    assert result["candidates"] == []
    assert len(result["filtered"]) == 2


def test_overlong_title_extraction_should_start_at_a_semantic_boundary():
    result = discover_keyword_candidates(
        products=[
            {
                "id": "long-title",
                "title": (
                    "2026年新版这是一个很长的商品标题专为"
                    "小学三年级数学暑假预习资料电子版可打印"
                ),
            }
        ]
    )

    candidate = result["candidates"][0]
    assert candidate["keyword"] == "小学三年级数学暑假预习资料"
    assert candidate["review_status"] == "pending_review"
