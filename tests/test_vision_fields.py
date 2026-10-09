import json
from urllib.error import URLError

import pytest
from PIL import Image

import xhs_scout.monitor as monitor_module
from xhs_scout.config import Settings
from xhs_scout.db import connect, enqueue, get_monitor_state
from xhs_scout.ingest import ingest_image, persist_ingest_result
from xhs_scout.run_control import acquire_monitor_lease, reserve_next_runnable_task
from xhs_scout.signals import ProductSignals
from xhs_scout.vision_fields import (
    VisionFieldsError,
    extract_product_fields_with_vision,
    vision_fields_enabled,
)
from xhs_scout.workflow import capture_current_page_for_task


class _Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.raw


def _config(**overrides):
    config = {
        "enabled": True,
        "endpoint": "http://127.0.0.1:11434/api/chat",
        "model": "qwen3-vl:4b-instruct-q4_K_M",
        "timeout_seconds": 600,
    }
    config.update(overrides)
    return config


def test_local_ollama_response_is_strictly_parsed_once(tmp_path, monkeypatch):
    image = tmp_path / "detail.png"
    image.write_bytes(b"png-evidence")
    seen = {}

    def fake_open(request, *, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {
                "message": {
                    "content": json.dumps(
                        {
                            "title": "开学第一课/收心立规矩主题班会PPT+教案+逐字稿",
                            "price": 12.9,
                            "evidence": "到手价",
                        },
                        ensure_ascii=False,
                    )
                },
                "total_duration": 130_000_000_000,
                "load_duration": 300_000_000,
                "prompt_eval_duration": 119_000_000_000,
                "eval_duration": 10_000_000_000,
                "prompt_eval_count": 2579,
                "eval_count": 67,
            }
        )

    monkeypatch.setattr("xhs_scout.vision_fields.urlopen", fake_open)
    result = extract_product_fields_with_vision(image, _config())

    assert result["title"] == "开学第一课/收心立规矩主题班会PPT+教案+逐字稿"
    assert result["price"] == 12.9
    assert result["source"] == "ollama_vision"
    assert result["timing"]["total_seconds"] == 130.0
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["timeout"] == 600
    assert seen["payload"]["stream"] is False
    assert seen["payload"]["think"] is False
    assert seen["payload"]["format"]["required"] == [
        "title",
        "price",
        "evidence",
    ]
    prompt = seen["payload"]["messages"][0]["content"]
    assert "任务不是理解、概括或改写" in prompt
    assert "从第一个字符到最后一个字符再核对一遍" in prompt
    assert "一二三四五六" in prompt
    assert "title返回空字符串" in prompt
    assert len(seen["payload"]["messages"][0]["images"]) == 1


@pytest.mark.parametrize("enabled, expected", [(True, True), (False, False), ("true", False)])
def test_enabled_flag_must_be_literal_boolean(enabled, expected):
    assert vision_fields_enabled({"enabled": enabled}) is expected


def test_remote_endpoint_is_rejected_before_any_request(tmp_path, monkeypatch):
    image = tmp_path / "detail.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        "xhs_scout.vision_fields.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("不应访问远程接口")
        ),
    )
    with pytest.raises(VisionFieldsError, match="本机HTTP地址") as caught:
        extract_product_fields_with_vision(
            image,
            _config(endpoint="https://example.com/api/chat"),
        )
    assert caught.value.code == "vision_config_invalid"


@pytest.mark.parametrize(
    "content",
    [
        "```json\n{}\n```",
        json.dumps({"title": "标题", "price": None, "evidence": ""}),
        json.dumps({"title": "", "price": 12.9, "evidence": ""}),
        json.dumps({"title": "标题", "price": -1, "evidence": ""}),
    ],
)
def test_invalid_model_output_fails_closed(tmp_path, monkeypatch, content):
    image = tmp_path / "detail.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        "xhs_scout.vision_fields.urlopen",
        lambda *_args, **_kwargs: _Response({"message": {"content": content}}),
    )
    with pytest.raises(VisionFieldsError) as caught:
        extract_product_fields_with_vision(image, _config())
    assert caught.value.code == "vision_response_invalid"


def test_local_service_failure_preserves_machine_readable_evidence(
    tmp_path, monkeypatch
):
    image = tmp_path / "detail.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        "xhs_scout.vision_fields.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(VisionFieldsError) as caught:
        extract_product_fields_with_vision(image, _config())
    assert caught.value.code == "vision_service_unavailable"
    assert caught.value.evidence["model"] == "qwen3-vl:4b-instruct-q4_K_M"
    assert caught.value.evidence["screenshot"].endswith("detail.png")


