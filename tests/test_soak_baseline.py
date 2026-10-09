import hashlib
import json
import pytest

from xhs_scout.soak_baseline import (
    SoakBaselineError,
    SoakBaselineIntegrityError,
    build_baseline_manifest,
    read_baseline_manifest,
    validate_baseline_manifest,
    write_baseline_manifest,
)


def _project(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "src" / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "config" / "settings.json").write_text(
        '{"enabled":true}\n', encoding="utf-8"
    )
    return root


def _values(root):
    return {
        "project_root": root,
        "code_files": ["src/worker.py"],
        "config_files": [root / "config" / "settings.json"],
        "database_statistics": {
            "quick_check": "ok",
            "journal_mode": "wal",
            "run_count": 3,
            "pending_tasks": 0,
        },
        "run_parameters": {
            "interval_seconds": 3600,
            "max_keywords": 1,
            "max_products_per_keyword": 1,
        },
        "port_owners": {
            "8793": {"owner": "xhs-workbench pid 123", "expected": True},
            "8765": {"owner": "isolated other service", "isolated": True},
        },
        "disk_summary": {"free_bytes": 10_000_000, "status": "observed by caller"},
        "log_summary": {"total_bytes": 2048, "error_count": 0},
        "operator": "operator-a",
        "stop_entry": {
            "procedure": "Use the documented pause endpoint and wait for return",
            "verified": True,
        },
    }


def _rehash(payload):
    unsigned = dict(payload)
    unsigned.pop("manifest_hash", None)
    payload["manifest_hash"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_build_is_deterministic_and_hashes_only_explicit_project_files(tmp_path):
    root = _project(tmp_path)
    first = build_baseline_manifest(**_values(root))
    second = build_baseline_manifest(**_values(root))

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.baseline_id.startswith("pre-soak-baseline-")
    files = first.sources["observed"]["files"]
    assert [item["category"] for item in files] == ["code", "config"]
    assert files[0]["sha256"] == hashlib.sha256(
        (root / "src" / "worker.py").read_bytes()
    ).hexdigest()
    assert first.sources["observed"]["file_set_sha256"]
    assert first.sources["caller_supplied"]["database_statistics"]["run_count"] == 3


def test_sources_are_explicitly_observed_or_caller_supplied(tmp_path):
    manifest = build_baseline_manifest(**_values(_project(tmp_path)))

    assert set(manifest.sources) == {"observed", "caller_supplied"}
    assert all(
        item["source"] == "observed"
        for item in manifest.sources["observed"]["files"]
    )
    assert "database_statistics" not in manifest.sources["observed"]
    assert "project_root" not in manifest.sources["caller_supplied"]


def test_manifest_never_authorizes_any_start(tmp_path):
    manifest = build_baseline_manifest(**_values(_project(tmp_path)))

    assert manifest.baseline_complete is True
    assert manifest.authorizes_start is False
    assert manifest.safety["pre_soak_start_authorized"] is False
    assert manifest.safety["soak_24h_start_authorized"] is False
    assert manifest.safety["scheduler_start_authorized"] is False
    assert "does not authorize" in manifest.safety["statement"]


def test_path_escape_and_absolute_outside_file_are_rejected(tmp_path):
    root = _project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("outside = True\n", encoding="utf-8")
    values = _values(root)

    values["code_files"] = ["../outside.py"]
    with pytest.raises(SoakBaselineError, match="outside project_root"):
        build_baseline_manifest(**values)

    values = _values(root)
    values["code_files"] = [outside]
    with pytest.raises(SoakBaselineError, match="outside project_root"):
        build_baseline_manifest(**values)


def test_symlink_to_outside_project_is_rejected(tmp_path):
    root = _project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("outside = True\n", encoding="utf-8")
    link = root / "src" / "outside-link.py"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink unavailable on this Windows host: {exc}")
    values = _values(root)
    values["code_files"] = [link]

    with pytest.raises(SoakBaselineError, match="outside project_root"):
        build_baseline_manifest(**values)


def test_resolved_symlink_escape_is_fail_closed_without_platform_privileges(
    tmp_path, monkeypatch
):
    root = _project(tmp_path)
    link = root / "src" / "simulated-link.py"
    link.write_text("placeholder = True\n", encoding="utf-8")
    outside = tmp_path / "resolved-outside.py"
    outside.write_text("outside = True\n", encoding="utf-8")
    original_resolve = type(link).resolve

    def simulated_resolve(self, strict=False):
        if self == link:
            return outside
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(type(link), "resolve", simulated_resolve)
    values = _values(root)
    values["code_files"] = [link]

    with pytest.raises(SoakBaselineError, match="outside project_root"):
        build_baseline_manifest(**values)


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("database_statistics", "credentials"),
        ("run_parameters", "api_token"),
        ("port_owners", "Cookie"),
        ("disk_summary", "password"),
        ("log_summary", "client-secret"),
        ("stop_entry", "refresh_tokens"),
    ],
)
def test_sensitive_fields_are_rejected_recursively(tmp_path, section, field):
    values = _values(_project(tmp_path))
    if section == "port_owners":
        values[section]["8793"]["nested"] = {field: "must-not-be-stored"}
    else:
        values[section]["nested"] = {field: "must-not-be-stored"}

    with pytest.raises(SoakBaselineError, match="sensitive field"):
        build_baseline_manifest(**values)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value["port_owners"].pop("8793"), "8793 and 8765"),
        (lambda value: value["port_owners"]["8765"].pop("owner"), "owner"),
        (lambda value: value.update(stop_entry={}), "stop_entry"),
        (
            lambda value: value["database_statistics"].pop("quick_check"),
            "quick_check",
        ),
        (
            lambda value: value["run_parameters"].pop("interval_seconds"),
            "interval_seconds",
        ),
    ],
)
def test_missing_critical_owner_stop_db_or_parameter_fails_closed(
    tmp_path, mutation, match
):
    values = _values(_project(tmp_path))
    mutation(values)

    with pytest.raises(SoakBaselineError, match=match):
        build_baseline_manifest(**values)


