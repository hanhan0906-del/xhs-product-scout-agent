import hashlib
import json
from copy import deepcopy

import pytest

from xhs_scout.soak_baseline import (
    build_baseline_manifest,
    write_baseline_manifest,
)
from xhs_scout.soak_readiness import (
    FAILED,
    INSUFFICIENT,
    NOT_REACHED,
    PASS,
    evaluate_soak_readiness,
)


AUTHORIZATION_KEYS = (
    "pre_soak_start_authorized",
    "soak_24h_start_authorized",
    "scheduler_start_authorized",
)


def _project(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "src" / "worker.py").write_text(
        "BASELINE_VALUE = 1\n",
        encoding="utf-8",
    )
    (root / "config" / "settings.json").write_text(
        '{"max_keywords":1,"max_products_per_keyword":1}\n',
        encoding="utf-8",
    )
    return root


def _baseline_values(root):
    return {
        "project_root": root,
        "code_files": ["src/worker.py"],
        "config_files": ["config/settings.json"],
        "database_statistics": {
            "quick_check": "ok",
            "journal_mode": "wal",
            "run_count": 3,
        },
        "run_parameters": {
            "interval_seconds": 3600,
            "max_keywords": 1,
            "max_products_per_keyword": 1,
        },
        "port_owners": {
            "8793": {"owner": "offline fixture owner"},
            "8765": {"owner": "isolated offline fixture"},
        },
        "disk_summary": {"status": "caller supplied fixture"},
        "log_summary": {"error_count": 0},
        "operator": "offline-operator",
        "stop_entry": {"procedure": "pause and wait for the current round"},
    }


def _g0_only_bundle():
    return {
        "soak_id": "baseline-readiness-integration",
        "evidence_kind": "simulation",
        "rounds": [],
        "offline_tests_passed": True,
        "sqlite_stress_passed": True,
        "scheduler_recovery_tested": True,
        "lease_safety_tested": True,
    }


