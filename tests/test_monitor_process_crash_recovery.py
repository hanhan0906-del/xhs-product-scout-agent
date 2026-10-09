from pathlib import Path

from xhs_scout.config import Settings
from xhs_scout.db import connect, enqueue, set_monitor_desired_state
from xhs_scout.monitor import (
    MonitorBlocked,
    MonitorLimits,
    _app_process_restarted,
    monitor_once,
)
from xhs_scout.ui_automation import Bounds, UiTarget


class RestartingDevice:
    def __init__(self):
        self.calls = []
        self.process_ids = iter(["100", "200", "300", "300"])

    def pidof(self, package):
        self.calls.append(("pidof", package))
        return next(self.process_ids)

    def tap(self, x, y):
        self.calls.append(("tap", x, y))

    def force_stop(self, package, *, timeout):
        self.calls.append(("force_stop", package, timeout))

    def launch_with_bluestacks_player(self, player, instance, package):
        self.calls.append(("launch", str(player), instance, package))


def test_process_restart_requires_two_known_different_ids():
    assert _app_process_restarted("100", "200") is True
    assert _app_process_restarted("100", "100") is False
    assert _app_process_restarted(None, "200") is False
    assert _app_process_restarted("100", None) is False


def test_product_open_process_crash_restarts_and_researches_current_keyword(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    device = RestartingDevice()
    card = UiTarget(
        x=898,
        y=527,
        bounds=Bounds(750, 400, 1040, 650),
        label="商品卡片",
        reason="test",
    )
    search_calls = []
    detail_probes = iter(
        [
            {"page_kind": "home_feed", "activity": "IndexActivityV2"},
            {"page_kind": "product_detail", "activity": "GoodsDetailActivityV2"},
        ]
    )

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor.discover_bluestacks_player",
        lambda _configured=None: Path("C:/BlueStacks/HD-Player.exe"),
    )
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: {
            "page_kind": "home_feed",
            "has_anr": False,
            "risk_stop_reason": None,
        },
    )

    def open_search(_settings, _device, **kwargs):
        search_calls.append(kwargs["task"]["keyword"])
        return {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        }

    monkeypatch.setattr("xhs_scout.monitor._open_search_results", open_search)
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards",
        lambda *_args, **_kwargs: [card],
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._probe_opened_product_page",
        lambda *_args, **_kwargs: next(detail_probes),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MonitorBlocked("stop after verified crash recovery", hard=True)
        ),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        lambda called_settings, limit=20: {
            "report_path": str(called_settings.reports_dir / "offline.md"),
            "count": 0,
            "limit": limit,
        },
    )
    with connect(settings.db_path) as conn:
        enqueue(conn, ["预算表"], source="process-crash-test")
        set_monitor_desired_state(conn, "running")

    output = monitor_once(
        settings,
        limits=MonitorLimits(
            wait_seconds=0,
            requeue_due_keywords=False,
            seller_profile=False,
        ),
    )

    assert output["blocked"] == "stop after verified crash recovery"
    assert output["app_process_crash_recovery"] == {
        "attempted": True,
        "safe_page": "home_feed",
        "keyword": "预算表",
    }
    assert search_calls == ["预算表", "预算表"]
    assert [call[0] for call in device.calls] == [
        "pidof",
        "tap",
        "pidof",
        "force_stop",
        "launch",
        "pidof",
        "tap",
        "pidof",
    ]
    with connect(settings.db_path) as conn:
        events = [
            row["event"]
            for row in conn.execute(
                "SELECT event FROM run_events ORDER BY id"
            ).fetchall()
        ]
    assert "app_process_restart_detected_during_product_open" in events
    assert "product_open_crash_recovery_succeeded" in events
    assert "retap_product_card_after_process_restart" in events
