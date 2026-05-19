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
# The script:
#   1. Stops any prior agent process recorded in the pidfile.
#   2. Loads `.env` from the repo root into the spawned-process environment.
#   3. Sets `PYTHONDONTWRITEBYTECODE=1` so the spawned interpreter never
#      writes `.pyc` files. This eliminates the stale-bytecode failure mode
#      where an old `__pycache__/foo.cpython-3XX.pyc` shadowed a newer
#      `foo.py` and the running agent kept serving pre-edit code. The
#      cost is ~100-300ms of extra compile time on first import; well
#      worth the reliability win.
#   4. Spawns `python -m receptionist.agent dev` detached with stdout/stderr
#      redirected to `secrets/<business>/runtime/agent.{log,err}` and the
#      PID written to `secrets/<business>/runtime/agent.pid`.

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
$runtimeDir = Join-Path $repo "secrets\$Business\runtime"
$pidPath = Join-Path $runtimeDir "agent.pid"
$logPath = Join-Path $runtimeDir "agent.log"
$errPath = Join-Path $runtimeDir "agent.err"
$pyExe   = Join-Path $repo "venv\Scripts\python.exe"
$envFile = Join-Path $repo ".env"

if (-not (Test-Path -LiteralPath $pyExe)) {
    Write-Host "ERROR: venv python not found at $pyExe" -ForegroundColor Red
    exit 65
}

# --- 1. Kill any prior agent process (idempotent) ---
if (Test-Path -LiteralPath $pidPath) {
    $oldPid = [int](Get-Content -LiteralPath $pidPath)
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
}

# --- 2. Ensure runtime dir exists ---
if (-not (Test-Path -LiteralPath $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
}

# --- 3. Load .env into the spawned-process environment ---
if (Test-Path -LiteralPath $envFile) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        if ($_ -match "^([A-Z_]+)=(.*)$") {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
        }
    }
}
[Environment]::SetEnvironmentVariable("RECEPTIONIST_CONFIG", $Business, "Process")
# Tell Python not to write .pyc files at all. Prevents the entire class
# of "stale bytecode shadows newer source" bugs by eliminating the cache.
[Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")

# --- 4. Start agent fully detached and return immediately ---
$proc = Start-Process -FilePath $pyExe `
    -ArgumentList "-m","receptionist.agent","dev" `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError $errPath `
    -WorkingDirectory $repo `
    -PassThru -WindowStyle Hidden

$proc.Id | Out-File -Encoding ascii -LiteralPath $pidPath

Write-Host "agent restarted: business=$Business PID=$($proc.Id)"
Write-Host "  log:    $logPath"
Write-Host "  status: powershell -File scripts/agent-status.ps1 -Business $Business"
