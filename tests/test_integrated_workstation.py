import json
from pathlib import Path

from fastapi import HTTPException

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    record_note_observation,
    record_search_result_evidence,
    set_monitor_state,
    utcnow,
)
from xhs_scout.reports import generate_candidate_report
from xhs_scout.web import LowFollowerEvidence, create_app
from xhs_scout.workflow import complete_task_from_observation, start_task


def _routes(settings):
    app = create_app(settings)
    return {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}


def _write_portfolio_config(settings):
    config_dir = settings.root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "keyword_portfolio.json").write_text(
        json.dumps(
            {
                "version": 1,
                "policy": {
                    "hourly_budget": 2,
                    "per_round_budget": 2,
                    "keyword_cooldown_hours": 24,
                    "core_share": 0.5,
                },
                "categories": [
                    {
                        "id": "study",
                        "label": "Study",
                        "layer": "core",
                        "priority": 90,
                        "seed_terms": ["study printables"],
                        "modifiers": ["pdf"],
                    },
                    {
                        "id": "office",
                        "label": "Office",
                        "layer": "explore",
                        "priority": 70,
                        "seed_terms": ["notion template"],
                        "modifiers": [],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _seed_candidate(settings, *, with_public_chain=False):
    with connect(settings.db_path) as conn:
        now = utcnow()
        enqueue(conn, ["study printables"])
        task_id = conn.execute("SELECT id FROM search_tasks").fetchone()[0]
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, shop_name, share_url, price, is_virtual,
                virtual_confidence, first_seen_at, last_seen_at
            ) VALUES ('integrated-fp', 'Integrated study planner', 'Template Lab',
                      'https://xhs.example/item/integrated', 29.9, 1, 1, ?, ?)
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for sales, interested in ((1000, 1200), (1800, 2600)):
            conn.execute(
                """
                INSERT INTO observations(
                    product_id, observed_at, source, screenshot_path, raw_text,
                    cumulative_sales_min, sales_7d_min, sales_30d_min,
                    positive_reviews_30d_min, interested_7d_min,
                    raw_signals_json
                ) VALUES (?, ?, 'test', NULL, 'trend text', ?, 500, ?, 300, ?, '{}')
                """,
                (product_id, now, sales, sales, interested),
            )
        observation_id = conn.execute(
            "SELECT id FROM observations WHERE product_id=? ORDER BY id DESC LIMIT 1",
            (product_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score,
                low_follower_verified, reasons_json, status
            ) VALUES (?, ?, 'B', 67.5, 0, '["trend"]', 'candidate')
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
            source_keyword="study printables",
            result_rank=1,
            page_kind="product_detail",
            search_probe_dir="tmp/probes/search-integrated",
            search_screenshot_path=None,
            text_excerpt="study printables Integrated study planner",
        )
        if with_public_chain:
            record_note_observation(
                conn,
                product_id=product_id,
                source="related_note_card",
                screenshot_path=None,
                probe_dir="tmp/probes/note-integrated",
                page_kind="note_detail",
                raw_text="Author A note",
                author_name="Author A",
                likes=1200,
                collects=20,
                comments=5,
                published_days_ago=2,
            )
            record_note_observation(
                conn,
                product_id=product_id,
                source="author_profile_from_note",
                screenshot_path=None,
                probe_dir="tmp/probes/profile-integrated",
                page_kind="account_profile",
                raw_text="Author A profile",
                author_name="Author A",
                follower_count=188,
                likes=9000,
            )
        set_monitor_state(conn, "last_heartbeat", now)
        set_monitor_state(conn, "last_block_reason", "offline integration marker")
    return product_id


def test_status_insight_fields_are_json_serializable(tmp_path):
    settings = Settings.load(tmp_path)
    _write_portfolio_config(settings)
    _seed_candidate(settings, with_public_chain=True)

    status = _routes(settings)["/api/status"]()

    encoded = json.dumps(status, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["products"] == 1
    assert decoded["observations"] == 2
    assert decoded["candidates"] == 1
    assert decoded["quality"]["summary"]["by_severity"]
    assert decoded["quality"]["audited_at"]
    assert decoded["digest"]["stats"]["period"] == "daily"
    assert decoded["portfolio"]["budget"]["per_round_budget"] == 1
    assert decoded["recent"][0]["reasons"] == ["trend"]


def test_integrated_insight_routes_cover_daily_weekly_quality_and_portfolio(tmp_path):
    settings = Settings.load(tmp_path)
    _write_portfolio_config(settings)
    _seed_candidate(settings, with_public_chain=True)
    routes = _routes(settings)

    daily = routes["/api/digest/{period}"]("daily")
    weekly = routes["/api/digest/{period}"]("weekly")
    quality = routes["/api/quality"]()
    portfolio = routes["/api/portfolio"]()

    assert daily["stats"]["period"] == "daily"
    assert weekly["stats"]["period"] == "weekly"
    assert daily["stats"]["candidates_total"] == 1
    assert quality["scope"]["products"] == 1
    assert quality["summary"]["by_code"]["screenshot_missing"] >= 1
    assert portfolio["version"] == 1
    assert portfolio["budget"]["round_budget"] == 1
    assert portfolio["selected"]

    try:
        routes["/api/digest/{period}"]("monthly")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("monthly digest route should reject unsupported periods")


def test_candidate_report_contains_digest_summary_and_quality_section(tmp_path):
    settings = Settings.load(tmp_path)
    _write_portfolio_config(settings)
    _seed_candidate(settings, with_public_chain=True)

    output = settings.reports_dir / "integrated-report.md"
    result = generate_candidate_report(settings, output_path=output, limit=5)
    report = Path(result["report_path"]).read_text(encoding="utf-8")

    assert result["candidate_count"] == 1
    assert result["digest_alert_count"] >= 0
    assert result["quality_issue_count"] >= 1
    assert "Integrated study planner" in report
    assert "24" in report
    assert "error / screenshot_missing" in report
    assert "warning / low_follower_evidence_gap" not in report


def test_manual_low_follower_input_cannot_promote_without_public_note_profile_chain(tmp_path):
    settings = Settings.load(tmp_path)
    product_id = _seed_candidate(settings, with_public_chain=False)
    verify = _routes(settings)["/api/verify-low-follower/{product_id}"]

    result = verify(
        product_id,
        LowFollowerEvidence(
            author_name="Manual Author",
            follower_count=188,
            likes=1200,
            published_days_ago=2,
            source_note="manual-only",
        ),
    )

    assert result["manual_threshold_met"] is True
    assert result["promotion"]["verified"] is False
    assert result["promotion"]["skip_reason"] == "note/profile evidence incomplete"
    assert result["grade"] == "B"
    assert result["status"] == "needs_review"
    assert result["verified"] is False
    assert "trend" in result["reasons"]
    assert len(result["reasons"]) >= 3
    with connect(settings.db_path) as conn:
        latest = conn.execute(
            """
            SELECT evidence_grade, low_follower_verified, status
            FROM candidate_assessments
            WHERE product_id=? ORDER BY id DESC LIMIT 1
            """,
            (product_id,),
        ).fetchone()
    assert latest["evidence_grade"] == "B"
    assert latest["low_follower_verified"] == 0
    assert latest["status"] == "needs_review"
