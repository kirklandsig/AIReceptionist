"""Detached background launcher for the receptionist agent.

Why this exists
---------------
On Windows, `Start-Process -RedirectStandardOutput` (PowerShell) sets up
the child via .NET's `Process.Start` with handle inheritance enabled.
The new process is a tracked child of the calling shell, and any tooling
that waits for the shell's process tree to drain (CI runners, terminal
multiplexers, AI dev harnesses) ends up waiting for the agent itself to
exit — which it never does, because the agent is a long-running daemon.

`Win32_Process.Create` (WMI) detaches the process but does not propagate
the calling shell's environment variables, which the agent needs for
LIVEKIT_*/OPENAI_*/SMTP_PASSWORD/etc.

`subprocess.Popen` with `creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`
gives us both: env-var inheritance AND a truly detached child that is
not a descendant of this launcher. On POSIX, `start_new_session=True`
plus `close_fds=True` achieves the same thing.

This launcher writes the agent's PID to disk and exits immediately. The
calling PowerShell/bash wrapper sees a clean EOF and returns control to
the operator in well under a second, regardless of whether the agent has
finished registering with LiveKit yet.

Usage
-----
    python scripts/_spawn_agent.py <business-slug>

Reads `.env.local` / `.env` from the repo root (so SMTP/LIVEKIT credentials
propagate to the child), kills any existing agent recorded in
`secrets/<slug>/runtime/agent.pid`, then spawns the new agent with
stdout/stderr redirected to `agent.log` / `agent.err` in the same dir.

Exit codes
----------
    0   spawned successfully
    64  invalid arguments / bad slug
    65  venv python not found
    66  spawn failed
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path


SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _load_dotenv(
    env_path: Path,
    env: dict[str, str],
    *,
    override: bool = False,
    protected_keys: set[str] | None = None,
) -> None:
    """Minimal .env loader. Supports `KEY=value` lines, ignores blanks and
    comments. Does NOT do quoting/escaping — keep .env files plain. The
    agent itself also calls `load_dotenv`, so this is belt-and-suspenders
    for env-vars that must be present before the agent's Python imports
    resolve (e.g. `PYTHONDONTWRITEBYTECODE`).
    """
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if override and (protected_keys is None or key not in protected_keys):
            env[key] = value
        else:
            env.setdefault(key, value)


def _kill_prior(pid_path: Path) -> None:
    """Stop any agent recorded in the pidfile. Best-effort; never raises."""
    if not pid_path.is_file():
        return
    try:
        old_pid = int(pid_path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(old_pid)],
                capture_output=True, check=False, timeout=5,
            )
        else:
            os.kill(old_pid, 15)
    except Exception:
        # Process already dead, permission denied, or taskkill itself
        # failed. Either way the new launch is the priority — don't
        # block on cleanup.
        pass


def _kill_multiprocessing_spawn_orphans() -> None:
    """Kill Python multiprocessing-spawn subprocesses whose parent is dead.

    LiveKit Agents in prod mode (`start`) spawns prewarmed runner
    subprocesses via Python's `multiprocessing` module. Those children
    have command lines like:

        C:\\Python314\\python.exe -c "from multiprocessing.spawn
        import spawn_main; spawn_main(parent_pid=N, pipe_handle=H)"

    They are NOT in the agent worker's process tree by Win32 metric, so
    `taskkill /F /T /PID <parent>` does not reach them. After a restart
    they become orphans whose `ParentProcessId` points to a dead PID,
    but they themselves keep running. Each one stays registered with
    LiveKit Cloud and is eligible to handle jobs — with stale code and
    a stale OpenAI Realtime tool registry. This was the cause of the
    multi-hour "Unknown function record_intake_answer" / hallucinated-
    parameter regression observed on 2026-05-22 after switching the
    local worker to prod mode.

    Safety: only kills processes whose parent is NOT alive. A
    multiprocessing child whose parent is still running is left alone
    (it's a healthy current-session worker). On a developer's laptop
    this is a small risk if another Python app is also using
    multiprocessing — accept that risk; production never runs both
    workloads on one box.
    """
    if sys.platform != "win32":
        return
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
        "| Where-Object { $_.CommandLine -like '*multiprocessing.spawn*' } "
        "| ForEach-Object { "
        "    $alive = $true; "
        "    try { Get-Process -Id $_.ParentProcessId -ErrorAction Stop | Out-Null } "
        "    catch { $alive = $false } "
        "    if (-not $alive) { $_.ProcessId } "
        "}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, check=False, text=True, timeout=10,
        )
    except Exception:
        return
    current_pid = os.getpid()
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid == current_pid:
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, check=False, timeout=5,
            )
        except Exception:
            pass


def _kill_orphan_agents(repo: Path) -> None:
    """Stop orphaned receptionist agent workers from this checkout on Windows.

    Matches any LiveKit subcommand (`dev`, `start`, etc.) so switching the
    launcher between dev and prod mode still cleanly purges leftover workers
    from the prior mode.
    """
    if sys.platform != "win32":
        return
    repo_text = str(repo)
    escaped_repo = repo_text.replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "$_.CommandLine -like '*-m receptionist.agent *' -and "
        f"$_.CommandLine -like '*{escaped_repo}*' "
        "} | Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, check=False, text=True, timeout=5,
        )
    except Exception:
        return
    current_pid = os.getpid()
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid == current_pid:
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, check=False, timeout=5,
            )
        except Exception:
            pass


def _write_generation_token(runtime: Path) -> str:
    token = uuid.uuid4().hex
    (runtime / "agent.generation").write_text(token, encoding="ascii")
    return token


def _add_generation_env(
    env: dict[str, str], generation_path: Path, generation_token: str
) -> None:
    env["RECEPTIONIST_AGENT_GENERATION"] = generation_token
    env["RECEPTIONIST_AGENT_GENERATION_FILE"] = str(generation_path)


def _write_restart_marker(log_path: Path, generation_token: str) -> None:
    with open(log_path, "a", encoding="utf-8") as log_f:
        log_f.write(f"agent restart generation={generation_token}\n")


def _spawn_detached(
    pyexe: Path,
    repo: Path,
    log_f,
    err_f,
    env: dict[str, str],
) -> subprocess.Popen:
    # `start` is LiveKit Agents' production-mode subcommand: one stable worker,
    # no file watching, no hot-reload-driven respawning. Dev mode's hot reload
    # was producing dozens of stale worker registrations on LiveKit Cloud and
    # a degraded OpenAI Realtime tool registry on long-lived workers. The local
    # launcher always uses `start`; developers who want hot-reload can run
    # `python -m receptionist.agent dev` directly without the launcher.
    args = [str(pyexe), "-m", "receptionist.agent", "start"]
    if sys.platform == "win32":
        # DETACHED_PROCESS = 0x00000008
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        # CREATE_NO_WINDOW = 0x08000000
        creationflags = 0x00000008 | 0x00000200 | 0x08000000
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=err_f,
            cwd=str(repo),
            env=env,
            creationflags=creationflags,
            close_fds=True,
        )
    return subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=log_f,
        stderr=err_f,
        cwd=str(repo),
        env=env,
        start_new_session=True,
        close_fds=True,
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1]:
        print("usage: spawn_agent <business-slug>", file=sys.stderr)
        return 64
    business = argv[1]
    if not SLUG_RE.match(business):
        print(
            f"invalid business slug {business!r} "
            "(use letters, digits, underscore, hyphen only)",
            file=sys.stderr,
        )
        return 64

    repo = Path(__file__).resolve().parent.parent
    runtime = repo / "secrets" / business / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)

    log_path = runtime / "agent.log"
    err_path = runtime / "agent.err"
    pid_path = runtime / "agent.pid"
    generation_path = runtime / "agent.generation"

    pyexe = repo / "venv" / "Scripts" / "python.exe"
    if not pyexe.is_file():
        # POSIX fallback
        alt = repo / "venv" / "bin" / "python"
        if alt.is_file():
            pyexe = alt
        else:
            print(f"venv python not found at {pyexe}", file=sys.stderr)
            return 65

    # Stop prior agent before spawning the new one
    _kill_prior(pid_path)
    _kill_orphan_agents(repo)
    # Also kill LiveKit prod-mode `multiprocessing.spawn` prewarmed-runner
    # orphans whose parent is now dead. See docstring on
    # `_kill_multiprocessing_spawn_orphans` for the root-cause discussion.
    _kill_multiprocessing_spawn_orphans()

    generation_token = _write_generation_token(runtime)
    _write_restart_marker(log_path, generation_token)

    # Build the child env: caller env + .env + intake-specific knobs
    env = os.environ.copy()
    caller_keys = set(env)
    _load_dotenv(repo / ".env", env)
    _load_dotenv(repo / ".env.local", env, override=True, protected_keys=caller_keys)
    env["RECEPTIONIST_CONFIG"] = business
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    _add_generation_env(env, generation_path, generation_token)

    # Open log/err in append mode so a restart preserves prior session
    # output. The child gets its own duplicates of the handles via Popen;
    # we close ours immediately after spawn so this launcher doesn't keep
    # the files alive.
    log_f = open(log_path, "ab", buffering=0)
    err_f = open(err_path, "ab", buffering=0)
    try:
        proc = _spawn_detached(pyexe, repo, log_f, err_f, env)
    except OSError as e:
        print(f"spawn failed: {e}", file=sys.stderr)
        return 66
    finally:
        log_f.close()
        err_f.close()

    pid_path.write_text(str(proc.pid), encoding="ascii")
    print(f"agent restarted: business={business} PID={proc.pid}")
    print(f"  log:    {log_path}")
    print(f"  status: powershell -File scripts/agent-status.ps1 -Business {business}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
