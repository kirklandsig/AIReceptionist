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

Reads `.env` from the repo root (so SMTP/LIVEKIT credentials propagate to
the child), kills any existing agent recorded in
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
from pathlib import Path


SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _load_dotenv(env_path: Path, env: dict[str, str]) -> None:
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
        # Don't override values already set by the caller
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
                ["taskkill", "/F", "/PID", str(old_pid)],
                capture_output=True, check=False, timeout=5,
            )
        else:
            os.kill(old_pid, 15)
    except Exception:
        # Process already dead, permission denied, or taskkill itself
        # failed. Either way the new launch is the priority — don't
        # block on cleanup.
        pass


def _spawn_detached(
    pyexe: Path,
    repo: Path,
    log_f,
    err_f,
    env: dict[str, str],
) -> subprocess.Popen:
    args = [str(pyexe), "-m", "receptionist.agent", "dev"]
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

    # Build the child env: caller env + .env + intake-specific knobs
    env = os.environ.copy()
    _load_dotenv(repo / ".env", env)
    env["RECEPTIONIST_CONFIG"] = business
    env["PYTHONDONTWRITEBYTECODE"] = "1"

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
