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


def _offline_report(settings, limit=20):
    return {
        "report_path": str(settings.reports_dir / "offline-seller-profile.md"),
        "count": 0,
        "limit": limit,
    }


def test_seller_soft_skip_returns_to_search_and_requeues_without_task_result(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
        wait_seconds=0,
        seller_profile=True,
        note_evidence=True,
    )
    device = FakeDevice()
    card = UiTarget(
        x=120,
        y=240,
        bounds=Bounds(100, 200, 140, 280),
        label="product",
        reason="offline",
    )
    later_calls = []

    with connect(settings.db_path) as conn:
        enqueue(conn, ["食谱"], source="test")
        set_monitor_desired_state(conn, "running")
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, first_seen_at, last_seen_at
            ) VALUES ('seller-soft-product', '食谱商品', '2026-08-12T00:00:00+00:00',
                      '2026-08-12T00:00:00+00:00')
            """
        )
        product_id = conn.execute(
            "SELECT id FROM products WHERE fingerprint='seller-soft-product'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(product_id, observed_at, source, raw_text)
            VALUES (?, '2026-08-12T00:00:00+00:00', 'test', '食谱商品')
            """,
            (product_id,),
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

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
            "product_id": product_id,
            "observation_id": observation_id,
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_seller_profile_from_product",
        lambda *_args, **_kwargs: {
            "skipped": True,
            "skip_reason": "shop_entry_not_opened",
            "task_disposition": {
                "retryable": True,
                "reason": "shop_entry_not_opened",
            },
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._recover_to_search_results_after_detail",
        lambda *_args, **_kwargs: later_calls.append("return") or True,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._capture_note_evidence_for_current_detail",
        lambda *_args, **_kwargs: later_calls.append("note") or {},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report",
        _offline_report,
    )

    output = monitor_once(settings, limits=limits)

    assert output.get("blocked") is None
    assert output["processed_tasks"] == 1
    assert output["captured_products"] == 1
    assert later_calls == ["return"]
    with connect(settings.db_path) as conn:
        task = conn.execute(
            """
            SELECT status, attempts, run_owner, run_lease_expires_at, last_error
            FROM search_tasks WHERE keyword='食谱'
            """
        ).fetchone()
        assert task["status"] == "pending"
        assert task["attempts"] == 1
        assert task["run_owner"] is None
        assert task["run_lease_expires_at"] is None
        assert task["last_error"] == "shop_entry_not_opened"
        assert conn.execute(
            "SELECT COUNT(*) FROM task_results WHERE task_id=(SELECT id FROM search_tasks WHERE keyword='食谱')"
        ).fetchone()[0] == 0
        state = get_monitor_state(conn)
        assert state["desired_state"] == "running"
        assert state["risk_stop_reason"] is None


def test_seller_unknown_remains_a_hard_stop(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
        wait_seconds=0,
        seller_profile=True,
    )
    device = FakeDevice()
    card = UiTarget(120, 240, Bounds(100, 200, 140, 280), "product", "offline")

    with connect(settings.db_path) as conn:
        enqueue(conn, ["食谱"], source="test")
        set_monitor_desired_state(conn, "running")

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *_args, **_kwargs: {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards", lambda *_args, **_kwargs: [card]
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._probe_opened_product_page",
        lambda *_args, **_kwargs: {"page_kind": "product_detail"},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        lambda *_args, **_kwargs: {"product_id": 1, "observation_id": 1},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.record_search_result_evidence",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_seller_profile_from_product",
        lambda *_args, **_kwargs: {
            "blocked": True,
            "reason": "店铺入口打开了未知页面：unknown",
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report", _offline_report
    )

    output = monitor_once(settings, limits=limits)

    assert output["blocked"] == "店铺入口打开了未知页面：unknown"
    with connect(settings.db_path) as conn:
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == output["blocked"]


def test_seller_not_displayed_success_completes_with_valid_task_result(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    limits = MonitorLimits(
        max_keywords=1,
        max_products_per_keyword=1,
        requeue_due_keywords=False,
        wait_seconds=0,
        seller_profile=True,
        note_evidence=False,
    )
    device = FakeDevice()
    card = UiTarget(
        x=120,
        y=240,
        bounds=Bounds(100, 200, 140, 280),
        label="product",
        reason="offline",
    )
    later_calls = []

    with connect(settings.db_path) as conn:
        enqueue(conn, ["未展示粉丝商品"], source="test")
        set_monitor_desired_state(conn, "running")
        product_id = conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, first_seen_at, last_seen_at
            ) VALUES ('seller-not-displayed-product', '未展示粉丝商品',
                      '2026-08-12T00:00:00+00:00',
                      '2026-08-12T00:00:00+00:00')
            """
        ).lastrowid
        observation_id = conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, raw_text, raw_signals_json
            ) VALUES (?, '2026-08-12T00:00:00+00:00', 'test',
                      '未展示粉丝商品',
                      '{"商品销量":"1000+","近30天好评":"300+","近30天购买":"500+"}')
            """,
            (product_id,),
        ).lastrowid

    monkeypatch.setattr("xhs_scout.monitor._device", lambda _settings: device)
    monkeypatch.setattr(
        "xhs_scout.monitor._open_search_results",
        lambda *_args, **_kwargs: {
            "xml": "<hierarchy />",
            "probe": {"page_kind": "search_results"},
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.find_product_cards", lambda *_args, **_kwargs: [card]
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._probe_opened_product_page",
        lambda *_args, **_kwargs: {"page_kind": "product_detail"},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_current_page_for_task",
        lambda *_args, **_kwargs: {
            "product_id": product_id,
            "observation_id": observation_id,
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.capture_seller_profile_from_product",
        lambda *_args, **_kwargs: {
            "parsed": {
                "author_name": None,
                "follower_count": None,
                "likes": None,
                "collects": None,
                "comments": None,
                "published_days_ago": None,
            },
            "note_observation_id": 151,
            "follower_display_status": "not_displayed",
            "low_follower_qualified": False,
            "after_probe": {"page_kind": "shop_product_list"},
            "recovery_probe": {"page_kind": "product_detail"},
        },
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._capture_note_evidence_for_current_detail",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "xhs_scout.monitor._recover_to_search_results_after_detail",
        lambda *_args, **_kwargs: later_calls.append("return") or True,
    )
    monkeypatch.setattr(
        "xhs_scout.monitor.generate_candidate_report", _offline_report
    )

    output = monitor_once(settings, limits=limits)

    assert output.get("blocked") is None
    assert output["processed_tasks"] == 1
    assert output["captured_products"] == 1
    assert later_calls == ["return"]
    assert output["seller_profiles"][0]["follower_display_status"] == "not_displayed"
    assert output["seller_profiles"][0]["low_follower_qualified"] is False
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT id, status, last_error FROM search_tasks WHERE keyword=?",
            ("未展示粉丝商品",),
        ).fetchone()
        assert task["status"] == "completed"
        assert task["last_error"] is None
        result = conn.execute(
            """
            SELECT product_id, observation_id, valid
            FROM task_results WHERE task_id=?
            """,
            (task["id"],),
        ).fetchone()
        assert dict(result) == {
            "product_id": product_id,
            "observation_id": observation_id,
            "valid": 1,
        }
        state = get_monitor_state(conn)
        assert state["desired_state"] == "running"
        assert state["risk_stop_reason"] is None
