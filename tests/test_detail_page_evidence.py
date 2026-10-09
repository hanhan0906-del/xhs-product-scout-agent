import json
from pathlib import Path

from xhs_scout.config import Settings
from xhs_scout.db import connect, enqueue
from xhs_scout.ingest import ingest_image
from xhs_scout.probe import classify_page_evidence
from xhs_scout.signals import classify_page_text
from xhs_scout.workflow import capture_current_page_for_task


ROOT = Path(__file__).resolve().parents[1]
REAL_PROBE_DIR = (
    ROOT
    / "data"
    / "probes"
    / "monitor-c8b5f1a49b1d-probe-detail-114"
)
COUPON_DETAIL_PROBE_DIR = (
    ROOT
    / "data"
    / "probes"
    / "monitor-5090e67db887-probe-detail-187"
)


def _real_detail_evidence() -> tuple[dict, str]:
    probe = json.loads((REAL_PROBE_DIR / "probe.json").read_text(encoding="utf-8"))
    xml_text = (REAL_PROBE_DIR / "window.xml").read_text(encoding="utf-8")
    return probe, xml_text


def test_real_detail_replay_requires_strict_activity_and_ui_fallback():
    probe, xml_text = _real_detail_evidence()

    assert classify_page_text(probe["text"]) == "unknown"
    assert classify_page_evidence(
        probe["text"],
        activity=probe["activity"],
        ui_tree=xml_text,
    ) == ("product_detail", "strict_product_detail_ui")


def test_real_coupon_purchase_detail_is_still_strict_product_detail():
    probe = json.loads(
        (COUPON_DETAIL_PROBE_DIR / "probe.json").read_text(encoding="utf-8")
    )
    xml_text = (COUPON_DETAIL_PROBE_DIR / "window.xml").read_text(
        encoding="utf-8"
    )

    assert classify_page_text(probe["text"]) == "unknown"
    assert "领券购买" in probe["text"]
    assert classify_page_evidence(
        probe["text"],
        activity=probe["activity"],
        ui_tree=xml_text,
    ) == ("product_detail", "strict_product_detail_ui")


def test_ui_risk_guard_wins_over_underlying_product_controls():
    probe, xml_text = _real_detail_evidence()
    guarded_xml = xml_text.replace(
        "</hierarchy>",
        '<node text="请完成验证" content-desc="安全验证" bounds="[0,0][1080,2400]" />'
        "</hierarchy>",
    )

    assert classify_page_evidence(
        probe["text"],
        activity=probe["activity"],
        ui_tree=guarded_xml,
    ) == ("risk_stop", "ocr_ui_guard")


def test_strict_detail_fallback_rejects_wrong_activity_or_incomplete_shell():
    probe, xml_text = _real_detail_evidence()
    incomplete_xml = xml_text.replace(
        'text="立即购买"', 'text="查看详情"', 1
    )

    assert classify_page_evidence(
        probe["text"],
        activity="com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity",
        ui_tree=xml_text,
    )[0] == "unknown"
    assert classify_page_evidence(
        probe["text"],
        activity=probe["activity"],
        ui_tree=incomplete_xml,
    )[0] == "unknown"


def test_required_detail_mismatch_is_rejected_before_database_writes(
    tmp_path, monkeypatch
):
    probe, _ = _real_detail_evidence()
    settings = Settings.load(tmp_path)
    image = tmp_path / "capture.png"
    image.write_bytes(b"offline-image")
    monkeypatch.setattr(
        "xhs_scout.ingest.extract_text",
        lambda _path: (probe["text"], []),
    )

    output = ingest_image(
        settings,
        image,
        source="test",
        activity=probe["activity"],
        ui_tree="",
        required_page_kind="product_detail",
    )

    assert output["page_kind"] == "unknown"
    assert output["page_kind_mismatch"] is True
    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_ui_risk_is_rejected_before_database_writes(tmp_path, monkeypatch):
    probe, xml_text = _real_detail_evidence()
    guarded_xml = xml_text.replace(
        "</hierarchy>",
        '<node text="请完成验证" content-desc="安全验证" bounds="[0,0][1080,2400]" />'
        "</hierarchy>",
    )
    settings = Settings.load(tmp_path)
    image = tmp_path / "capture.png"
    image.write_bytes(b"offline-image")
    monkeypatch.setattr(
        "xhs_scout.ingest.extract_text",
        lambda _path: (probe["text"], []),
    )

    output = ingest_image(
        settings,
        image,
        source="test",
        activity=probe["activity"],
        ui_tree=guarded_xml,
        required_page_kind="product_detail",
    )

    assert output["risk_stopped"] is True
    assert output["page_kind"] == "risk_stop"
    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_strict_detail_context_allows_ingest_and_persistence(tmp_path, monkeypatch):
    probe, xml_text = _real_detail_evidence()
    settings = Settings.load(tmp_path)
    image = tmp_path / "capture.png"
    image.write_bytes(b"offline-image")
    monkeypatch.setattr(
        "xhs_scout.ingest.extract_text",
        lambda _path: (probe["text"], []),
    )

    output = ingest_image(
        settings,
        image,
        source="test",
        activity=probe["activity"],
        ui_tree=xml_text,
        required_page_kind="product_detail",
    )

    assert output["page_kind"] == "product_detail"
    assert output["page_kind_source"] == "strict_product_detail_ui"
    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


class _CaptureDevice:
    def __init__(self, activity: str, xml_text: str):
        self.activity = activity
        self.xml_text = xml_text

    def window_focus(self):
        return f"mCurrentFocus=Window{{abc u0 {self.activity}}}"

    def screenshot(self, destination):
        destination.write_bytes(b"offline-image")
        return destination

    def ui_dump(self):
        return self.xml_text


def test_monitor_mode_returns_disposition_without_ending_task(tmp_path, monkeypatch):
    probe, xml_text = _real_detail_evidence()
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        enqueue(conn, ["话术"], source="test")
        task_id = conn.execute("SELECT id FROM search_tasks").fetchone()[0]

    seen = {}

    def fake_ingest(_settings, _image, **kwargs):
        seen.update(kwargs)
        return {
            "page_kind": "unknown",
            "page_kind_source": "ocr_ui_unclassified",
        }

    monkeypatch.setattr("xhs_scout.workflow.ingest_image", fake_ingest)
    output = capture_current_page_for_task(
        settings,
        _CaptureDevice(probe["activity"], xml_text),
        task_id,
        run_id="monitor-test",
        complete_task=False,
        manage_task_state=False,
    )

    assert seen["activity"] == probe["activity"]
    assert seen["ui_tree"] == xml_text
    assert seen["required_page_kind"] == "product_detail"
    assert output["task_disposition"] == {
        "status": "needs_manual_detail",
        "reason": "当前页不是商品详情页：unknown",
    }
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, run_owner FROM search_tasks WHERE id=?", (task_id,)
        ).fetchone()
        assert tuple(task) == ("running", "monitor-test")
