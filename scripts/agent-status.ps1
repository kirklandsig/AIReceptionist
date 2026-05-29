# scripts/agent-status.ps1
#
# Fast read-only status check for the receptionist agent. Reports whether
# the recorded PID is alive AND whether LiveKit worker registration
# completed. Never blocks; safe to call repeatedly. Pair with
# scripts/restart-agent.ps1.
#
# Usage:
#     powershell -ExecutionPolicy Bypass -File scripts/agent-status.ps1 -Business acme-dental
#     # or set $env:RECEPTIONIST_CONFIG and omit -Business
#
# Exit codes:
#     0 — agent alive and registered with LiveKit
#     1 — no pidfile (agent has never been started for this business)
#     2 — pidfile present but process not running
#     3 — process running but current generation is not registered yet
#     4 — current generation marker is missing from log
#     5 — generation file is missing or empty
#     6 — unexpected orphan agent process exists for this checkout
#    64 — usage error (no business slug provided)

param(
    [string]$Business = $env:RECEPTIONIST_CONFIG
)

$ErrorActionPreference = 'Continue'

if (-not $Business) {
    Write-Host "ERROR: -Business <slug> required (or set RECEPTIONIST_CONFIG)" -ForegroundColor Red
    exit 64
}

if ($Business -notmatch '^[a-zA-Z0-9_-]+$') {
    Write-Host "ERROR: invalid business slug '$Business' (use letters, numbers, underscore, hyphen only)" -ForegroundColor Red
    exit 64
}

$repo = (Resolve-Path "$PSScriptRoot/..").Path
$runtimeDir = Join-Path $repo "secrets\$Business\runtime"
$pidPath = Join-Path $runtimeDir "agent.pid"
$logPath = Join-Path $runtimeDir "agent.log"
$generationPath = Join-Path $runtimeDir "agent.generation"

if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Host "no agent.pid for business=$Business -- agent has never been started"
    exit 1
}

$agentPid = [int](Get-Content -LiteralPath $pidPath)
$proc = Get-Process -Id $agentPid -ErrorAction SilentlyContinue
$repoNeedle = $repo.Replace('\', '/').TrimEnd('/').ToLowerInvariant()
$allProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
$processMap = @{}
foreach ($candidate in $allProcesses) {
    $processMap[[int]$candidate.ProcessId] = $candidate
}

function Test-IsAgentCommandLine {
    param([string]$CommandLine)

    $normalizedCommandLine = $CommandLine.Replace('\', '/').ToLowerInvariant()
    if ($normalizedCommandLine -ne $repoNeedle -and $normalizedCommandLine -notlike "*$repoNeedle/*") {
        return $false
    }
    # Match any LiveKit subcommand (dev, start, etc.) rather than just `dev`,
    # so the status check works regardless of which mode the launcher chose.
    if ($normalizedCommandLine -notlike "*receptionist.agent *") {
        return $false
    }
    return $true
}

if (-not $proc) {
    Write-Host "business=$Business PID $agentPid recorded but NOT running"
    exit 2
}

$pidProcess = $processMap[$agentPid]
if (-not $pidProcess) {
    Write-Host "business=$Business PID $agentPid is running but could not be verified as this checkout's receptionist.agent dev"
    exit 2
}

$pidProcessName = [string]$pidProcess.Name
$pidProcessCommandLine = [string]$pidProcess.CommandLine
if (($pidProcessName -ne 'python.exe' -and $pidProcessName -ne 'pythonw.exe') -or -not (Test-IsAgentCommandLine -CommandLine $pidProcessCommandLine)) {
    Write-Host "business=$Business PID $agentPid is not a receptionist agent for this checkout (name=$pidProcessName; expected receptionist.agent dev)"
    exit 2
}

Write-Host "business=${Business} PID ${agentPid}: alive, started $($proc.StartTime)"

if (-not (Test-Path -LiteralPath $generationPath)) {
    Write-Host "process up but generation is missing: no agent.generation"
    exit 5
}

$generation = (Get-Content -LiteralPath $generationPath -Raw).Trim()
if (-not $generation) {
    Write-Host "process up but generation is missing: agent.generation is empty"
    exit 5
}

if (-not (Test-Path -LiteralPath $logPath)) {
    Write-Host "process up but no log file yet"
    exit 3
}

$restartPattern = "agent restart generation=$generation"
$restartMarker = Select-String -LiteralPath $logPath -SimpleMatch -Pattern $restartPattern |
                 Select-Object -Last 1
if (-not $restartMarker) {
    Write-Host "process up but current generation marker is missing from log: $generation"
    exit 4
}

$registrationLine = Select-String -LiteralPath $logPath -SimpleMatch -Pattern "registered worker" |
                    Where-Object { $_.LineNumber -gt $restartMarker.LineNumber } |
                    Select-Object -Last 1
if (-not $registrationLine) {
    Write-Host "process up but no 'registered worker' line after current generation marker -- still starting"
    exit 3
}

if ($registrationLine.LineNumber -le $restartMarker.LineNumber) {
    Write-Host "process up but latest registration predates current generation marker -- still starting"
    exit 3
}

$processes = $allProcesses | Where-Object { $_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' }

function Test-IsDescendantOfAgentPid {
    param(
        [int]$ChildPid,
        [int]$RootPid,
        [hashtable]$ProcessMap
    )

    $seen = @{}
    $cursor = $ChildPid
    while ($ProcessMap.ContainsKey($cursor)) {
        if ($seen.ContainsKey($cursor)) {
            return $false
        }
        $seen[$cursor] = $true
        $parent = [int]$ProcessMap[$cursor].ParentProcessId
        if ($parent -eq $RootPid) {
            return $true
        }
        if ($parent -eq 0 -or $parent -eq $cursor) {
            return $false
        }
        $cursor = $parent
    }
    return $false
}

$orphanPids = @()
foreach ($candidate in $processes) {
    $candidatePid = [int]$candidate.ProcessId
    $commandLine = [string]$candidate.CommandLine
    if ($candidatePid -eq $agentPid) {
        continue
    }
    if (Test-IsDescendantOfAgentPid -ChildPid $candidatePid -RootPid $agentPid -ProcessMap $processMap) {
        continue
    }
    if (-not (Test-IsAgentCommandLine -CommandLine $commandLine)) {
        continue
    }
    $orphanPids += $candidatePid
}

if ($orphanPids.Count -gt 0) {
    Write-Host "unexpected orphan receptionist agent process(es): $($orphanPids -join ', ')"
    exit 6
}

Write-Host "last registration: $($registrationLine.Line.Trim())"
exit 0
