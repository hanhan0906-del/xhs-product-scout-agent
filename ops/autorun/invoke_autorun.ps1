[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = "",
    [string]$ConfigPath = "",
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ResolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
if (-not (Test-Path -LiteralPath $ResolvedRoot -PathType Container)) {
    throw "Project root does not exist: $ResolvedRoot"
}
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot "autorun.config.json"
}
$ResolvedConfig = [System.IO.Path]::GetFullPath($ConfigPath)
$StartScript = Join-Path $ResolvedRoot "ops\start_workbench.ps1"
$HealthScript = Join-Path $ResolvedRoot "ops\health_check.ps1"
$LogDir = Join-Path $ResolvedRoot "ops\logs\autorun"
$LogPath = Join-Path $LogDir "autorun.jsonl"
$StatePath = Join-Path $LogDir "status.json"
$PowerShellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

foreach ($required in @($StartScript, $HealthScript)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing required script: $required"
    }
}

function Get-Config {
    $default = [pscustomobject]@{
        schema_version = 1
        service_recovery_enabled = $true
        scheduler_recovery_enabled = $false
        scheduler_resume_requires_persisted_running_intent = $true
    }
    if (-not (Test-Path -LiteralPath $ResolvedConfig -PathType Leaf)) {
        return $default
    }
    $loaded = Get-Content -LiteralPath $ResolvedConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($name in @(
        "schema_version",
        "service_recovery_enabled",
        "scheduler_recovery_enabled",
        "scheduler_resume_requires_persisted_running_intent"
    )) {
        if ($null -eq $loaded.PSObject.Properties[$name]) {
            throw "Autorun config is missing required property: $name"
        }
    }
    if ([int]$loaded.schema_version -ne 1) {
        throw "Unsupported autorun config schema_version: $($loaded.schema_version)"
    }
    return $loaded
}

function Invoke-PowerShellFile {
    param([string]$FilePath, [string[]]$Arguments)
    $allArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $FilePath) + $Arguments
    $output = & $PowerShellExe @allArgs 2>&1 | Out-String
    return [pscustomobject]@{ exit_code = $LASTEXITCODE; output = $output.Trim() }
}

function Write-RunState {
    param([hashtable]$Record)
    $Record.timestamp = (Get-Date).ToUniversalTime().ToString("o")
    $object = [pscustomobject]$Record
    $json = $object | ConvertTo-Json -Depth 8 -Compress
    Add-Content -LiteralPath $LogPath -Value $json -Encoding UTF8
    $object | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatePath -Encoding UTF8
}

$config = Get-Config
$summary = [ordered]@{
    project_root = $ResolvedRoot
    port = 8793
    ignored_port = 8765
    mode = $(if ($Execute) { "execute" } else { "dry-run" })
    service_recovery_enabled = [bool]$config.service_recovery_enabled
    scheduler_recovery_enabled = [bool]$config.scheduler_recovery_enabled
    service_action = "none"
    scheduler_action = "none"
    outcome = "planned"
    reason = $null
}