def test_enabled_vision_owns_persisted_title_and_price_once(tmp_path, monkeypatch):
    settings = Settings.load(tmp_path)
    config_path = tmp_path / "config" / "vision_fields.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    image = tmp_path / "source.png"
    Image.new("RGB", (1080, 2340), "white").save(image)
    calls = []

    monkeypatch.setattr(
        "xhs_scout.ingest.extract_text",
        lambda _path: ("主图促销标题\n已售111", []),
    )
    monkeypatch.setattr(
        "xhs_scout.ingest.classify_page_evidence",
        lambda *_args, **_kwargs: ("product_detail", "test"),
    )
    monkeypatch.setattr(
        "xhs_scout.ingest.extract_layout_fields_with_roi_ocr",
        lambda **_kwargs: {
            "fields": {
                "title": {"field_value": "错误坐标标题"},
                "price": {"field_value": 129.0},
            }
        },
    )
    monkeypatch.setattr(
        "xhs_scout.ingest.parse_product_text",
        lambda _text: ProductSignals(cumulative_sales_exact=111),
    )

    def fake_vision(path, config):
        calls.append((path, config["model"]))
        return {
            "title": "新初一七年级开学第一课PPT，初一上学期开学家长会课件",
            "price": 98.9,
            "evidence": "到手价",
            "source": "ollama_vision",
            "model": config["model"],
        }

    monkeypatch.setattr(
        "xhs_scout.ingest.extract_product_fields_with_vision",
        fake_vision,
    )

    output = ingest_image(settings, image, source="test", persist=False)
    assert output["signals"]["title"] == (
        "新初一七年级开学第一课PPT，初一上学期开学家长会课件"
    )
    assert output["signals"]["price"] == 98.9
    assert output["vision_fields"]["source"] == "ollama_vision"
    assert len(calls) == 1

    persisted = persist_ingest_result(settings, output)
    assert persisted["product_id"] > 0
    assert len(calls) == 1
    with connect(settings.db_path) as conn:
        product = conn.execute("SELECT title, price FROM products").fetchone()
        raw = json.loads(
            conn.execute("SELECT raw_signals_json FROM observations").fetchone()[0]
        )
    assert product["title"] == (
        "新初一七年级开学第一课PPT，初一上学期开学家长会课件"
    )
    assert product["price"] == 98.9
    assert raw["vision_fields"]["model"] == "qwen3-vl:4b-instruct-q4_K_M"
    assert raw["layout_fields"]["fields"]["title"]["field_value"] == "错误坐标标题"


class _CaptureDevice:
    def window_focus(self):
        return (
            "mCurrentFocus=Window{abc u0 "
            "com.xingin.xhs/com.xingin.goods.detail.GoodsDetailActivityV2}"
        )

    def screenshot(self, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"screenshot")
        return destination

    def ui_dump(self):
        return '<hierarchy><node text="加入购物车"/></hierarchy>'


def test_vision_infrastructure_failure_refunds_attempt_and_writes_no_product(
    tmp_path, monkeypatch
):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["开学第一课PPT"], source="test")
        task_id = conn.execute(
            "SELECT id FROM search_tasks WHERE keyword='开学第一课PPT'"
        ).fetchone()[0]

    monkeypatch.setattr(
        "xhs_scout.workflow.ingest_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            VisionFieldsError(
                "vision_service_unavailable",
                "无法连接本地视觉模型",
                evidence={"screenshot": str(tmp_path / "captured.png")},
            )
        ),
    )
    output = capture_current_page_for_task(
        settings,
        _CaptureDevice(),
        task_id,
        run_id="vision-failure-run",
    )

    assert output["reason_code"] == "vision_fields_failure"
    assert output["hard_stop"] is True
    assert output["task_result"] is None
    assert output["task_disposition"]["attempt_returned"] is True
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(task) == ("pending", 0, None)
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == output["blocked"]
        event = conn.execute(
            "SELECT event, data_json FROM run_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert event["event"] == "vision_fields_hard_stop"
    assert json.loads(event["data_json"])["reason_code"] == "vision_fields_failure"


def test_monitor_vision_failure_uses_strict_dual_lease_and_refunds_attempt(tmp_path):
    settings = Settings.load(tmp_path)
    owner = "vision-monitor-run"
    with connect(settings.db_path) as conn:
        enqueue(conn, ["开学第一课PPT"], source="test")
        task_id = conn.execute(
            "SELECT id FROM search_tasks WHERE keyword='开学第一课PPT'"
        ).fetchone()[0]
        acquire_monitor_lease(conn, owner=owner, ttl_seconds=900)
        reserved = reserve_next_runnable_task(conn, owner=owner, task_id=task_id)
        assert reserved and reserved["attempts"] == 1

    with pytest.raises(monitor_module.VisionInfrastructureBlocked) as caught:
        monitor_module._raise_vision_fields_hard_stop(
            settings,
            run_id=owner,
            task_id=task_id,
            message="Ollama unavailable",
            evidence={"error_code": "vision_service_unavailable"},
            dry_run=False,
        )

    assert caught.value.failure["attempt_returned"] is True
    assert caught.value.failure["reason_code"] == "vision_fields_failure"
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        event = conn.execute(
            "SELECT event, data_json FROM run_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert tuple(task) == ("pending", 0, None)
    assert event["event"] == "vision_fields_hard_stop"
    assert json.loads(event["data_json"])["refunded_tasks"][0]["attempts_after"] == 0


def test_monitor_ui_tree_failure_refunds_infrastructure_attempt(tmp_path):
    settings = Settings.load(tmp_path)
    owner = "ui-tree-monitor-run"
    with connect(settings.db_path) as conn:
        enqueue(conn, ["开学第一课PPT"], source="test")
        task_id = conn.execute(
            "SELECT id FROM search_tasks WHERE keyword='开学第一课PPT'"
        ).fetchone()[0]
        acquire_monitor_lease(conn, owner=owner, ttl_seconds=900)
        reserved = reserve_next_runnable_task(conn, owner=owner, task_id=task_id)
        assert reserved and reserved["attempts"] == 1

    with pytest.raises(monitor_module.UiTreeInfrastructureBlocked) as caught:
        monitor_module._raise_ui_tree_hard_stop(
            settings,
            run_id=owner,
            task_id=task_id,
            message="empty UI tree after bounded retry",
            phase="search_product_tab",
            evidence={"probe_dir": "probe-example"},
            dry_run=False,
        )

    assert caught.value.failure["attempt_returned"] is True
    assert caught.value.failure["reason_code"] == "ui_tree_unavailable"
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        event = conn.execute(
            "SELECT event, data_json FROM run_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert tuple(task) == ("pending", 0, None)
    assert event["event"] == "ui_tree_hard_stop"
    assert json.loads(event["data_json"])["refunded_tasks"][0]["attempts_after"] == 0
