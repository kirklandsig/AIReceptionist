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
#     3 — process running but worker registration not yet visible in log
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

if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Host "no agent.pid for business=$Business -- agent has never been started"
    exit 1
}

$agentPid = [int](Get-Content -LiteralPath $pidPath)
$proc = Get-Process -Id $agentPid -ErrorAction SilentlyContinue

if (-not $proc) {
    Write-Host "business=$Business PID $agentPid recorded but NOT running"
    exit 2
}

Write-Host "business=${Business} PID ${agentPid}: alive, started $($proc.StartTime)"

# Most recent worker-registration line in the log
if (Test-Path -LiteralPath $logPath) {
    $reg = Select-String -LiteralPath $logPath -Pattern "registered worker" |
           Select-Object -Last 1
    if ($reg) {
        Write-Host "last registration: $($reg.Line.Trim())"
        exit 0
    } else {
        Write-Host "process up but no 'registered worker' line yet -- still starting"
        exit 3
    }
} else {
    Write-Host "process up but no log file yet"
    exit 3
}
