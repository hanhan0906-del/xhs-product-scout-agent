import json
from datetime import datetime
from pathlib import Path

from xhs_scout.keyword_portfolio import (
    PortfolioPolicy,
    build_keyword_candidates,
    build_rotation_plan,
    decide_pause,
    normalize_keyword,
)


NOW = datetime.fromisoformat("2026-07-28T10:00:00+08:00")


def _config():
    return {
        "version": 1,
        "policy": {
            "hourly_budget": 3,
            "per_round_budget": 2,
            "keyword_cooldown_hours": 24,
            "core_share": 0.5,
            "max_generated_per_category": 2,
            "max_consecutive_failures": 2,
            "failure_pause_hours": 3,
        },
        "categories": [
            {
                "id": "k12",
                "label": "K12",
                "layer": "core",
                "priority": 90,
                "seed_terms": [" 小学学习资料 ", "小学 学习资料", "阅读理解"],
                "modifiers": ["电子版", "PDF资料"],
            },
            {
                "id": "office",
                "label": "办公模板",
                "layer": "explore",
                "priority": 70,
                "seed_terms": ["Excel模板", "Notion模板"],
                "modifiers": ["可复制"],
            },
        ],
    }


def test_normalize_keyword_dedupes_spacing_case_and_punctuation():
    assert normalize_keyword(" PDF 资料｜电子版 ") == "pdf资料电子版"
    assert normalize_keyword("小学 学习-资料") == normalize_keyword("小学学习资料")


def test_candidates_include_core_explore_combinations_and_dedupe():
    candidates = build_keyword_candidates(_config())
    normalized = [item.normalized for item in candidates]

    assert len(normalized) == len(set(normalized))
    assert "小学学习资料" in normalized
    assert "小学学习资料电子版" in normalized
    assert "excel模板" in normalized
    assert {item.layer for item in candidates} == {"core", "explore"}


def test_dimension_combinations_are_bounded_auditable_and_keep_explore_terms():
    config = _config()
    config["policy"].update(
        {
            "max_generated_per_category": 3,
            "max_total_candidates": 20,
        }
    )
    config["categories"][0].update(
        {
            "modifiers": [],
            "product_forms": ["电子版", "资料包"],
            "audiences": ["小学生"],
            "scenarios": ["期末复习"],
            "stage_modifiers": ["暑假"],
            "explore_terms": ["中考冲刺资料"],
            "dimension_budgets": {
                "product_forms": 1,
                "audiences": 1,
                "scenarios": 0,
                "stage_modifiers": 0,
                "explore_terms": 1,
            },
            "seed_source_ids": ["xlsx_import"],
            "dimension_source_ids": ["offline_design"],
            "max_generated": 3,
        }
    )

    candidates = build_keyword_candidates(config)
    by_kind = {
        item.combination_kind: item
        for item in candidates
        if item.category_id == "k12"
    }

    assert len(candidates) <= 20
    assert by_kind["seed"].source_ids == ("xlsx_import",)
    assert by_kind["product_forms"].components == ("小学学习资料", "电子版")
    assert by_kind["audiences"].keyword == "小学生 小学学习资料"
    assert by_kind["explore_term"].layer == "explore"
    assert by_kind["explore_term"].source_ids == ("offline_design",)


def test_rotation_plan_respects_round_budget_layers_and_serializes():
    plan = build_rotation_plan(_config(), now=NOW, hourly_used=0, rotation_cursor=0)

    assert len(plan["selected"]) == 2
    assert [item["layer"] for item in plan["selected"]] == ["core", "explore"]
    assert plan["budget"]["hourly_remaining"] == 3
    assert plan["rotation"]["next_cursor"] != plan["rotation"]["input_cursor"]
    json.dumps(plan, ensure_ascii=False)


def test_two_slot_plan_reserves_one_explore_keyword():
    config = _config()
    config["policy"].update({"core_share": 0.9, "min_explore_per_round": 1})

    plan = build_rotation_plan(config, now=NOW)

    assert [item["layer"] for item in plan["selected"]] == ["core", "explore"]
    assert plan["budget"]["min_explore_per_round"] == 1
    assert plan["scope"] == {
        "mode": "finite_offline_portfolio",
        "full_site_exhaustive": False,
        "production_queue_write": False,
    }


