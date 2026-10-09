from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    get_monitor_state,
    record_note_observation,
    set_monitor_state,
    utcnow,
)
from fastapi import HTTPException
import pytest

from xhs_scout.device_link_open import DeviceLinkOpenError
from xhs_scout.web import _candidate_rows, create_app


def _insert_openable_product(settings, direct_url="xhsdiscover://page/goods/open-me"):
    with connect(settings.db_path) as conn:
        now = utcnow()
        return conn.execute(
            """
            INSERT INTO products(fingerprint, title, direct_url, first_seen_at, last_seen_at)
            VALUES ('openable-product', 'Openable', ?, ?, ?)
            """,
            (direct_url, now, now),
        ).lastrowid


def _open_device_route(settings):
    app = create_app(settings)
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/products/{product_id}/open-on-device"
    )


def test_open_on_device_rejects_missing_product(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    monkeypatch.setattr(
        "xhs_scout.web.open_link_on_configured_device",
        lambda *_args: (_ for _ in ()).throw(AssertionError("device must not open")),
    )

    with pytest.raises(HTTPException) as caught:
        _open_device_route(settings)(999)

    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == "product_not_found"


def test_open_on_device_revalidates_stored_direct_url(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    product_id = _insert_openable_product(settings, "https://xhslink.com/a/share-only")
    monkeypatch.setattr(
        "xhs_scout.web.open_link_on_configured_device",
        lambda *_args: (_ for _ in ()).throw(AssertionError("device must not open")),
    )

    with pytest.raises(HTTPException) as caught:
        _open_device_route(settings)(product_id)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "invalid_direct_url"


@pytest.mark.parametrize("busy_kind", ["scheduler", "desired", "running", "owner", "task_lease", "run_lease"])
def test_open_on_device_rejects_every_device_occupancy_signal(
    tmp_path, monkeypatch, busy_kind
):
    settings = Settings.load(tmp_path)
    product_id = _insert_openable_product(settings)
    route = _open_device_route(settings)
    monkeypatch.setattr(
        "xhs_scout.web.open_link_on_configured_device",
        lambda *_args: (_ for _ in ()).throw(AssertionError("device must not open")),
    )
    if busy_kind == "scheduler":
        app = create_app(settings)
        app.state.monitor_scheduler.snapshot = lambda: {"thread_alive": True}
        route = next(
            item.endpoint
            for item in app.routes
            if getattr(item, "path", None) == "/api/products/{product_id}/open-on-device"
        )
    elif busy_kind == "desired":
        with connect(settings.db_path) as conn:
            set_monitor_state(conn, "desired_state", "running")
    else:
        with connect(settings.db_path) as conn:
            now = utcnow()
            if busy_kind == "run_lease":
                conn.execute(
                    """
                    INSERT INTO run_leases(name, owner, acquired_at, heartbeat_at, expires_at)
                    VALUES ('test', 'owner', ?, ?, ?)
                    """,
                    (now, now, now),
                )
            else:
                status = "running" if busy_kind == "running" else "pending"
                owner = "owner" if busy_kind == "owner" else None
                lease = now if busy_kind == "task_lease" else None
                conn.execute(
                    """
                    INSERT INTO search_tasks(
                        keyword, status, run_owner, run_lease_expires_at,
                        created_at, updated_at
                    ) VALUES ('busy', ?, ?, ?, ?, ?)
                    """,
                    (status, owner, lease, now, now),
                )

    with pytest.raises(HTTPException) as caught:
        route(product_id)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "device_busy"


def test_open_on_device_rejects_risk_stop(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    product_id = _insert_openable_product(settings)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", "captcha")
    monkeypatch.setattr(
        "xhs_scout.web.open_link_on_configured_device",
        lambda *_args: (_ for _ in ()).throw(AssertionError("device must not open")),
    )

    with pytest.raises(HTTPException) as caught:
        _open_device_route(settings)(product_id)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "risk_stop_active"


def test_open_on_device_uses_stored_url_once_and_maps_device_failure(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    direct_url = "xhsdiscover://page/goods/stored-product"
    product_id = _insert_openable_product(settings, direct_url)
    calls = []

    def fake_open(_settings, url):
        calls.append(url)
        return {"launched": True, "page_verified": False, "device_serial": "mock"}

    monkeypatch.setattr("xhs_scout.web.open_link_on_configured_device", fake_open)
    result = _open_device_route(settings)(product_id)

    assert calls == [direct_url]
    assert result["launched"] is True
    assert result["page_verified"] is False

    monkeypatch.setattr(
        "xhs_scout.web.open_link_on_configured_device",
        lambda *_args: (_ for _ in ()).throw(
            DeviceLinkOpenError("device_open_failed", "failed", 502)
        ),
    )
    with pytest.raises(HTTPException) as caught:
        _open_device_route(settings)(product_id)
    assert caught.value.status_code == 502
    assert caught.value.detail == {"code": "device_open_failed", "message": "failed"}


def test_candidate_export_rows_include_note_and_profile_evidence(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, share_url, first_seen_at, last_seen_at
            ) VALUES ('web-fp', 'Test pack', 'https://xhslink.com/a/test', ?, ?)
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, raw_signals_json
            ) VALUES (?, ?, 'test',
                '{"metrics_strip":{"frames":[{"signals":{"sales_30d_min":1000,"positive_reviews_30d_min":500,"favorites_30d_min":200}}]}}')
            """,
            (product_id, now),
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score, reasons_json, status
            ) VALUES (?, ?, 'B', 60, '[]', 'candidate')
            """,
            (product_id, now),
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="related_note_card",
            screenshot_path=None,
            probe_dir="note-probe",
            page_kind="note_detail",
            raw_text="Author A",
            author_name="Author A",
            likes=1200,
            published_days_ago=2,
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="author_profile_from_note",
            screenshot_path=None,
            probe_dir="profile-probe",
            page_kind="account_profile",
            raw_text="Author A",
            author_name="Author A",
            follower_count=188,
            likes=9000,
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="seller_profile_from_product",
            screenshot_path=None,
            probe_dir="seller-probe",
            page_kind="shop_product_list",
            raw_text="Test shop 188 followers",
            author_name="Test shop",
            follower_count=188,
        )
        task_id = conn.execute(
            """
            INSERT INTO search_tasks(keyword, created_at, updated_at)
            VALUES ('test', ?, ?)
            """,
            (now, now),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO task_results(
                task_id, product_id, observation_id, captured_at, valid
            ) VALUES (?, ?, ?, ?, 1)
            """,
            (task_id, product_id, observation_id, now),
        )

        row = dict(_candidate_rows(conn)[0])
    assert row["note_author_name"] == "Author A"
    assert row["share_url"] == "https://xhslink.com/a/test"
    assert row["note_likes"] == 1200
    assert row["note_published_days_ago"] == 2
    assert row["profile_follower_count"] == 188
    assert row["profile_total_likes"] == 9000
    assert row["seller_follower_count"] == 188
    assert row["seller_follower_display_status"] == "visible"
    assert row["candidate_qualified"] is True


def test_candidate_export_rows_exclude_partial_or_non_low_follower_products(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        now = utcnow()
        for number, followers in enumerate((188, 5000)):
            product_id = conn.execute(
                """
                INSERT INTO products(
                    fingerprint, title, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?)
                """,
                (f"export-{number}", f"Export {number}", now, now),
            ).lastrowid
            observation_id = conn.execute(
                """
                INSERT INTO observations(
                    product_id, observed_at, source, raw_signals_json
                ) VALUES (?, ?, 'test',
                    '{"metrics_strip":{"frames":[{"signals":{"sales_30d_min":1000,"positive_reviews_30d_min":500,"favorites_30d_min":200}}]}}')
                """,
                (product_id, now),
            ).lastrowid
            task_id = conn.execute(
                """
                INSERT INTO search_tasks(keyword, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (f"keyword-{number}", now, now),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO task_results(
                    task_id, product_id, observation_id, captured_at, valid
                ) VALUES (?, ?, ?, ?, 1)
                """,
                (task_id, product_id, observation_id, now),
            )
            record_note_observation(
                conn,
                product_id=product_id,
                source="seller_profile_from_product",
                screenshot_path=None,
                probe_dir=f"seller-{number}",
                page_kind="shop_product_list",
                raw_text="seller",
                follower_count=followers,
            )

        rows = [dict(row) for row in _candidate_rows(conn)]

    assert [row["title"] for row in rows] == ["Export 0"]
    assert rows[0]["seller_follower_count"] == 188
    assert rows[0]["task_result_valid"] is True


def test_candidate_export_rows_exclude_not_displayed_follower_evidence(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        now = utcnow()
        product_id = conn.execute(
            """
            INSERT INTO products(fingerprint, title, first_seen_at, last_seen_at)
            VALUES ('not-displayed', 'Not displayed', ?, ?)
            """,
            (now, now),
        ).lastrowid
        observation_id = conn.execute(
            """
            INSERT INTO observations(product_id, observed_at, source, raw_signals_json)
            VALUES (?, ?, 'test',
                '{"metrics_strip":{"frames":[{"signals":{"sales_30d_min":1000,"positive_reviews_30d_min":500,"favorites_30d_min":200}}]}}')
            """,
            (product_id, now),
        ).lastrowid
        task_id = conn.execute(
            """INSERT INTO search_tasks(keyword, created_at, updated_at)
               VALUES ('not-displayed', ?, ?)""",
            (now, now),
        ).lastrowid
        conn.execute(
            """INSERT INTO task_results(task_id, product_id, observation_id, captured_at, valid)
               VALUES (?, ?, ?, ?, 1)""",
            (task_id, product_id, observation_id, now),
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="seller_profile_from_product",
            screenshot_path=None,
            probe_dir="seller-not-displayed",
            page_kind="shop_product_list",
            raw_text="合法店铺页未显示粉丝数",
            raw={
                "follower_display_status": "not_displayed",
                "low_follower_qualified": False,
            },
        )

        assert _candidate_rows(conn) == []


def test_resume_starts_scheduler_and_pause_wakes_it(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    calls = []
    monkeypatch.setattr(
        "xhs_scout.scheduler.MonitorScheduler.start",
        lambda self: calls.append("start") or True,
    )
    monkeypatch.setattr(
        "xhs_scout.scheduler.MonitorScheduler.wake",
        lambda self: calls.append("wake"),
    )
    monkeypatch.setattr(
        "xhs_scout.scheduler.MonitorScheduler.stop",
        lambda self, timeout=5.0: calls.append("stop"),
    )

    app = create_app(settings)
    routes = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
    resume = routes["/api/monitor/resume"]()
    pause = routes["/api/monitor/pause"]()

    assert resume["desired_state"] == "running"
    assert pause["desired_state"] == "paused"
    assert calls == ["start", "wake"]
    with connect(settings.db_path) as conn:
        assert get_monitor_state(conn)["desired_state"] == "paused"


def test_web_scheduler_starts_next_successful_round_immediately(tmp_path):
    app = create_app(Settings.load(tmp_path))

    snapshot = app.state.monitor_scheduler.snapshot()

    assert snapshot["interval_seconds"] == 0
    assert snapshot["idle_interval_seconds"] == 60
    assert snapshot["limits"]["max_keywords"] == 1
    assert snapshot["limits"]["max_products_per_keyword"] == 1
    assert snapshot["limits"]["note_evidence"] is False


def test_capture_route_rejects_database_path_outside_capture_root(tmp_path):
    settings = Settings.load(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    with connect(settings.db_path) as conn:
        now = utcnow()
        conn.execute(
            """
            INSERT INTO observations(observed_at, source, screenshot_path, raw_signals_json)
            VALUES (?, 'test', ?, '{}')
            """,
            (now, str(outside)),
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    routes = {
        route.path: route.endpoint
        for route in create_app(settings).routes
        if hasattr(route, "endpoint")
    }
    try:
        routes["/captures/{observation_id}"](observation_id)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("capture route must reject paths outside capture_dir")


def test_run_once_route_rejects_active_risk_stop(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", "captcha detected")
    monkeypatch.setattr(
        "xhs_scout.web.monitor_once",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("monitor_once must not run while risk stop is active")
        ),
    )
    routes = {
        route.path: route.endpoint
        for route in create_app(settings).routes
        if hasattr(route, "endpoint")
    }

    try:
        routes["/api/monitor/run-once"]()
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("run-once must reject an active risk stop")
