from pathlib import Path

import pytest

import xhs_scout.monitor as monitor_module
import xhs_scout.note_observation as note_observation_module
from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    enqueue,
    get_monitor_state,
    record_ocr_timeout_hard_stop,
    set_monitor_desired_state,
)
from xhs_scout.probe import is_ocr_timeout_probe
from xhs_scout.run_control import acquire_monitor_lease, reserve_next_runnable_task


TIMEOUT_MESSAGE = "RapidOCR timed out after 60 seconds: current.png"


class _ProbeDevice:
    def window_focus(self):
        return (
            "mCurrentFocus=Window{abc u0 "
            "com.xingin.xhs/com.xingin.goods.detail.GoodsDetailActivityV2}"
        )

    def ui_dump(self):
        return "<hierarchy />"


def _one_task(settings: Settings, keyword: str) -> int:
    with connect(settings.db_path) as conn:
        enqueue(conn, [keyword], source="test")
        return int(
            conn.execute(
                "SELECT id FROM search_tasks WHERE keyword=?", (keyword,)
            ).fetchone()[0]
        )


def _timeout_probe(tmp_path: Path, **overrides) -> dict:
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    screenshot = probe_dir / "current.png"
    screenshot.write_bytes(b"structured timeout evidence")
    probe = {
        "page_kind": "ocr_timeout",
        "ocr_timeout": True,
        "reason_code": "ocr_timeout",
        "infrastructure_failure": True,
        "exception": {
            "type": "OcrTimeoutError",
            "message": TIMEOUT_MESSAGE,
        },
        "ocr_error": TIMEOUT_MESSAGE,
        "risk_stop_reason": TIMEOUT_MESSAGE,
        "probe_dir": str(probe_dir),
        "screenshot": str(screenshot),
        "activity": _ProbeDevice().window_focus(),
    }
    probe.update(overrides)
    return probe


def _offline_report(settings: Settings, limit: int = 20) -> dict:
    return {
        "report_path": str(settings.reports_dir / "strict-ocr-contract.md"),
        "count": 0,
        "limit": limit,
    }


def test_timeout_probe_predicate_is_strict_and_note_calls_propagate_it(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    timeout_probe = _timeout_probe(tmp_path)
    incomplete_probe = dict(timeout_probe)
    incomplete_probe.pop("infrastructure_failure")

    assert is_ocr_timeout_probe(timeout_probe) is True
    assert is_ocr_timeout_probe(incomplete_probe) is False

    monkeypatch.setattr(
        note_observation_module,
        "probe_current_page",
        lambda *_args, **_kwargs: timeout_probe,
    )
    assert (
        note_observation_module.open_related_note_once(
            settings,
            _ProbeDevice(),
            product_id=None,
        )
        is timeout_probe
    )
    assert (
        note_observation_module.open_note_author_profile_once(
            settings,
            _ProbeDevice(),
            product_id=None,
        )
        is timeout_probe
    )


def test_strict_dual_lease_returns_attempt_only_once(tmp_path):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "strict dual lease")
    owner = "strict-dual-lease"

    with connect(settings.db_path) as conn:
        acquire_monitor_lease(conn, owner=owner, ttl_seconds=900)
        reserved = reserve_next_runnable_task(conn, owner=owner, task_id=task_id)
        assert reserved and reserved["attempts"] == 1

        first = record_ocr_timeout_hard_stop(
            conn,
            run_id=owner,
            owner=owner,
            reason="OCR infrastructure timeout: strict contract",
            phase="probe_ocr",
            task_id=task_id,
            require_active_monitor_lease=True,
        )
        second = record_ocr_timeout_hard_stop(
            conn,
            run_id=owner,
            owner=owner,
            reason="OCR infrastructure timeout: duplicate disposition",
            phase="probe_ocr",
            task_id=task_id,
            require_active_monitor_lease=True,
        )

        assert first["attempt_returned"] is True
        assert first["refunded_tasks"][0]["attempts_after"] == 0
        assert second["attempt_returned"] is False
        assert second["refunded_tasks"] == []
        assert second["lease_safety_blocked"]["reason"] == "task_not_running"
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(task) == ("pending", 0, None)


