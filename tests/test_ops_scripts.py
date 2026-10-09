from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPS_DIR = PROJECT_ROOT / "ops"
PROJECT_PATH = r"C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"


def read_ops(name: str) -> str:
    return (OPS_DIR / name).read_text(encoding="utf-8")


def test_ops_files_exist_in_t5_scope():
    for name in [
        "start_workbench.ps1",
        "stop_workbench.ps1",
        "health_check.ps1",
        "install_scheduled_task.ps1",
    ]:
        assert (OPS_DIR / name).is_file()
    assert (PROJECT_ROOT / "OPERATIONS.md").is_file()


def test_scripts_embed_port_project_path_and_dry_run_controls():
    for name in [
        "start_workbench.ps1",
        "stop_workbench.ps1",
        "health_check.ps1",
        "install_scheduled_task.ps1",
    ]:
        text = read_ops(name)
        assert PROJECT_PATH in text
        assert "8793" in text
        assert "SupportsShouldProcess" in text

    for name in [
        "start_workbench.ps1",
        "stop_workbench.ps1",
        "install_scheduled_task.ps1",
    ]:
        text = read_ops(name)
        assert "[switch]$Execute" in text
        assert "[dry-run]" in text


def test_start_script_is_idempotent_and_does_not_stop_processes():
    text = read_ops("start_workbench.ps1")

    assert "Get-NetTCPConnection" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "CommandLine" in text
    assert "xhs_scout.cli" in text
    assert "serve" in text
    assert "Workbench already appears to be running" in text
    assert "Refusing to start or stop anything" in text
    assert "Start-Process" in text
    assert "Stop-Process" not in text
    assert '"--project-root=`"$normalizedRoot`""' in text
    assert '"--project-root `"$normalizedRoot`""' in text


def test_stop_script_requires_project_owned_8793_and_ignores_8765():
    text = read_ops("stop_workbench.ps1")

    assert "Get-NetTCPConnection" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "CommandLine" in text
    assert "IsProjectOwned" in text
    assert "xhs_scout.cli" in text
    assert "serve" in text
    assert "$Port -ne 8793" in text
    assert "8765" in text
    assert "Refusing to stop; no process was killed" in text
    assert "Stop-Process" in text
    assert '"--project-root=`"$normalizedRoot`""' in text
    assert '"--project-root `"$normalizedRoot`""' in text


def test_health_check_is_http_read_only_and_checks_project_owner():
    text = read_ops("health_check.ps1")

    assert "Invoke-WebRequest" in text
    assert "/api/status" in text
    assert "/api/monitor/status" in text
    assert "/export/candidates.csv" in text
    assert "Get-NetTCPConnection" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "IsProjectOwned" in text
    assert "ignored_port = 8765" in text
    assert "Stop-Process" not in text
    assert "Start-Process" not in text
    assert "Register-ScheduledTask" not in text


def test_scheduled_task_script_only_registers_when_execute_is_passed():
    text = read_ops("install_scheduled_task.ps1")

    assert "New-ScheduledTaskAction" in text
    assert "New-ScheduledTaskTrigger" in text
    assert "Register-ScheduledTask" in text
    assert "start_workbench.ps1" in text
    assert "-Execute" in text
    assert "XhsProductScoutWorkbench8793" in text
    assert "port 8765 is not used" in text
    assert "No scheduled task was registered" in text


def test_operations_doc_records_safe_usage_and_integration_boundary():
    text = (PROJECT_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")

    assert PROJECT_PATH in text
    assert "http://127.0.0.1:8793" in text
    assert "dry-run" in text
    assert "-Execute" in text
    assert "-WhatIf" in text
    assert "Win32_Process.CommandLine" in text
    assert "8765" in text
    assert "主对话" not in text
