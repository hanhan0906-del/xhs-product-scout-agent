import json

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    set_monitor_desired_state,
)
from xhs_scout.monitor import MonitorLimits, monitor_once
from xhs_scout.ui_automation import Bounds, UiTarget


class FakeDevice:
    def __init__(self):
        self.calls = []

    def tap(self, x, y):
        self.calls.append(("tap", x, y))

    def back(self):
        self.calls.append(("back",))


def _offline_report(settings, limit=20):
    return {
        "report_path": str(settings.reports_dir / "offline-lease-safety.md"),
        "count": 0,
        "limit": limit,
    }


def _prepare_running_task(settings):
    with connect(settings.db_path) as conn:
        enqueue(conn, ["lease safety"], source="test")
        set_monitor_desired_state(conn, "running")


def _take_over_monitor_lease(settings):
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            UPDATE run_leases
            SET owner='replacement-owner'
            WHERE name='monitor_once'
            """
        )


def _assert_fail_closed_state(settings, output, expected_phase):
    assert output["lease_safety_blocked"] == {
        "phase": expected_phase,
        "reason": "monitor_owner_mismatch",
    }
    assert output["blocked"] == (
        f"lease safety blocked at {expected_phase}: monitor_owner_mismatch"
    )
    assert output["skipped"][-1]["retryable"] is False

    with connect(settings.db_path) as conn:
        task = conn.execute(
            """
            SELECT status, attempts, next_run_at, run_owner,
                   run_lease_expires_at, last_error
            FROM search_tasks
            WHERE keyword='lease safety'
            """
        ).fetchone()
        assert task["status"] == "needs_manual_detail"
        assert task["attempts"] == 1
        assert task["next_run_at"] is None
        assert task["run_owner"] is None
        assert task["run_lease_expires_at"] is None
        assert task["last_error"] == output["blocked"]

        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == output["blocked"]
        assert state["last_block_reason"] == output["blocked"]

        lease = conn.execute(
            "SELECT owner FROM run_leases WHERE name='monitor_once'"
        ).fetchone()
        assert lease["owner"] == "replacement-owner"

        event = conn.execute(
            """
            SELECT phase, event, level, message, data_json
            FROM run_events
            WHERE event='lease_safety_blocked'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        assert (event["phase"], event["event"], event["level"]) == (
            "lease_safety",
            "lease_safety_blocked",
            "warning",
        )
        assert event["message"] == output["blocked"]
        assert json.loads(event["data_json"])["checkpoint"] == expected_phase


def test_lease_loss_after_search_stops_all_later_device_actions(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
        wait_seconds=0,
    )
    device = FakeDevice()
    later_calls = []

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)

    def fake_search(_settings, called_device, **_kwargs):
        called_device.tap(10, 20)
        _take_over_monitor_lease(settings)
        return {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        }

    monkeypatch.setattr("xhs_scout.monitor._open_search_results", fake_search)
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards",
        lambda *_args, **_kwargs: later_calls.append("find cards") or [],
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        lambda *_args, **_kwargs: later_calls.append("capture") or {},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._recover_to_search_results_after_detail",
        lambda *_args, **_kwargs: later_calls.append("return") or True,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        _offline_report,
    )
    _prepare_running_task(settings)

    output = monitor_once(settings, limits=limits)

    assert device.calls == [("tap", 10, 20)]
    assert later_calls == []
    _assert_fail_closed_state(settings, output, "after_search_stage")


