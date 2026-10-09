[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8793,
    [switch]$Execute,
    [switch]$OpenBrowser,
    [int]$MaxLogFiles = 10,
    [int]$MaxLogMegabytes = 10
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

function Invoke-LogRotation {
    param(
        [string]$LogDir,
        [int]$KeepFiles,
        [int]$MaxMegabytes,
        [switch]$ActuallyExecute
    )
    $maxBytes = [int64]$MaxMegabytes * 1MB
    if (-not $ActuallyExecute) {
        Write-Host "[dry-run] Ensure log directory exists: $LogDir"
        Write-Host "[dry-run] Rotate *.log files larger than ${MaxMegabytes}MB and keep latest $KeepFiles files"
        return
    }
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Get-ChildItem -LiteralPath $LogDir -Filter "*.log" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Length -gt $maxBytes } |
        ForEach-Object {
            $archiveName = "{0}.{1:yyyyMMddHHmmss}.old" -f $_.Name, (Get-Date)
            Rename-Item -LiteralPath $_.FullName -NewName $archiveName
        }
    Get-ChildItem -LiteralPath $LogDir -Filter "*.log*" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $KeepFiles |
        Remove-Item -Force
}

$ResolvedRoot = Resolve-ProjectRoot -Path $ProjectRoot
$LogDir = Join-Path $ResolvedRoot "ops\logs"
$StdoutLog = Join-Path $LogDir "workbench.stdout.log"
$StderrLog = Join-Path $LogDir "workbench.stderr.log"
$PidFile = Join-Path $LogDir "workbench.pid"
$HealthUrl = "http://${HostAddress}:${Port}/api/status"

Write-Host "Project: $ResolvedRoot"
Write-Host "Target:  http://${HostAddress}:${Port}"

$owners = @(Get-PortOwnerProcess -ExpectedPort $Port -ResolvedRoot $ResolvedRoot)
$projectOwners = @($owners | Where-Object { $_.IsProjectOwned })
$foreignOwners = @($owners | Where-Object { -not $_.IsProjectOwned })

if ($projectOwners.Count -gt 0) {
    Write-Host "Workbench already appears to be running on port $Port with PID(s): $($projectOwners.ProcessId -join ', ')"
    exit 0
}
if ($foreignOwners.Count -gt 0) {
    $ids = $foreignOwners.ProcessId -join ", "
    throw "Port $Port is already used by non-project process(es): $ids. Refusing to start or stop anything."
}

Invoke-LogRotation -LogDir $LogDir -KeepFiles $MaxLogFiles -MaxMegabytes $MaxLogMegabytes -ActuallyExecute:$Execute

$python = Join-Path $ResolvedRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = "python"
}
$arguments = @(
    "-m", "xhs_scout.cli", "serve",
    "--host", $HostAddress,
    "--port", $Port.ToString(),
    "--project-root=`"$ResolvedRoot`""
)

if (-not $Execute) {
    Write-Host "[dry-run] Would start: $python $($arguments -join ' ')"
    Write-Host "[dry-run] Working directory: $ResolvedRoot"
    Write-Host "[dry-run] Logs: $StdoutLog and $StderrLog"
    Write-Host "[dry-run] Re-run with -Execute to start the workbench. You may also pass -WhatIf."
    exit 0
}

if ($PSCmdlet.ShouldProcess("port $Port in $ResolvedRoot", "start project workbench process")) {
    $process = Start-Process -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $ResolvedRoot `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $PidFile -Encoding UTF8 -Value $process.Id
    $healthy = $false
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
            $healthy = $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
        }
        catch {
            $healthy = $false
        }
    } while (-not $healthy -and -not $process.HasExited -and (Get-Date) -lt $deadline)
    if (-not $healthy) {
        throw "Workbench PID $($process.Id) did not become healthy at $HealthUrl."
    }
    Write-Host "Started healthy workbench PID $($process.Id). Health URL: $HealthUrl"
}

if ($OpenBrowser -and $PSCmdlet.ShouldProcess($HealthUrl, "open browser")) {
    Start-Process "http://${HostAddress}:${Port}/"
}
