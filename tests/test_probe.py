from xhs_scout.config import Settings
from xhs_scout.ocr import OcrWorkerError
from xhs_scout.probe import _focused_activity, is_ocr_timeout_probe, probe_current_page


class _FakeDevice:
    def window_focus(self):
        return (
            "mCurrentFocus=Window{abc u0 "
            "com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity}"
        )

    def screenshot(self, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-but-present-png-bytes")
        return destination

    def ui_dump(self):
        return "<hierarchy />"


def test_probe_current_page_converts_ocr_worker_error_into_infrastructure_probe(
    tmp_path, monkeypatch
):
    """Regression test: production run monitor-eceec6274ab2 hit
    ``OcrWorkerError: RapidOCR worker failed: OSError: image file is
    truncated`` inside ``probe_current_page``. Only ``OcrTimeoutError`` was
    caught there, so the worker error propagated as a bare unhandled
    exception, ending the run and consuming a task attempt with the
    generic reason ``monitor run ended before task completion`` instead of
    going through the existing OCR-infrastructure hard-stop/refund
    contract."""

    settings = Settings.load(tmp_path)
    worker_error = OcrWorkerError(
        "RapidOCR worker failed: OSError: image file is truncated; "
        "evidence=/probes/x/.ocr-diagnostics/y.json",
        diagnostics={"evidence_path": "/probes/x/.ocr-diagnostics/y.json"},
    )
    monkeypatch.setattr(
        "xhs_scout.probe.extract_text",
        lambda *_a, **_k: (_ for _ in ()).throw(worker_error),
    )

    result = probe_current_page(settings, _FakeDevice(), run_id="test-ocr-worker-error")

    assert result["page_kind"] == "ocr_timeout"
    assert result["reason_code"] == "ocr_timeout"
    assert result["infrastructure_failure"] is True
    assert result["ocr_timeout"] is True
    assert result["exception"]["type"] == "OcrWorkerError"
    assert "image file is truncated" in result["exception"]["message"]
    assert is_ocr_timeout_probe(result) is True


def test_focused_activity_extracts_current_focus():
    dump = "mCurrentFocus=Window{5b54568 u0 com.xingin.xhs/com.xingin.IndexActivity}"
    assert _focused_activity(dump) == "com.xingin.xhs/com.xingin.IndexActivity"


def test_focused_activity_extracts_miui_mode_and_root_task_format():
    dump = (
        "mCurrentFocus=Window{8b159e5 mode=0 rootTaskId=26 u0 "
        "com.xingin.xhs/com.xingin.commercial.shoppage.ShopDetailActivity}"
    )
    assert _focused_activity(dump) == (
        "com.xingin.xhs/com.xingin.commercial.shoppage.ShopDetailActivity"
    )


def test_focused_activity_handles_missing_value():
    assert _focused_activity("no current focus") is None
