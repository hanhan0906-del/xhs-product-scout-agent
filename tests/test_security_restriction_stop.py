import pytest

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    set_monitor_desired_state,
)
from xhs_scout.monitor import MonitorLimits, monitor_once
from xhs_scout.signals import classify_page_text, detect_risk_stop


@pytest.mark.parametrize(
    ("text", "expected_reason"),
    (
        ("小红书 - 安全限制\n检测到当前环境存在风险", "安全限制"),
        ("当前设备异常，请更换设备后重试", "设备异常"),
        ("检测到风险插件，请卸载后再试", "风险插件"),
        ("登录异常，请重新登录", "登录异常"),
    ),
)
def test_explicit_security_page_phrases_are_hard_stop_signals(
    text, expected_reason
):
    assert detect_risk_stop(text) == expected_reason
    assert classify_page_text(text) == "risk_stop"


def test_generic_abnormal_word_does_not_trigger_risk_stop():
    text = "商品数据异常分析模板 自动发货"

    assert detect_risk_stop(text) is None
    assert classify_page_text(text) != "risk_stop"


def test_security_restriction_persists_and_ignore_paused_cannot_open_device(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
    )
    security_text = "小红书 - 安全限制\n当前设备异常，请稍后再试"
    reason = detect_risk_stop(security_text)
    device_opens = []

    monkeypatch.setattr(
        "xhs_scout.monitor._device",
        lambda called_settings: device_opens.append(called_settings) or object(),
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *args, **kwargs: {
            "probe_dir": str(tmp_path / "security-probe"),
            "activity": "com.xingin.xhs/.index.v2.IndexActivityV2",
            "has_anr": False,
            "risk_stop_reason": reason,
            "page_kind": classify_page_text(security_text),
            "screenshot": str(tmp_path / "security-probe" / "current.png"),
            "text": security_text,
            "ocr_count": 2,
            "ui_dump_ok": False,
            "ui_error": None,
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        lambda called_settings, limit=20: {
            "report_path": str(called_settings.reports_dir / "offline-security.md"),
            "count": 0,
            "limit": limit,
        },
    )

    with connect(settings.db_path) as conn:
        enqueue(conn, ["安全页回归"], source="test")
        set_monitor_desired_state(conn, "running")

    first = monitor_once(settings, limits=limits)

    assert first["blocked"] == "risk stop: 安全限制"
    assert len(device_opens) == 1
    with connect(settings.db_path) as conn:
        first_state = get_monitor_state(conn)
        assert first_state["desired_state"] == "paused"
        assert first_state["risk_stop_reason"] == "risk stop: 安全限制"

    second = monitor_once(settings, limits=limits, ignore_paused=True)

    assert second["blocked"] == "risk stop: 安全限制"
    assert second["skipped"] == ["risk stop requires explicit resume"]
    assert len(device_opens) == 1
    with connect(settings.db_path) as conn:
        second_state = get_monitor_state(conn)
        assert second_state["desired_state"] == "paused"
        assert second_state["risk_stop_reason"] == "risk stop: 安全限制"
