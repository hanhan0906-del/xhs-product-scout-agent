[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8793,
    [int]$TimeoutSeconds = 5,
    [switch]$Json
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

function Test-HttpEndpoint {
    param(
        [string]$Url,
        [int]$TimeoutSeconds
    )
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
        return [pscustomobject]@{
            url = $Url
            ok = ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
            status_code = [int]$response.StatusCode
            error = $null
        }
    }
    catch {
        return [pscustomobject]@{
            url = $Url
            ok = $false
            status_code = $null
            error = $_.Exception.Message
        }
    }
}

$ResolvedRoot = Resolve-ProjectRoot -Path $ProjectRoot
$urls = @(
    "http://${HostAddress}:${Port}/api/status",
    "http://${HostAddress}:${Port}/api/monitor/status",
    "http://${HostAddress}:${Port}/export/candidates.csv"
)

if ($WhatIfPreference) {
    Write-Host "[what-if] Would inspect Get-NetTCPConnection on port $Port and request:"
    $urls | ForEach-Object { Write-Host "[what-if] $_" }
    exit 0
}

$owners = @(Get-PortOwnerProcess -ExpectedPort $Port -ResolvedRoot $ResolvedRoot)
$ownerSummary = @($owners | ForEach-Object {
    [pscustomobject]@{
        process_id = $_.ProcessId
        is_project_owned = $_.IsProjectOwned
        command_line = $_.CommandLine
    }
})
$endpointResults = @($urls | ForEach-Object { Test-HttpEndpoint -Url $_ -TimeoutSeconds $TimeoutSeconds })
$ok = (
    $owners.Count -gt 0 -and
    @($owners | Where-Object { $_.IsProjectOwned }).Count -gt 0 -and
    @($owners | Where-Object { -not $_.IsProjectOwned }).Count -eq 0 -and
    @($endpointResults | Where-Object { -not $_.ok }).Count -eq 0
)
$result = [pscustomobject]@{
    ok = $ok
    project_root = $ResolvedRoot
    port = $Port
    ignored_port = 8765
    owners = $ownerSummary
    endpoints = $endpointResults
}

if ($Json) {
    $result | ConvertTo-Json -Depth 6
}
else {
    if ($ok) {
        Write-Host "OK: project-owned workbench is healthy on http://${HostAddress}:${Port}"
    }
    else {
        Write-Host "FAIL: workbench health check failed for http://${HostAddress}:${Port}"
        $result | ConvertTo-Json -Depth 6
    }
}

if (-not $ok) {
    exit 1
}
