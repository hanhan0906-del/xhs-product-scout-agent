[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$IncludeTaskScheduler,
    [string]$TaskName = "XhsProductScoutWorkbench8793"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ResolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$StatePath = Join-Path $ResolvedRoot "ops\logs\autorun\status.json"
$result = [ordered]@{
    project_root = $ResolvedRoot
    port = 8793
    ignored_port = 8765
    last_run = $null
    task_scheduler = "not_queried"
}
if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
    $result.last_run = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
}
if ($IncludeTaskScheduler) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $result.task_scheduler = $(if ($null -eq $task) { "not_installed" } else { $task.State.ToString() })
}
[pscustomobject]$result | ConvertTo-Json -Depth 8
