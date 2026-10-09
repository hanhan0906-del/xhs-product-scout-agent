[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = "",
    [string]$TaskName = "XhsProductScoutWorkbench8793",
    [int]$RepeatMinutes = 15,
    [string]$ConfigPath = "",
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
# Installed project: C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

function Resolve-ProjectRoot {
    param([string]$Path)
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "Project root does not exist: $resolved"
    }
    return $resolved.TrimEnd("\")
}

if ($RepeatMinutes -lt 5) {
    throw "RepeatMinutes must be at least 5."
}

$ResolvedRoot = Resolve-ProjectRoot -Path $ProjectRoot
$AutorunScript = Join-Path $ResolvedRoot "ops\autorun\invoke_autorun.ps1"
$StartScript = Join-Path $ResolvedRoot "ops\start_workbench.ps1"
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $ResolvedRoot "ops\autorun\autorun.config.json"
}
$ResolvedConfig = [System.IO.Path]::GetFullPath($ConfigPath)

if (-not (Test-Path -LiteralPath $AutorunScript -PathType Leaf)) {
    throw "Missing autorun entrypoint: $AutorunScript"
}
if (-not (Test-Path -LiteralPath $StartScript -PathType Leaf)) {
    throw "Missing service recovery target: $StartScript"
}

$PowerShellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$ActionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$AutorunScript`" -ProjectRoot `"$ResolvedRoot`" -ConfigPath `"$ResolvedConfig`" -Execute"

Write-Host "Task name: $TaskName"
Write-Host "Project:   $ResolvedRoot"
Write-Host "Action:    $PowerShellExe $ActionArgs"
Write-Host "Schedule:  at logon and every $RepeatMinutes minutes"
Write-Host "Scope:     recover only this project's 8793 workbench; port 8765 is not used."
Write-Host "Service:   autorun delegates recovery to start_workbench.ps1 after health failure."
Write-Host "Scheduler: independent opt-in config; default disabled; active risk is never cleared."

if (-not $Execute) {
    Write-Host "[dry-run] No ScheduledTasks cmdlet was called. No scheduled task was registered."
    Write-Host "[dry-run] Re-run with -Execute to register or update the idempotent definition. You may also pass -WhatIf."
    exit 0
}

if ($PSCmdlet.ShouldProcess($TaskName, "register or replace this project's scheduled task definition")) {
    $Action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $ActionArgs -WorkingDirectory $ResolvedRoot
    $AtLogOn = New-ScheduledTaskTrigger -AtLogOn
    $Repeating = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5) `
        -RepetitionInterval (New-TimeSpan -Minutes $RepeatMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger @($AtLogOn, $Repeating) `
        -Settings $Settings `
        -Description "Self-recovering local XHS product scout workbench on 127.0.0.1:8793; scheduler recovery is separately gated" `
        -Force | Out-Null
    Write-Host "Registered or updated scheduled task: $TaskName"
}
