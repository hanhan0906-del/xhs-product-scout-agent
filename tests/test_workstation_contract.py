from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from xhs_scout.config import Settings
from xhs_scout.db import connect, set_monitor_state, utcnow
from xhs_scout.web import create_app


@dataclass
class _Response:
    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.content)


class _ASGITestClient:
    """Small dependency-free client that exercises the complete ASGI route stack."""

    def __init__(self, app):
        self.app = app

    def get(self, path: str) -> _Response:
        return self._request("GET", path)

    def post(self, path: str, *, json: Any = None) -> _Response:
        body = b""
        headers: list[tuple[bytes, bytes]] = []
        if json is not None:
            body = __import__("json").dumps(json).encode()
            headers.append((b"content-type", b"application/json"))
        return self._request("POST", path, body=body, headers=headers)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> _Response:
        async def invoke() -> _Response:
            messages: list[dict[str, Any]] = []
            request_sent = False

            async def receive():
                nonlocal request_sent
                if request_sent:
                    return {"type": "http.disconnect"}
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}

            async def send(message):
                messages.append(message)

            await self.app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.3"},
                    "http_version": "1.1",
                    "method": method,
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"",
                    "root_path": "",
                    "headers": headers or [],
                    "client": ("testclient", 50000),
                    "server": ("testserver", 80),
                    "state": {},
                },
                receive,
                send,
            )
            start = next(item for item in messages if item["type"] == "http.response.start")
            content = b"".join(
                item.get("body", b"")
                for item in messages
                if item["type"] == "http.response.body"
            )
            return _Response(
                status_code=start["status"],
                headers={
                    key.decode("latin-1"): value.decode("latin-1")
                    for key, value in start["headers"]
                },
                content=content,
            )

        return asyncio.run(invoke())