@pytest.mark.parametrize(
    ("invalid_lease", "expected_reason"),
    [
        ("task_expired", "task_lease_expired"),
        ("monitor_replaced", "monitor_owner_mismatch"),
    ],
)
def test_strict_lease_failure_is_structured_and_never_refunds(
    tmp_path,
    invalid_lease,
    expected_reason,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, f"strict failure {invalid_lease}")
    owner = f"owner-{invalid_lease}"

    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")
        acquire_monitor_lease(conn, owner=owner, ttl_seconds=900)
        reserved = reserve_next_runnable_task(conn, owner=owner, task_id=task_id)
        assert reserved and reserved["attempts"] == 1
        if invalid_lease == "task_expired":
            conn.execute(
                "UPDATE search_tasks SET run_lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", task_id),
            )
        else:
            conn.execute(
                """
                UPDATE run_leases
                SET owner=?, expires_at=?
                WHERE name='monitor_once'
                """,
                ("replacement-owner", "2999-01-01T00:00:00+00:00"),
            )

        disposition = record_ocr_timeout_hard_stop(
            conn,
            run_id=owner,
            owner=owner,
            reason="OCR infrastructure timeout: lease invalid",
            phase="probe_ocr",
            task_id=task_id,
            require_active_monitor_lease=True,
        )

        assert disposition["attempt_returned"] is False
        assert disposition["refunded_tasks"] == []
        assert disposition["lease_safety_blocked"]["reason"] == expected_reason
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(task) == ("running", 1, owner)
        state = get_monitor_state(conn)
        assert state["desired_state"] == "paused"
        assert state["risk_stop_reason"] == disposition["reason"]


def test_incomplete_probe_does_not_trigger_timeout_attempt_return(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "incomplete OCR probe")
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    incomplete_probe = _timeout_probe(tmp_path)
    incomplete_probe.pop("reason_code")
    device = _ProbeDevice()
    monkeypatch.setattr(monitor_module, "_device", lambda _settings: device)

    def stop_on_incomplete(_settings, called_device, *, run_id, task, limits):
        monitor_module._guard_probe(
            _settings,
            run_id,
            incomplete_probe,
            task["id"],
            device=called_device,
            dry_run=limits.dry_run,
        )
        raise monitor_module.MonitorBlocked(
            "incomplete OCR timeout probe contract",
            hard=True,
        )

    monkeypatch.setattr(monitor_module, "_open_search_results", stop_on_incomplete)
    monkeypatch.setattr(monitor_module, "generate_candidate_report", _offline_report)

    output = monitor_module.monitor_once(
        settings,
        limits=monitor_module.MonitorLimits(
            max_keywords=1,
            max_products_per_keyword=1,
            requeue_due_keywords=False,
            wait_seconds=0,
        ),
    )

    assert output["blocked"].startswith("risk stop: ")
    assert output.get("reason_code") != "ocr_timeout"
    assert "ocr_timeout" not in output
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT attempts FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert task["attempts"] == 1


def test_monitor_owner_change_returns_fail_closed_dictionary_without_second_refund(
    tmp_path,
    monkeypatch,
):
    settings = Settings.load(tmp_path)
    task_id = _one_task(settings, "monitor owner replacement")
    with connect(settings.db_path) as conn:
        set_monitor_desired_state(conn, "running")

    timeout_probe = _timeout_probe(tmp_path)
    device = _ProbeDevice()
    monkeypatch.setattr(monitor_module, "_device", lambda _settings: device)

    def replace_owner_then_timeout(
        _settings,
        called_device,
        *,
        run_id,
        task,
        limits,
    ):
        with connect(settings.db_path) as conn:
            conn.execute(
                """
                UPDATE run_leases
                SET owner=?, expires_at=?
                WHERE name='monitor_once'
                """,
                ("replacement-owner", "2999-01-01T00:00:00+00:00"),
            )
        monitor_module._guard_probe(
            _settings,
            run_id,
            timeout_probe,
            task["id"],
            device=called_device,
            dry_run=limits.dry_run,
        )
        raise AssertionError("valid OCR timeout contract must stop the monitor")

    monkeypatch.setattr(
        monitor_module,
        "_open_search_results",
        replace_owner_then_timeout,
    )
    monkeypatch.setattr(monitor_module, "generate_candidate_report", _offline_report)

    output = monitor_module.monitor_once(
        settings,
        limits=monitor_module.MonitorLimits(
            max_keywords=1,
            max_products_per_keyword=1,
            requeue_due_keywords=False,
            wait_seconds=0,
        ),
    )

    assert isinstance(output, dict)
    assert output["reason_code"] == "ocr_timeout"
    assert output["attempt_returned"] is False
    assert output["ocr_timeout"]["attempt_returned"] is False
    assert (
        output["lease_safety_blocked"]["reason"]
        == "monitor_owner_mismatch"
    )
    with connect(settings.db_path) as conn:
        task = conn.execute(
            "SELECT status, attempts, run_owner FROM search_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert task["status"] == "running"
        assert task["attempts"] == 1
        assert task["run_owner"] == output["run_id"]
        assert get_monitor_state(conn)["desired_state"] == "paused"