def test_bad_db_check_and_expanded_budget_fail_closed(tmp_path):
    values = _values(_project(tmp_path))
    values["database_statistics"]["quick_check"] = "database disk image is malformed"
    with pytest.raises(SoakBaselineError, match="quick_check must be ok"):
        build_baseline_manifest(**values)

    values = _values(_project(tmp_path / "other"))
    values["run_parameters"]["max_keywords"] = 2
    with pytest.raises(SoakBaselineError, match="1 keyword x 1 product"):
        build_baseline_manifest(**values)


def test_write_read_and_tampered_manifest_fail_closed(tmp_path):
    root = _project(tmp_path)
    manifest = build_baseline_manifest(**_values(root))
    path = write_baseline_manifest(
        root / "baseline.json", manifest, allowed_roots=[root]
    )

    assert read_baseline_manifest(path, allowed_roots=[root]) == manifest
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sources"]["caller_supplied"]["operator"] = "someone-else"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SoakBaselineIntegrityError, match="integrity hash"):
        read_baseline_manifest(path, allowed_roots=[root])


def test_rehashed_attempt_to_authorize_start_still_fails_closed(tmp_path):
    manifest = build_baseline_manifest(**_values(_project(tmp_path)))
    payload = manifest.as_dict()
    payload["safety"]["pre_soak_start_authorized"] = True
    _rehash(payload)

    with pytest.raises(SoakBaselineIntegrityError, match="never authorize"):
        validate_baseline_manifest(payload)


def test_changed_observed_file_invalidates_baseline(tmp_path):
    root = _project(tmp_path)
    manifest = build_baseline_manifest(**_values(root))
    (root / "src" / "worker.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(SoakBaselineIntegrityError, match="changed after baseline"):
        validate_baseline_manifest(manifest)


def test_manifest_output_path_and_symlink_escape_are_rejected(tmp_path):
    root = _project(tmp_path)
    manifest = build_baseline_manifest(**_values(root))

    with pytest.raises(SoakBaselineError, match="outside allowed roots"):
        write_baseline_manifest(
            tmp_path / "outside.json", manifest, allowed_roots=[root]
        )

    outside = tmp_path / "outside-dir"
    outside.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable on this Windows host: {exc}")
    with pytest.raises(SoakBaselineError, match="outside allowed roots"):
        write_baseline_manifest(
            link / "baseline.json", manifest, allowed_roots=[root]
        )


def test_unknown_or_sensitive_manifest_fields_are_rejected_even_if_rehashed(tmp_path):
    manifest = build_baseline_manifest(**_values(_project(tmp_path)))
    payload = manifest.as_dict()
    payload["sources"]["caller_supplied"]["database_statistics"]["access_token"] = (
        "must-not-be-stored"
    )
    _rehash(payload)

    with pytest.raises(SoakBaselineIntegrityError, match="sensitive field"):
        validate_baseline_manifest(payload, verify_files=False)