def test_lease_loss_after_metrics_stops_note_and_return_device_actions(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
        wait_seconds=0,
        note_evidence=True,
    )
    device = FakeDevice()
    later_calls = []
    card = UiTarget(
        x=120,
        y=240,
        bounds=Bounds(100, 200, 140, 280),
        label="fake product",
        reason="offline test",
    )

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *_args, **_kwargs: {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards",
        lambda *_args, **_kwargs: [card],
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._probe_opened_product_page",
        lambda *_args, **_kwargs: {"page_kind": "product_detail"},
    )

    def fake_capture(*_args, **_kwargs):
        device.calls.append(("metrics_ocr",))
        _take_over_monitor_lease(settings)
        return {"product_id": None, "observation_id": None}

    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        fake_capture,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._capture_note_evidence_for_current_detail",
        lambda *_args, **_kwargs: later_calls.append("note") or {},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._recover_to_search_results_after_detail",
        lambda *_args, **_kwargs: later_calls.append("return") or True,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        _offline_report,
    )
    _prepare_running_task(settings)

    output = monitor_once(settings, limits=limits)

    assert device.calls == [("tap", 120, 240), ("metrics_ocr",)]
    assert later_calls == []
    _assert_fail_closed_state(
        settings,
        output,
        "after_detail_capture_and_metrics_ocr",
    )


def test_capture_disposition_is_not_misreported_as_lease_loss(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
        wait_seconds=0,
        seller_profile=False,
    )
    device = FakeDevice()
    later_calls = []
    card = UiTarget(
        x=120,
        y=240,
        bounds=Bounds(100, 200, 140, 280),
        label="fake product",
        reason="offline test",
    )
    reason = "当前页不是商品详情页：unknown"

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *_args, **_kwargs: {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards",
        lambda *_args, **_kwargs: [card],
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._probe_opened_product_page",
        lambda *_args, **_kwargs: {"page_kind": "product_detail"},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        lambda *_args, **_kwargs: {
            "page_kind": "unknown",
            "skip_task_link_reason": reason,
            "task_disposition": {
                "status": "needs_manual_detail",
                "reason": reason,
            },
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._capture_note_evidence_for_current_detail",
        lambda *_args, **_kwargs: later_calls.append("note") or {},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._recover_to_search_results_after_detail",
        lambda *_args, **_kwargs: later_calls.append("return") or True,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        _offline_report,
    )
    _prepare_running_task(settings)

    output = monitor_once(settings, limits=limits)

    assert output["blocked"] == reason
    assert "lease_safety_blocked" not in output
    assert later_calls == []
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, run_owner, run_lease_expires_at, last_error "
            "FROM search_tasks WHERE keyword='lease safety'"
        ).fetchone()
        assert tuple(task) == ("needs_manual_detail", None, None, reason)
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == reason
        assert conn.execute(
            "SELECT COUNT(*) FROM run_events WHERE event='lease_safety_blocked'"
        ).fetchone()[0] == 0


def test_non_product_recovery_keeps_task_lease_until_after_back(
    tmp_path, monkeypatch
):
    """非商品页要先在有效租约内返回搜索页，再登记任务失败。

    旧顺序先调用mark_task_failed清除了run_owner，紧接着的恢复前租约检查
    必然得到task_not_running，使任何非商品页恢复都退化成全局硬停止。
    """

    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
        wait_seconds=0,
        seller_profile=False,
    )
    device = FakeDevice()
    card = UiTarget(
        x=120,
        y=240,
        bounds=Bounds(100, 200, 140, 280),
        label="fake product",
        reason="offline test",
    )

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *_args, **_kwargs: {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards",
        lambda *_args, **_kwargs: [card],
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._probe_opened_product_page",
        lambda *_args, **_kwargs: {
            "page_kind": "account_profile",
            "activity": "com.xingin.xhs.AccountActivity",
            "has_anr": False,
            "risk_stop_reason": None,
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "page_kind": "search_results",
            "activity": "com.xingin.xhs.GlobalSearchActivity",
            "has_anr": False,
            "risk_stop_reason": None,
        },
    )
    monkeypatch.setattr("xhs_scout.monitor._guard_probe", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        _offline_report,
    )
    _prepare_running_task(settings)

    output = monitor_once(settings, limits=limits)

    assert device.calls == [("tap", 120, 240), ("back",)]
    assert "lease_safety_blocked" not in output
    assert output.get("blocked") is None
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner, last_error "
            "FROM search_tasks WHERE keyword='lease safety'"
        ).fetchone()
        assert tuple(task) == (
            "pending",
            1,
            None,
            "opened page is account_profile",
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM run_events WHERE event='lease_safety_blocked'"
        ).fetchone()[0] == 0
