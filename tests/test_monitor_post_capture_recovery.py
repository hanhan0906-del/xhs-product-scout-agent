import json
from pathlib import Path

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    set_monitor_desired_state,
)
from xhs_scout.monitor import (
    MonitorLimits,
    _recover_to_search_results_after_detail,
)


class FakeDevice:
    def __init__(self):
        self.back_calls = 0

    def back(self):
        self.back_calls += 1


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _probe(*, page_kind, activity, text, fixed_query=None):
    ocr = []
    if fixed_query:
        ocr.append(
            {
                "text": fixed_query,
                "confidence": 0.99,
                "box": [[200, 120], [500, 120], [500, 170], [200, 170]],
            }
        )
    return {
        "run_id": "probe-test",
        "probe_dir": "unused",
        "activity": activity,
        "has_anr": False,
        "risk_stop_reason": None,
        "page_kind": page_kind,
        "screenshot": None,
        "text": text,
        "ocr_count": len(ocr),
        "ocr": ocr,
        "ui_dump_ok": True,
        "ui_error": None,
    }


def _create_task(settings, keyword="模板"):
    with connect(settings.db_path) as conn:
        enqueue(conn, [keyword], source="post-capture-recovery-test")
        return conn.execute(
            "SELECT id FROM search_tasks WHERE keyword=?",
            (keyword,),
        ).fetchone()["id"]


def test_first_back_accepts_keyword_matched_results_despite_stale_activity(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _create_task(settings)
    device = FakeDevice()
    probes = iter(
        [
            _probe(
                page_kind="search_results",
                activity="android/com.android.internal.app.ResolverActivity",
                text="12:35\n模板\n搜索\n商品\n职场新人全周期成长指南",
                fixed_query="模板",
            )
        ]
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda _probe: "")
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    recovered = _recover_to_search_results_after_detail(
        settings,
        device,
        run_id="monitor-recovery-test",
        task_id=task_id,
        expected_keyword="模板",
        limits=MonitorLimits(wait_seconds=0),
    )

    assert recovered is True
    assert device.back_calls == 1
    with connect(settings.db_path) as conn:
        event = conn.execute(
            """
            SELECT data_json
            FROM run_events
            WHERE event='back_to_search_results'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert event is not None
    assert '"keyword_matches": true' in event["data_json"]
    assert '"activity_match": false' in event["data_json"]


def test_real_unknown_probe_accepts_fixed_search_context_after_one_back(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _create_task(settings, keyword="开学第一课PPT")
    device = FakeDevice()
    probe_root = (
        PROJECT_ROOT
        / "data"
        / "probes"
        / "monitor-d6c80899da28-probe-after-detail-back-1"
    )
    probe = json.loads((probe_root / "probe.json").read_text(encoding="utf-8"))
    xml_text = (probe_root / "window.xml").read_text(encoding="utf-8")
    assert probe["page_kind"] == "unknown"
    assert "GlobalSearchActivity" in probe["activity"]

    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: probe,
    )
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda _probe: xml_text)
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    recovered = _recover_to_search_results_after_detail(
        settings,
        device,
        run_id="monitor-real-recovery-replay",
        task_id=task_id,
        expected_keyword="开学第一课PPT",
        limits=MonitorLimits(wait_seconds=0),
    )

    assert recovered is True
    assert device.back_calls == 1
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        event = conn.execute(
            """
            SELECT data_json
            FROM run_events
            WHERE event='back_to_search_results'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert state["last_block_reason"] is None
    assert event is not None
    assert '"fixed_search_context": true' in event["data_json"]


def test_wrong_keyword_does_not_accept_results_and_still_pauses(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _create_task(settings)
    device = FakeDevice()
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")
    probes = iter(
        [
            _probe(
                page_kind="search_results",
                activity="android/com.android.internal.app.ResolverActivity",
                text="12:35\n话术\n搜索\n商品\n错误的搜索上下文",
                fixed_query="话术",
            ),
            _probe(
                page_kind="search_input",
                activity="android/com.android.internal.app.ResolverActivity",
                text="12:36\n历史记录\n模板\n话术",
            ),
        ]
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda _probe: "")
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    recovered = _recover_to_search_results_after_detail(
        settings,
        device,
        run_id="monitor-recovery-test",
        task_id=task_id,
        expected_keyword="模板",
        limits=MonitorLimits(wait_seconds=0),
    )

    assert recovered is False
    assert device.back_calls == 2
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
    assert state["desired_state"] == "paused"
    assert state["last_block_reason"] == (
        "post-capture back did not reach search results: search_input"
    )


def test_shop_product_list_still_requires_real_search_activity(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _create_task(settings)
    device = FakeDevice()
    probes = iter(
        [
            _probe(
                page_kind="shop_product_list",
                activity="android/com.android.internal.app.ResolverActivity",
                text="12:35\n模板\n搜索\n商品",
                fixed_query="模板",
            ),
            _probe(
                page_kind="search_input",
                activity="android/com.android.internal.app.ResolverActivity",
                text="12:36\n历史记录\n模板",
            ),
        ]
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.probe_current_page",
        lambda *_args, **_kwargs: next(probes),
    )
    monkeypatch.setattr("xhs_scout.monitor._read_ui", lambda _probe: "")
    monkeypatch.setattr("xhs_scout.monitor.time.sleep", lambda _seconds: None)

    recovered = _recover_to_search_results_after_detail(
        settings,
        device,
        run_id="monitor-recovery-test",
        task_id=task_id,
        expected_keyword="模板",
        limits=MonitorLimits(wait_seconds=0),
    )

    assert recovered is False
    assert device.back_calls == 2
