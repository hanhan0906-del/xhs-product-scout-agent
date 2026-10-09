from xhs_scout.config import Settings
from xhs_scout.db import connect
from xhs_scout.web import create_app
from xhs_scout.workbench_ui import render_workbench_html


def _route(settings):
    return next(
        route
        for route in create_app(settings).routes
        if getattr(route, "path", None) == "/api/keyword-combination-review"
    )


def test_keyword_combination_review_is_get_only_and_fail_closed_without_data(
    tmp_path,
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path):
        pass
    route = _route(settings)
    assert route.methods == {"GET"}
    result = route.endpoint()
    assert result["generation_stage"] == "not_ready"
    assert result["candidate_count"] == 0
    assert result["candidates"] == []
    assert result["scope"]["database_access"] == "sqlite_mode_ro_query_only"
    assert result["scope"]["production_queue_write"] is False
    assert result["scope"]["approval_write"] is False
    assert result["scope"]["approval_endpoint"] is False
    assert result["scope"]["writes_queue"] is False
    assert result["scope"]["search_trigger"] is False
    assert result["scope"]["search_execution"] is False
    assert result["scope"]["monitor_authorization"] is False
    assert result["scope"]["soak_authorization"] is False


def test_keyword_combination_stays_internal_when_classified_pool_is_shown():
    html = render_workbench_html()

    assert 'id="keywordCombinationReviewPanel"' not in html
    assert "新策略组合候选 · 只读审核" not in html
    assert "分类关键词" in html
    assert 'keywordPool: "/api/keyword-pool"' in html
    assert "fetch(API_ROUTES.keywordPool)" in html
    assert 'keywordCombinationReview: "/api/keyword-combination-review"' in html
    assert "fetch(API_ROUTES.keywordCombinationReview)" in html
    assert "production_queue_write === false" in html
    assert "search_execution === false" in html