def _build_workstation(tmp_path):
    settings = Settings.load(tmp_path)
    (settings.root / "config" / "keyword_portfolio.json").write_text(
        json.dumps(
            {
                "version": 1,
                "policy": {
                    "hourly_budget": 2,
                    "per_round_budget": 1,
                    "keyword_cooldown_hours": 24,
                    "core_share": 1,
                },
                "categories": [
                    {
                        "id": "study",
                        "label": "学习资料",
                        "layer": "core",
                        "priority": 100,
                        "seed_terms": ["小学学习资料"],
                        "modifiers": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    capture = settings.capture_dir / "product-1.png"
    capture.write_bytes(b"contract-capture")
    outside = settings.root / "outside-secret.txt"
    outside.write_text("must not be served", encoding="utf-8")

    with connect(settings.db_path) as conn:
        now = utcnow()
        conn.execute(
            """
            INSERT INTO search_tasks(
                keyword, source, priority, status, created_at, updated_at
            ) VALUES ('小学学习资料', 'contract', 100, 'pending', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, shop_name, share_url, price, is_virtual,
                virtual_confidence, first_seen_at, last_seen_at
            ) VALUES (
                'contract-product', '小学学习资料包', '资料店',
                'https://www.xiaohongshu.com/goods-detail/contract-product',
                19.9, 1, 1, ?, ?
            )
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO observations(
                product_id, observed_at, source, screenshot_path, raw_text,
                cumulative_sales_min, sales_30d_min,
                positive_reviews_30d_min, raw_signals_json
            ) VALUES (?, ?, 'contract', ?, 'contract evidence', 1200, 500, 300, '{}')
            """,
            (product_id, now, str(capture)),
        )
        inside_observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score,
                low_follower_verified, reasons_json, status
            ) VALUES (?, ?, 'B', 68.5, 0, '["趋势证据完整"]', 'candidate')
            """,
            (product_id, now),
        )
        conn.execute(
            """
            INSERT INTO observations(
                observed_at, source, screenshot_path, raw_signals_json
            ) VALUES (?, 'contract-outside', ?, '{}')
            """,
            (now, str(outside)),
        )
        outside_observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return (
        settings,
        _ASGITestClient(create_app(settings)),
        inside_observation_id,
        outside_observation_id,
    )


def test_workstation_status_and_insight_endpoints_form_one_public_contract(tmp_path):
    _settings, client, _inside_id, _outside_id = _build_workstation(tmp_path)

    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert {"quality", "digest", "portfolio"} <= status.keys()
    assert status["quality"]["summary"]["issue_count"] >= 0
    assert status["digest"]["stats"]["period"] == "daily"
    assert status["portfolio"]["version"] == 1

    quality = client.get("/api/quality")
    daily = client.get("/api/digest/daily")
    weekly = client.get("/api/digest/weekly")
    portfolio = client.get("/api/portfolio")
    assert [response.status_code for response in (quality, daily, weekly, portfolio)] == [
        200,
        200,
        200,
        200,
    ]
    assert quality.json()["scope"]["products"] == 1
    assert daily.json()["stats"]["period"] == "daily"
    assert weekly.json()["stats"]["period"] == "weekly"
    assert portfolio.json()["budget"]["per_round_budget"] == 1


def test_home_keeps_logs_out_and_uses_product_links_without_capture_column(tmp_path):
    _settings, client, inside_id, _outside_id = _build_workstation(tmp_path)

    home = client.get("/")
    assert home.status_code == 200
    html = home.text
    for forbidden in ("/api/run-events", "recent_run_events", "运行事件日志", "运行日志"):
        assert forbidden not in html

    assert "证据截图" not in html
    assert "搜索关键词" in html
    assert "safeProductDirectUrl(item.direct_url)" in html
    assert "safeProductShareUrl(item.share_url)" in html
    assert "makeProduct(item)" in html
    assert "makeCaptureLink(item)" not in html
    assert "search_result_rank" not in html

    recent = client.get("/api/status").json()["recent"][0]
    assert recent["share_url"] == (
        "https://www.xiaohongshu.com/goods-detail/contract-product"
    )
    assert recent["observation_id"] == inside_id


def test_risk_stop_rejects_run_once_before_monitor_execution(tmp_path, monkeypatch):
    settings, client, _inside_id, _outside_id = _build_workstation(tmp_path)
    with connect(settings.db_path) as conn:
        set_monitor_state(conn, "risk_stop_reason", "captcha detected")

    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("monitor_once must remain behind the risk-stop gate")

    monkeypatch.setattr("xhs_scout.web.monitor_once", fail_if_called)
    response = client.post("/api/monitor/run-once", json={})

    assert response.status_code == 409
    assert "风险停止仍生效" in response.json()["detail"]
    assert called is False


def test_run_once_does_not_requeue_due_keywords(tmp_path, monkeypatch):
    settings, client, _inside_id, _outside_id = _build_workstation(tmp_path)
    observed = {}

    def capture_limits(_settings, *, limits, ignore_paused):
        observed["limits"] = limits
        observed["ignore_paused"] = ignore_paused
        return {"processed_tasks": 0}

    monkeypatch.setattr("xhs_scout.web.monitor_once", capture_limits)
    response = client.post("/api/monitor/run-once", json={})

    assert response.status_code == 200
    assert observed["ignore_paused"] is True
    assert observed["limits"].requeue_due_keywords is False


def test_run_once_forwards_the_requested_search_result_rank(tmp_path, monkeypatch):
    """A controlled single run must reach the exact rank it was asked for.

    Only the scheduler derives the rank from continuous discovery.  Without an
    explicit passthrough this endpoint silently ran rank 1 while the operator
    believed a rank 2+ task was being collected, which both duplicates the
    rank 1 product and marks the higher-rank task complete.
    """

    _settings, client, _inside_id, _outside_id = _build_workstation(tmp_path)
    observed = {}

    def capture_limits(_settings, *, limits, ignore_paused):
        observed["limits"] = limits
        return {"processed_tasks": 0}

    monkeypatch.setattr("xhs_scout.web.monitor_once", capture_limits)
    response = client.post(
        "/api/monitor/run-once",
        json={
            "task_id": 183,
            "expected_keyword": "开学第一课PPT",
            "search_result_rank": 2,
            "search_card_scan_limit": 5,
        },
    )

    assert response.status_code == 200
    assert observed["limits"].task_id == 183
    assert observed["limits"].expected_keyword == "开学第一课PPT"
    assert observed["limits"].search_result_rank == 2
    assert observed["limits"].search_card_scan_limit == 5


def test_run_once_keeps_rank_one_default_and_rejects_out_of_range(tmp_path, monkeypatch):
    _settings, client, _inside_id, _outside_id = _build_workstation(tmp_path)
    observed = {}

    def capture_limits(_settings, *, limits, ignore_paused):
        observed["limits"] = limits
        return {"processed_tasks": 0}

    monkeypatch.setattr("xhs_scout.web.monitor_once", capture_limits)

    default = client.post("/api/monitor/run-once", json={})
    assert default.status_code == 200
    assert observed["limits"].search_result_rank == 1
    assert observed["limits"].search_card_scan_limit == 3

    # rank 6 is beyond the five-product-per-keyword contract
    assert client.post(
        "/api/monitor/run-once", json={"search_result_rank": 6}
    ).status_code == 422
    assert client.post(
        "/api/monitor/run-once", json={"search_result_rank": 0}
    ).status_code == 422


def test_capture_route_serves_only_files_beneath_capture_dir(tmp_path):
    _settings, client, inside_id, outside_id = _build_workstation(tmp_path)

    inside = client.get(f"/captures/{inside_id}")
    outside = client.get(f"/captures/{outside_id}")

    assert inside.status_code == 200
    assert inside.content == b"contract-capture"
    assert outside.status_code == 404
    assert outside.json()["detail"] == "截图不存在"
