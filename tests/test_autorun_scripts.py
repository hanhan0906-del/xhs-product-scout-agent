import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPS = PROJECT_ROOT / "ops"
AUTORUN = OPS / "autorun"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_autorun_files_and_default_config_are_fail_closed():
    expected = [
        OPS / "install_scheduled_task.ps1",
        OPS / "uninstall_scheduled_task.ps1",
        AUTORUN / "invoke_autorun.ps1",
        AUTORUN / "get_autorun_status.ps1",
        AUTORUN / "autorun.config.example.json",
        AUTORUN / "README.md",
    ]
    assert all(path.is_file() for path in expected)
    config = json.loads(read(AUTORUN / "autorun.config.example.json"))
    assert config == {
        "schema_version": 1,
        "service_recovery_enabled": True,
        "scheduler_recovery_enabled": False,
        "scheduler_resume_requires_persisted_running_intent": True,
    }


def test_installer_is_dry_run_before_any_task_scheduler_cmdlet():
    text = read(OPS / "install_scheduled_task.ps1")
    dry_run = text.index('if (-not $Execute)')
    assert dry_run < text.index("New-ScheduledTaskAction")
    assert dry_run < text.index("New-ScheduledTaskTrigger")
    assert dry_run < text.index("Register-ScheduledTask")
    assert "invoke_autorun.ps1" in text
    assert "-Port 8793" not in text
    assert "port 8765 is not used" in text
    assert "-Force" in text


def test_uninstaller_is_dry_run_and_only_removes_named_task():
    text = read(OPS / "uninstall_scheduled_task.ps1")
    dry_run = text.index('if (-not $Execute)')
    assert dry_run < text.index("Get-ScheduledTask")
    assert dry_run < text.index("Unregister-ScheduledTask")
    assert "Stop-Process" not in text
    assert "start_workbench" not in text
    assert "8793" in text and "8765" in text


def test_autorun_separates_service_recovery_from_scheduler_recovery():
    text = read(AUTORUN / "invoke_autorun.ps1")
    assert "service_recovery_enabled" in text
    assert "scheduler_recovery_enabled" in text
    assert "service_recovery_does_not_imply_collection_recovery" in text
    assert '"-Port", "8793", "-Execute"' in text
    assert "/api/monitor/status" in text
    assert "/api/status" in text
    assert "/api/monitor/resume" in text
    assert "/api/monitor/risk-resume" not in text
    assert "risk_stop_reason" in text
    assert 'desired_state -ne "running"' in text
    assert "8765" in text


def test_status_query_does_not_touch_task_scheduler_by_default():
    text = read(AUTORUN / "get_autorun_status.ps1")
    assert "IncludeTaskScheduler" in text
    assert text.index("if ($IncludeTaskScheduler)") < text.index("Get-ScheduledTask")
    assert "Invoke-WebRequest" not in text
    assert "Invoke-RestMethod" not in text


def test_powershell_scripts_parse_without_execution():
    scripts = [
        OPS / "install_scheduled_task.ps1",
        OPS / "uninstall_scheduled_task.ps1",
        AUTORUN / "invoke_autorun.ps1",
        AUTORUN / "get_autorun_status.ps1",
    ]
    quoted = ",".join("'" + str(path).replace("'", "''") + "'" for path in scripts)
    command = (
        "$errors=@();"
        f"@({quoted}) | ForEach-Object {{"
        "[void][System.Management.Automation.Language.Parser]::ParseFile($_,[ref]$null,[ref]$errors)"
        "}; if($errors.Count){$errors | Out-String | Write-Error; exit 1}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_autorun_dry_run_has_no_runtime_side_effects(tmp_path):
    config = tmp_path / "autorun.json"
    config.write_text(read(AUTORUN / "autorun.config.example.json"), encoding="utf-8")
    log_dir = OPS / "logs" / "autorun"
    before = sorted(path.name for path in log_dir.glob("*") if path.is_file()) if log_dir.exists() else []
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-File",
            str(AUTORUN / "invoke_autorun.ps1"),
            "-ProjectRoot",
            str(PROJECT_ROOT),
            "-ConfigPath",
            str(config),
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    after = sorted(path.name for path in log_dir.glob("*") if path.is_file()) if log_dir.exists() else []
    assert result.returncode == 0, stderr or stdout
    assert "[dry-run] No port, service, scheduler, log, state file, or Task Scheduler state was touched." in stdout
    assert before == after


def test_execute_mode_can_record_service_only_result_with_isolated_fake_health(tmp_path):
    project = tmp_path / "isolated-project"
    ops = project / "ops"
    local_autorun = ops / "autorun"
    local_autorun.mkdir(parents=True)
    (local_autorun / "invoke_autorun.ps1").write_text(
        read(AUTORUN / "invoke_autorun.ps1"), encoding="utf-8"
    )
    (ops / "health_check.ps1").write_text(
        "[CmdletBinding()] param([string]$ProjectRoot,[int]$Port,[switch]$Json)\n"
        "Write-Output '{\"ok\":true}'\nexit 0\n",
        encoding="utf-8",
    )
    (ops / "start_workbench.ps1").write_text(
        "[CmdletBinding()] param()\nthrow 'fake start must not be called'\n",
        encoding="utf-8",
    )
    config = local_autorun / "autorun.config.json"
    config.write_text(read(AUTORUN / "autorun.config.example.json"), encoding="utf-8")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-File",
            str(local_autorun / "invoke_autorun.ps1"),
            "-ProjectRoot",
            str(project),
            "-ConfigPath",
            str(config),
            "-Execute",
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    state = json.loads((ops / "logs" / "autorun" / "status.json").read_text(encoding="utf-8-sig"))
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert state["service_action"] == "already_healthy"
    assert state["scheduler_action"] == "disabled"
    assert state["outcome"] == "healthy_service_only"
    assert state["reason"] == "service_recovery_does_not_imply_collection_recovery"
