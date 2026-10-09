[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = "",
    [int]$Port = 8793,
    [switch]$Execute,
    [switch]$Force
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

function Test-ProjectOwnedCommandLine {
    param(
        [AllowNull()][string]$CommandLine,
        [string]$ResolvedRoot,
        [int]$ExpectedPort
    )
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    $normalizedCommand = $CommandLine.ToLowerInvariant()
    $normalizedRoot = $ResolvedRoot.ToLowerInvariant()
    $rootMarkers = @(
        "--project-root=`"$normalizedRoot`"",
        "--project-root `"$normalizedRoot`""
    )
    return (
        @($rootMarkers | Where-Object { $normalizedCommand.Contains($_) }).Count -gt 0 -and
        (
            $normalizedCommand.Contains("xhs_scout.cli") -or
            $normalizedCommand.Contains("xhs-scout")
        ) -and
        $normalizedCommand.Contains("serve") -and
        $normalizedCommand.Contains($ExpectedPort.ToString())
    )
}

function Get-PortOwnerProcess {
    param(
        [int]$ExpectedPort,
        [string]$ResolvedRoot
    )
    $connections = @(Get-NetTCPConnection -LocalPort $ExpectedPort -State Listen -ErrorAction SilentlyContinue)
    foreach ($connection in $connections) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
        if ($null -ne $proc) {
            [pscustomobject]@{
                ProcessId = [int]$proc.ProcessId
                CommandLine = [string]$proc.CommandLine
                IsProjectOwned = Test-ProjectOwnedCommandLine -CommandLine $proc.CommandLine -ResolvedRoot $ResolvedRoot -ExpectedPort $ExpectedPort
            }
        }
    }
}

$ResolvedRoot = Resolve-ProjectRoot -Path $ProjectRoot
Write-Host "Project: $ResolvedRoot"
Write-Host "Stop target: only project-owned listener on port $Port"
Write-Host "Non-target port 8765 is intentionally ignored."

if ($Port -ne 8793) {
    throw "This script is scoped to this project's workbench port 8793. Refusing requested port $Port."
}

$owners = @(Get-PortOwnerProcess -ExpectedPort $Port -ResolvedRoot $ResolvedRoot)
if ($owners.Count -eq 0) {
    Write-Host "No listener found on port $Port."
    exit 0
}

$foreignOwners = @($owners | Where-Object { -not $_.IsProjectOwned })
if ($foreignOwners.Count -gt 0) {
    $ids = $foreignOwners.ProcessId -join ", "
    throw "Port $Port has non-project owner process(es) $ids. Refusing to stop; no process was killed."
}

$projectOwners = @($owners | Where-Object { $_.IsProjectOwned })
foreach ($owner in $projectOwners) {
    if (-not $Execute) {
        Write-Host "[dry-run] Would stop project-owned PID $($owner.ProcessId) on port $Port"
        Write-Host "[dry-run] CommandLine: $($owner.CommandLine)"
        continue
    }
    if ($PSCmdlet.ShouldProcess("PID $($owner.ProcessId) on port $Port", "Stop-Process")) {
        Stop-Process -Id $owner.ProcessId -Force:$Force
        Write-Host "Stopped project-owned workbench PID $($owner.ProcessId)."
    }
}

if (-not $Execute) {
    Write-Host "[dry-run] Re-run with -Execute to stop only the verified project process. You may also pass -WhatIf."
}
