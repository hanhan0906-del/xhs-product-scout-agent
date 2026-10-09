from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import xhs_scout.soak_readiness as soak_readiness_module
from xhs_scout.config import Settings
from xhs_scout.db import connect
from xhs_scout.web import create_app


READINESS_PATH = "/api/soak-readiness"
APPROVAL_PATH = "/api/approval-manifest"


def _app_with_temp_database(root: Path):
    settings = Settings.load(root)
    with connect(settings.db_path):
        pass
    return settings, create_app(settings)


def _endpoint(app, path: str):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == path
    )


def _route(app, path: str):
    return next(
        route for route in app.routes if getattr(route, "path", None) == path
    )


def _workbench_html(app) -> str:
    return _endpoint(app, "/")()


def _install_required_critical_alert(
    monkeypatch,
    *,
    alert_id: str = "t58-critical-alert",
) -> str:
    original = soak_readiness_module.load_sqlite_evidence

    def load_with_critical_alert(source, *, context=None):
        bundle = original(source, context=context)
        bundle["digest_snapshots"] = [
            {
                "phase": "mid",
                "alerts": [
                    {
                        "alert_id": alert_id,
                        "severity": "critical",
                        "title": "T58 read-only contract fixture",
                    }
                ],
            }
        ]
        return bundle

    monkeypatch.setattr(
        soak_readiness_module,
        "load_sqlite_evidence",
        load_with_critical_alert,
    )
    return alert_id


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_ack_and_scheduler_files_fail_closed_and_are_displayable(
    tmp_path,
    monkeypatch,
):
    alert_id = _install_required_critical_alert(monkeypatch)
    settings, app = _app_with_temp_database(tmp_path)
    before = _sha256(settings.db_path)

    result = _endpoint(app, READINESS_PATH)()
    html = _workbench_html(app)

    assert _sha256(settings.db_path) == before
    assert result["ack_readiness"]["required"] is True
    assert result["ack_readiness"]["ready"] is False
    assert result["ack_readiness"]["missing_alert_ids"] == [alert_id]
    assert result["gates"]["G2"]["status"] != "passed"
    assert result["gates"]["G4"]["status"] != "passed"
    assert "scheduler_evidence_ledger_missing" in result["warnings"]
    assert "scheduler_expected_missing" in result["warnings"]
    assert result["ready_for_pre_soak"] is False
    assert result["ready_for_24h_soak"] is False
    assert result["soak_start_authorized"] is False
    assert result["authorization"]["soak_start_authorized"] is False
    assert result["authorization"]["expansion_authorized"] is False

    # The workbench has explicit render states for the exact fail-closed API fields.
    assert "data?.ack_readiness" in html
    assert "required · 未 ACK" in html
    assert "missing_alert_ids" in html
    assert "scheduler_evidence" in html
    assert "missing scheduled_at" in html
    assert "G2/G4 到期点未核对，不能晋级" in html
    assert "insufficient · 尚不具备" in html


def test_corrupt_ack_expected_and_scheduler_evidence_never_display_as_passed(
    tmp_path,
    monkeypatch,
):
    _install_required_critical_alert(monkeypatch)
    settings, app = _app_with_temp_database(tmp_path)
    ack_path = tmp_path / "acks" / "soak-ack.jsonl"
    scheduler_path = tmp_path / "evidence" / "scheduler-evidence.jsonl"
    expected_path = tmp_path / "evidence" / "scheduler-expected.json"
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    scheduler_path.parent.mkdir(parents=True, exist_ok=True)
    ack_path.write_text("{bad ack json}\n", encoding="utf-8")
    scheduler_path.write_text("{bad scheduler json}\n", encoding="utf-8")
    expected_path.write_text("{bad expected json}", encoding="utf-8")

    result = _endpoint(app, READINESS_PATH)()
    html = _workbench_html(app)

    assert result["ack_readiness"]["ready"] is False
    assert result["ack_readiness"]["integrity_error"]
    scheduler = result["record"]["scheduler_evidence"]
    assert scheduler["ledger_integrity_ok"] is False
    assert scheduler["integrity_error"]
    assert result["gates"]["G2"]["status"] != "passed"
    assert result["gates"]["G4"]["status"] != "passed"
    assert any(
        warning.startswith("scheduler_expected_invalid:")
        for warning in result["warnings"]
    )
    assert result["ready_for_pre_soak"] is False
    assert result["ready_for_24h_soak"] is False
    assert result["soak_start_authorized"] is False

    assert "integrity 损坏" in html
    assert "ledger_integrity_ok" in html
    assert "integrity_error" in html
    assert "不能晋级" in html
    assert "接口未明确返回 soak_start_authorized=false" in html


