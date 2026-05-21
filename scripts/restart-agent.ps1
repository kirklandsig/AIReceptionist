# scripts/restart-agent.ps1
#
# One-shot restart helper for the receptionist agent. Returns immediately
# after spawning the new process; does NOT block on worker registration.
# Use `scripts/agent-status.ps1 -Business <slug>` to check readiness.
#
# Usage (from repo root):
#     powershell -ExecutionPolicy Bypass -File scripts/restart-agent.ps1 -Business acme-dental
#     # or set $env:RECEPTIONIST_CONFIG and omit -Business
#
# Delegates process management to scripts\_spawn_agent.py. Keeping the
# detachment logic in Python avoids PowerShell handle-inheritance hangs
# and still returns immediately after the background agent is spawned.

param(
    [string]$Business = $env:RECEPTIONIST_CONFIG
)

$ErrorActionPreference = 'Stop'

if (-not $Business) {
    Write-Host "ERROR: -Business <slug> required (or set RECEPTIONIST_CONFIG)" -ForegroundColor Red
    exit 64
}

if ($Business -notmatch '^[a-zA-Z0-9_-]+$') {
    Write-Host "ERROR: invalid business slug '$Business' (use letters, numbers, underscore, hyphen only)" -ForegroundColor Red
    exit 64
}

$repo = (Resolve-Path "$PSScriptRoot/..").Path
$pyExe = Join-Path $repo "venv\Scripts\python.exe"
$launcher = Join-Path $repo "scripts\_spawn_agent.py"

& $pyExe $launcher $Business
exit $LASTEXITCODE