def _rehash(payload):
    unsigned = {
        "schema_version": payload["schema_version"],
        "manifest_kind": payload["manifest_kind"],
        "status": payload["status"],
        "sources": payload["sources"],
        "safety": payload["safety"],
    }
    content_hash = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload["baseline_id"] = f"pre-soak-baseline-{content_hash[:16]}"
    signed = {"baseline_id": payload["baseline_id"], **unsigned}
    payload["manifest_hash"] = hashlib.sha256(
        json.dumps(
            signed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _assert_never_authorized(report):
    result = report.as_dict()
    assert report.pre_soak_start_authorized is False
    assert report.soak_24h_start_authorized is False
    assert report.scheduler_start_authorized is False
    for key in AUTHORIZATION_KEYS:
        assert result[key] is False
        assert report.summary[key] is False
        assert report.record["authorization"][key] is False
        assert report.record["baseline"][key] is False


def _assert_baseline_failed_closed(report, fragment):
    assert report.summary["baseline_status"] == FAILED
    assert report.summary["baseline_integrity_ok"] is False
    assert report.gates["G0"].status == FAILED
    assert fragment in " ".join(report.summary["baseline"]["gaps"])
    assert report.ready_for_pre_soak is False
    assert report.ready_for_24h_soak is False
    _assert_never_authorized(report)


@pytest.mark.parametrize("target", ["pre_soak", "24h_soak", "expansion"])
def test_deterministic_baseline_object_only_satisfies_its_evidence_gate(
    tmp_path,
    target,
):
    root = _project(tmp_path)
    first = build_baseline_manifest(**_baseline_values(root))
    second = build_baseline_manifest(**_baseline_values(root))

    assert first == second
    assert first.to_json() == second.to_json()
    report = evaluate_soak_readiness(
        _g0_only_bundle(),
        target=target,
        baseline_manifest=first,
    )

    assert report.summary["baseline_status"] == PASS
    assert report.summary["baseline_source"] == "manifest"
    assert report.summary["baseline_id"] == first.baseline_id
    assert report.summary["baseline_manifest_hash"] == first.manifest_hash
    assert report.record["baseline"]["files_reverified"] is True
    assert report.gates["G0"].status == PASS
    assert report.gates["G1"].status == INSUFFICIENT
    assert all(report.gates[name].status != PASS for name in ("G2", "G3", "G4", "G5"))
    assert report.gates["G6"].status == NOT_REACHED
    assert report.ready_for_pre_soak is False
    assert report.ready_for_24h_soak is False
    _assert_never_authorized(report)


def test_deterministic_baseline_explicit_path_is_reverified_by_readiness(tmp_path):
    root = _project(tmp_path)
    manifest = build_baseline_manifest(**_baseline_values(root))
    manifest_path = write_baseline_manifest(
        root / "evidence" / "baseline.json",
        manifest,
        allowed_roots=[root],
    )

    report = evaluate_soak_readiness(
        _g0_only_bundle(),
        baseline_manifest_path=manifest_path,
        baseline_allowed_roots=[root],
    )

    assert report.summary["baseline_status"] == PASS
    assert report.summary["baseline_source"] == "path"
    assert report.summary["baseline_id"] == manifest.baseline_id
    assert report.summary["baseline_manifest_hash"] == manifest.manifest_hash
    assert report.record["baseline"]["files_reverified"] is True
    assert report.gates["G0"].status == PASS
    assert report.gates["G1"].status == INSUFFICIENT
    assert report.ready_for_pre_soak is False
    assert report.ready_for_24h_soak is False
    _assert_never_authorized(report)


@pytest.mark.parametrize(
    ("relative_path", "replacement"),
    [
        ("src/worker.py", "BASELINE_VALUE = 2\n"),
        (
            "config/settings.json",
            '{"max_keywords":2,"max_products_per_keyword":1}\n',
        ),
    ],
)
def test_observed_code_or_config_drift_fails_readiness_closed(
    tmp_path,
    relative_path,
    replacement,
):
    root = _project(tmp_path)
    manifest = build_baseline_manifest(**_baseline_values(root))
    (root / relative_path).write_text(replacement, encoding="utf-8")

    report = evaluate_soak_readiness(
        _g0_only_bundle(),
        baseline_manifest=manifest,
    )

    _assert_baseline_failed_closed(report, "changed after baseline")


def test_bad_json_path_and_bad_hash_object_fail_readiness_closed(tmp_path):
    root = _project(tmp_path)
    bad_json_path = root / "bad-baseline.json"
    bad_json_path.write_text("{not-json}\n", encoding="utf-8")
    bad_json = evaluate_soak_readiness(
        _g0_only_bundle(),
        baseline_manifest_path=bad_json_path,
        baseline_allowed_roots=[root],
    )

    manifest = build_baseline_manifest(**_baseline_values(root))
    bad_hash_payload = manifest.as_dict()
    bad_hash_payload["manifest_hash"] = "0" * 64
    bad_hash = evaluate_soak_readiness(
        _g0_only_bundle(),
        baseline_manifest=bad_hash_payload,
    )

    _assert_baseline_failed_closed(bad_json, "cannot read baseline manifest")
    _assert_baseline_failed_closed(bad_hash, "integrity hash")


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (
            lambda payload: payload["sources"]["caller_supplied"][
                "port_owners"
            ]["8793"].update(owner=""),
            "port_owners.8793.owner",
        ),
        (
            lambda payload: payload["sources"]["caller_supplied"].update(
                stop_entry={}
            ),
            "stop_entry",
        ),
        (
            lambda payload: payload["sources"]["caller_supplied"][
                "database_statistics"
            ].update(quick_check="database disk image is malformed"),
            "quick_check must be ok",
        ),
        (
            lambda payload: payload["sources"]["caller_supplied"][
                "run_parameters"
            ].update(max_keywords=2),
            "1 keyword x 1 product",
        ),
        (
            lambda payload: payload["sources"]["caller_supplied"][
                "run_parameters"
            ].update(max_products_per_keyword=2),
            "1 keyword x 1 product",
        ),
    ],
)
def test_rehashed_critical_baseline_defects_fail_readiness_closed(
    tmp_path,
    mutation,
    fragment,
):
    manifest = build_baseline_manifest(**_baseline_values(_project(tmp_path)))
    payload = manifest.as_dict()
    mutation(payload)
    _rehash(payload)

    report = evaluate_soak_readiness(
        _g0_only_bundle(),
        baseline_manifest=payload,
    )

    _assert_baseline_failed_closed(report, fragment)


@pytest.mark.parametrize(
    "authorization_mutation",
    [
        lambda payload: payload["safety"].update(
            pre_soak_start_authorized=True
        ),
        lambda payload: payload["safety"].update(
            soak_24h_start_authorized=True
        ),
        lambda payload: payload["safety"].update(
            scheduler_start_authorized=True
        ),
        lambda payload: payload["sources"]["caller_supplied"][
            "run_parameters"
        ].update(manual_authorization=True),
        lambda payload: payload["sources"]["caller_supplied"][
            "port_owners"
        ]["8793"].update(scheduler_authorised=True),
        lambda payload: payload["sources"]["caller_supplied"][
            "stop_entry"
        ].update(authorization={"granted": True}),
    ],
)
def test_any_rehashed_true_authorization_fails_readiness_closed(
    tmp_path,
    authorization_mutation,
):
    manifest = build_baseline_manifest(**_baseline_values(_project(tmp_path)))
    payload = deepcopy(manifest.as_dict())
    authorization_mutation(payload)
    _rehash(payload)

    report = evaluate_soak_readiness(
        _g0_only_bundle(),
        baseline_manifest=payload,
    )

    _assert_baseline_failed_closed(report, "authoriz")