@pytest.mark.parametrize(
    ("manifest_body", "expected_status", "display_text", "blocking_text"),
    [
        (
            None,
            "missing",
            "missing · 清单缺失",
            "清单缺失，不能视为已审批",
        ),
        (
            "{bad manifest json}",
            "invalid",
            "invalid · 清单损坏或越界",
            "清单损坏、篡改或语义越界",
        ),
    ],
)
def test_missing_or_invalid_approval_manifest_maps_to_blocked_workbench_state(
    tmp_path,
    manifest_body,
    expected_status,
    display_text,
    blocking_text,
):
    settings, app = _app_with_temp_database(tmp_path)
    if manifest_body is not None:
        manifest_path = tmp_path / "approvals" / "remediation-approval.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(manifest_body, encoding="utf-8")

    result = _endpoint(app, APPROVAL_PATH)()
    html = _workbench_html(app)

    assert result["manifest_status"] == expected_status
    assert result["review_status"] == "pending"
    assert result["is_current"] is False
    assert result["plan_approval_status"] == "pending_review"
    assert result["execution_status"] == "not_executed"
    assert result["authorizes_execution"] is False
    assert result["scope"]["manifest_access"] == "read_only"
    assert result["scope"]["production_queue_write"] is False
    assert result["scope"]["approval_write"] is False
    assert result["scope"]["approval_endpoint"] is False
    assert result["scope"]["execution_endpoint"] is False
    assert result["scope"]["authorizes_execution"] is False

    assert display_text in html
    assert blocking_text in html
    assert "source_plan_current=false · 阻塞" in html
    assert "authorizes_execution=false · not_executed" in html


def test_readiness_and_approval_surfaces_are_get_only_and_never_authorize(
    tmp_path,
):
    _, app = _app_with_temp_database(tmp_path)

    assert _route(app, READINESS_PATH).methods == {"GET"}
    assert _route(app, APPROVAL_PATH).methods == {"GET"}

    readiness = _endpoint(app, READINESS_PATH)()
    approval = _endpoint(app, APPROVAL_PATH)()
    assert readiness["soak_start_authorized"] is False
    assert readiness["authorization"]["soak_start_authorized"] is False
    assert readiness["authorization"]["expansion_authorized"] is False
    assert approval["execution_status"] == "not_executed"
    assert approval["authorizes_execution"] is False
    assert approval["scope"]["authorizes_execution"] is False


def test_workbench_has_no_readiness_or_approval_action_controls_or_post_calls(
    tmp_path,
):
    _, app = _app_with_temp_database(tmp_path)
    html = _workbench_html(app)

    readiness_start = html.index(
        '<section class="work-panel spaced-panel" '
        'aria-labelledby="soakReadinessTitle">'
    )
    readiness_end = html.index(
        'aria-labelledby="remediationPlanTitle"',
        readiness_start,
    )
    approval_start = html.index(
        '<section class="work-panel spaced-panel approval-manifest blocked"'
    )
    approval_end = html.index('data-view-panel="keywords"', approval_start)
    readiness_panel = html[readiness_start:readiness_end]
    approval_panel = html[approval_start:approval_end]

    for panel in (readiness_panel, approval_panel):
        assert "<button" not in panel
        assert "<form" not in panel
        assert "<input" not in panel
        assert "<select" not in panel
        assert "<textarea" not in panel
        assert 'method="post"' not in panel.lower()

    readiness_script_start = html.index("async function refreshSoakReadiness()")
    readiness_script_end = html.index(
        "function remediationStageText",
        readiness_script_start,
    )
    approval_script_start = html.index("async function refreshApprovalManifest()")
    approval_script_end = html.index(
        "function renderStatus",
        approval_script_start,
    )
    readiness_script = html[readiness_script_start:readiness_script_end]
    approval_script = html[approval_script_start:approval_script_end]

    assert "fetch(API_ROUTES.soakReadiness)" in readiness_script
    assert "fetch(API_ROUTES.approvalManifest)" in approval_script
    for script in (readiness_script, approval_script):
        assert 'method: "POST"' not in script
        assert "method: 'POST'" not in script
        assert ".post(" not in script

    assert "本工作台不启动 pre-soak、24 小时 soak、监控或扩容" in readiness_panel
    assert "不创建清单、不批准、不写队列，也不执行补证" in approval_panel
