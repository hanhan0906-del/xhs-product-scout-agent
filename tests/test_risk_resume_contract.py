import io
import json
import sys

import pytest
from fastapi import HTTPException

from xhs_scout import cli
from xhs_scout.config import Settings
from xhs_scout.db import (
    RiskConfirmationError,
    RiskStopActiveError,
    connect,
    get_monitor_state,
    recent_run_events,
    resume_monitor_after_risk,
    set_monitor_desired_state,
    set_monitor_state,
)
from xhs_scout.web import RiskResumeRequest, create_app
from xhs_scout.workbench_ui import render_workbench_html


RISK_REASON = "安全限制 / 设备异常"


def _routes(app):
    return {
        route.path: route.endpoint
        for route in app.routes
        if hasattr(route, "endpoint")
    }


def test_ordinary_resume_preserves_active_risk_stop(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "desired_state", "paused")
        set_monitor_state(conn, "risk_stop_reason", RISK_REASON)

        with pytest.raises(RiskStopActiveError):
            set_monitor_desired_state(conn, "running")

        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == RISK_REASON


def test_explicit_risk_resume_requires_exact_reason_and_records_audit(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", RISK_REASON)

        with pytest.raises(RiskConfirmationError):
            resume_monitor_after_risk(
                conn,
                confirm_risk_reason="stale reason",
                actor="test",
            )
        assert get_monitor_state(conn)["risk_stop_reason"] == RISK_REASON

        state = resume_monitor_after_risk(
            conn,
            confirm_risk_reason=RISK_REASON,
            actor="test",
        )
        event = recent_run_events(conn, limit=1)[0]

    assert state["desired_state"] == "running"
    assert state["risk_stop_reason"] is None
    assert event["event"] == "risk_stop_cleared"
    assert event["phase"] == "monitor_control"
    assert event["level"] == "warning"
    assert json.loads(event["data_json"]) == {
        "actor": "test",
        "confirmed_risk_reason": RISK_REASON,
    }


def test_web_ordinary_resume_returns_409_without_starting_scheduler(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", RISK_REASON)
    starts = []
    monkeypatch.setattr(
        "xhs_scout.scheduler.MonitorScheduler.start",
        lambda self: starts.append("start") or True,
    )

    routes = _routes(create_app(settings))
    with pytest.raises(HTTPException) as exc_info:
        routes["/api/monitor/resume"]()

    assert exc_info.value.status_code == 409
    assert starts == []
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == RISK_REASON


def test_web_explicit_risk_resume_validates_reason_then_starts_scheduler(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", RISK_REASON)
    starts = []
    monkeypatch.setattr(
        "xhs_scout.scheduler.MonitorScheduler.start",
        lambda self: starts.append("start") or True,
    )

    routes = _routes(create_app(settings))
    with pytest.raises(HTTPException) as exc_info:
        routes["/api/monitor/risk-resume"](
            RiskResumeRequest(confirm_risk_reason="stale reason")
        )
    assert exc_info.value.status_code == 409
    assert starts == []

    result = routes["/api/monitor/risk-resume"](
        RiskResumeRequest(confirm_risk_reason=RISK_REASON)
    )
    assert result["desired_state"] == "running"
    assert result["risk_stop_reason"] is None
    assert starts == ["start"]


def test_cli_requires_explicit_current_reason_to_clear_risk(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", RISK_REASON)
    monkeypatch.setattr(cli.Settings, "load", lambda _root=None: settings)
    monkeypatch.setattr(cli.sys, "stdout", io.StringIO())

    monkeypatch.setattr(sys, "argv", ["xhs-scout", "monitor-resume"])
    with pytest.raises(SystemExit):
        cli.main()
    with connect(settings.db_path) as conn:
        assert get_monitor_state(conn)["risk_stop_reason"] == RISK_REASON

    monkeypatch.setattr(
        sys,
        "argv",
        ["xhs-scout", "monitor-resume", "--confirm-risk", RISK_REASON],
    )
    cli.main()
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        event = recent_run_events(conn, limit=1)[0]
    assert state["desired_state"] == "running"
    assert state["risk_stop_reason"] is None
    assert json.loads(event["data_json"])["actor"] == "cli"


def test_ui_separates_ordinary_resume_from_risk_resume():
    html = render_workbench_html()

    assert "/api/monitor/resume" in html
    assert "/api/monitor/risk-resume" in html
    assert "恢复普通暂停" in html
    assert "确认风险已解除并恢复" in html
    assert 'Boolean(latestStatus?.monitor?.risk_stop_reason)' in html
    assert 'body: JSON.stringify({ confirm_risk_reason: riskReason })' in html
    assert "window.confirm" in html