if (-not $Execute) {
    Write-Host "[dry-run] Would run the existing health_check.ps1 against project-owned port 8793."
    if ([bool]$config.service_recovery_enabled) {
        Write-Host "[dry-run] If unhealthy, would call start_workbench.ps1 -Port 8793 -Execute."
    }
    if ([bool]$config.scheduler_recovery_enabled) {
        Write-Host "[dry-run] Scheduler recovery is opted in, but would still require healthy service, no active risk, and persisted desired_state=running."
    }
    else {
        Write-Host "[dry-run] Scheduler recovery is disabled; service recovery does not resume collection."
    }
    Write-Host "[dry-run] No port, service, scheduler, log, state file, or Task Scheduler state was touched."
    [pscustomobject]$summary | ConvertTo-Json -Depth 6
    exit 0
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
try {
    $health = Invoke-PowerShellFile -FilePath $HealthScript -Arguments @("-ProjectRoot", $ResolvedRoot, "-Port", "8793", "-Json")
    if ($health.exit_code -ne 0) {
        if (-not [bool]$config.service_recovery_enabled) {
            $summary.outcome = "blocked"
            $summary.reason = "service_unhealthy_and_recovery_disabled"
            Write-RunState -Record $summary
            exit 2
        }
        if ($PSCmdlet.ShouldProcess("project-owned port 8793", "recover workbench service")) {
            $started = Invoke-PowerShellFile -FilePath $StartScript -Arguments @("-ProjectRoot", $ResolvedRoot, "-Port", "8793", "-Execute")
            if ($started.exit_code -ne 0) {
                throw "start_workbench.ps1 failed: $($started.output)"
            }
            $summary.service_action = "recovered"
        }
        $health = Invoke-PowerShellFile -FilePath $HealthScript -Arguments @("-ProjectRoot", $ResolvedRoot, "-Port", "8793", "-Json")
        if ($health.exit_code -ne 0) {
            throw "health_check.ps1 remained unhealthy after recovery: $($health.output)"
        }
    }
    else {
        $summary.service_action = "already_healthy"
    }

    if (-not [bool]$config.scheduler_recovery_enabled) {
        $summary.scheduler_action = "disabled"
        $summary.outcome = "healthy_service_only"
        $summary.reason = "service_recovery_does_not_imply_collection_recovery"
        Write-RunState -Record $summary
        exit 0
    }

    # This is a separate fail-closed gate. It never calls risk-resume and never clears
    # CAPTCHA, login, risk-control, identity, database-lock, or other stop evidence.
    $monitorUrl = "http://127.0.0.1:8793/api/monitor/status"
    $statusUrl = "http://127.0.0.1:8793/api/status"
    $monitorPayload = Invoke-RestMethod -Uri $monitorUrl -Method Get -TimeoutSec 5
    $statusPayload = Invoke-RestMethod -Uri $statusUrl -Method Get -TimeoutSec 5
    if ($null -eq $monitorPayload.state -or $null -eq $statusPayload.monitor -or $null -eq $statusPayload.scheduler) {
        throw "Existing health/safety status payload is incomplete; refusing scheduler recovery."
    }
    $state = $monitorPayload.state
    if (-not [string]::IsNullOrWhiteSpace([string]$state.risk_stop_reason)) {
        $summary.scheduler_action = "blocked"
        $summary.outcome = "blocked"
        $summary.reason = "active_risk_stop"
        Write-RunState -Record $summary
        exit 3
    }
    if ([bool]$config.scheduler_resume_requires_persisted_running_intent -and [string]$state.desired_state -ne "running") {
        $summary.scheduler_action = "kept_paused"
        $summary.outcome = "healthy_service_only"
        $summary.reason = "no_persisted_running_intent"
        Write-RunState -Record $summary
        exit 0
    }
    if ([bool]$state.scheduler_running -or [bool]$statusPayload.scheduler.thread_alive) {
        $summary.scheduler_action = "already_running"
        $summary.outcome = "healthy"
        Write-RunState -Record $summary
        exit 0
    }

    if ($PSCmdlet.ShouldProcess("ordinary paused scheduler with persisted running intent", "POST /api/monitor/resume")) {
        $resume = Invoke-RestMethod -Uri "http://127.0.0.1:8793/api/monitor/resume" -Method Post -TimeoutSec 10
        if ([string]$resume.desired_state -ne "running") {
            throw "Ordinary resume endpoint did not return desired_state=running."
        }
        $summary.scheduler_action = "resumed"
        $summary.outcome = "healthy"
        Write-RunState -Record $summary
    }
}
catch {
    $summary.outcome = "error"
    $summary.reason = $_.Exception.Message
    Write-RunState -Record $summary
    Write-Error $_
    exit 1
}