def test_hourly_budget_caps_round_selection():
    plan = build_rotation_plan(_config(), now=NOW, hourly_used=2)

    assert plan["budget"]["round_budget"] == 1
    assert len(plan["selected"]) == 1


def test_keyword_24h_cooldown_defers_recent_keyword():
    first = build_rotation_plan(_config(), now=NOW)["selected"][0]
    history = {first["normalized"]: {"last_started_at": "2026-07-27T11:00:00+08:00"}}

    plan = build_rotation_plan(_config(), now=NOW, keyword_history=history)

    assert first["normalized"] not in {item["normalized"] for item in plan["selected"]}
    assert any(
        item["normalized"] == first["normalized"]
        and item["reason"] == "keyword_cooldown"
        and item["cooldown_until"] == "2026-07-28T11:00:00+08:00"
        for item in plan["deferred"]
    )


def test_cooldown_allows_keyword_after_24h():
    first = build_rotation_plan(_config(), now=NOW)["selected"][0]
    history = {first["normalized"]: "2026-07-27T09:59:00+08:00"}

    plan = build_rotation_plan(_config(), now=NOW, keyword_history=history)

    assert first["normalized"] in {item["normalized"] for item in plan["selected"]}


def test_failure_pause_is_pure_and_temporary():
    pause = decide_pause(
        {"consecutive_failures": 2},
        now=NOW,
        policy=PortfolioPolicy(max_consecutive_failures=2, failure_pause_hours=3),
    )

    assert pause == {
        "paused": True,
        "scope": "global",
        "severity": "failure",
        "reason": "consecutive failures reached 2",
        "resume_at": "2026-07-28T13:00:00+08:00",
        "manual_resume_required": False,
    }


def test_risk_pause_requires_manual_resume_and_blocks_plan():
    plan = build_rotation_plan(
        _config(),
        now=NOW,
        pause_input={"risk_stop_reason": "captcha detected"},
    )

    assert plan["paused"] is True
    assert plan["pause"]["manual_resume_required"] is True
    assert plan["selected"] == []


def test_repository_config_is_valid_and_bounded():
    raw = json.loads(open("config/keyword_portfolio.json", encoding="utf-8").read())
    candidates = build_keyword_candidates(raw)
    plan = build_rotation_plan(raw, now=NOW, hourly_used=0)

    assert raw["policy"]["per_round_budget"] <= raw["policy"]["hourly_budget"]
    assert len(candidates) <= raw["policy"]["max_total_candidates"]
    assert {"core", "explore"}.issubset({item.layer for item in candidates})
    assert len(plan["selected"]) == raw["policy"]["per_round_budget"]
    assert plan["rotation"]["total_candidates"] == len(candidates)
    assert plan["rotation"]["core_candidates"] > 0
    assert plan["rotation"]["explore_candidates"] > 0
    assert plan["circuit_breaker"]["max_consecutive_failures"] == 2
    json.dumps(plan, ensure_ascii=False)


def test_repository_config_covers_every_imported_seed_and_labels_sources():
    raw = json.loads(Path("config/keyword_portfolio.json").read_text(encoding="utf-8"))
    source_terms = [
        line.strip()
        for line in Path("config/seed_keywords.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    configured_seeds = [
        seed
        for category in raw["categories"]
        for seed in category.get("seed_terms", [])
    ]

    assert len(source_terms) == 78
    assert {normalize_keyword(item) for item in configured_seeds} == {
        normalize_keyword(item) for item in source_terms
    }
    assert raw["source_registry"]["seed_keywords_xlsx_import"]["term_count"] == 78
    assert all(
        category["seed_source_ids"] == ["seed_keywords_xlsx_import"]
        and category["dimension_source_ids"] == ["offline_dimension_design_2026_07_29"]
        for category in raw["categories"]
    )


def test_total_cap_preserves_core_and_explore_layers():
    config = _config()
    config["policy"].update(
        {
            "max_total_candidates": 4,
            "core_share": 0.5,
        }
    )

    candidates = build_keyword_candidates(config)

    assert len(candidates) == 4
    assert sum(item.layer == "core" for item in candidates) == 2
    assert sum(item.layer == "explore" for item in candidates) == 2
