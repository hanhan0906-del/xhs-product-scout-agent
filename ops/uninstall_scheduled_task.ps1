[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = "XhsProductScoutWorkbench8793",
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
# Installed project: C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent
Write-Host "Rollback target: scheduled task '$TaskName' only."
Write-Host "Scope: no service, scheduler, database, device, port 8793, or port 8765 is stopped or changed."
if (-not $Execute) {
    Write-Host "[dry-run] No ScheduledTasks cmdlet was called and no scheduled task was removed."
    Write-Host "[dry-run] Re-run with -Execute to unregister only this task. You may also pass -WhatIf."
    exit 0
}
if ($PSCmdlet.ShouldProcess($TaskName, "Unregister-ScheduledTask")) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "Scheduled task is already absent: $TaskName"
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered scheduled task: $TaskName"
}
