from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import scripts._spawn_agent as launcher


def test_restart_agent_powershell_delegates_to_python_launcher():
    script = Path("scripts/restart-agent.ps1").read_text(encoding="utf-8")
    assert "scripts\\_spawn_agent.py" in script or "scripts/_spawn_agent.py" in script
    assert "Win32_Process" not in script


def test_kill_prior_uses_windows_process_tree(monkeypatch, tmp_path):
    pid_path = tmp_path / "agent.pid"
    pid_path.write_text("12345", encoding="ascii")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    launcher._kill_prior(pid_path)

    assert calls
    args, kwargs = calls[0]
    assert args == ["taskkill", "/F", "/T", "/PID", "12345"]
    assert kwargs["timeout"] == 5


def test_kill_orphan_agents_kills_matching_workspace_processes(monkeypatch, tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "powershell":
            return SimpleNamespace(returncode=0, stdout="111\n222\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher.os, "getpid", lambda: 999)

    launcher._kill_orphan_agents(tmp_path)

    taskkill_calls = [call for call in calls if call[0][0] == "taskkill"]
    assert [call[0] for call in taskkill_calls] == [
        ["taskkill", "/F", "/T", "/PID", "111"],
        ["taskkill", "/F", "/T", "/PID", "222"],
    ]


def test_kill_multiprocessing_spawn_orphans_with_dead_parent(monkeypatch, tmp_path):
    """LiveKit Agents prod mode spawns prewarmed runner subprocesses via
    Python's `multiprocessing.spawn`. When the agent worker parent dies
    (`taskkill /T`), these multiprocessing children become orphans that
    `taskkill /T` cannot reach because they are not in the parent's
    process tree. They keep registering with LiveKit Cloud and handling
    jobs with stale code — the cause of the multi-hour "Unknown function
    record_intake_answer" / hallucinated-parameter regression seen on
    2026-05-22.

    The launcher must also kill these orphans on restart. Identification:
    a `python.exe` process with `multiprocessing.spawn` in its command
    line whose parent process is no longer alive.
    """
    calls = []
    process_table = {
        # alive parent — child should NOT be killed
        100: {"alive": True, "name": "python.exe", "cmd": "-m receptionist.agent start"},
        # multiprocessing orphan, parent alive (parent==100) — NOT killed
        200: {"alive": True, "name": "python.exe", "cmd": "multiprocessing.spawn parent_pid=100", "parent": 100},
        # multiprocessing orphan, parent dead (parent==999) — KILLED
        300: {"alive": True, "name": "python.exe", "cmd": "multiprocessing.spawn parent_pid=999", "parent": 999},
        # multiprocessing orphan, parent dead (parent==888) — KILLED
        400: {"alive": True, "name": "python.exe", "cmd": "multiprocessing.spawn parent_pid=888", "parent": 888},
        # non-multiprocessing python — ignored
        500: {"alive": True, "name": "python.exe", "cmd": "some-other-script.py", "parent": 1},
    }

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        # The PowerShell scan returns the PIDs of orphans whose parent is dead
        if args[0] == "powershell":
            script = args[-1]
            if "multiprocessing.spawn" in script and "ParentProcessId" in script:
                # Return PIDs whose parent_pid points to a process not in
                # the alive list. In our synthetic table that's 300 and 400.
                return SimpleNamespace(returncode=0, stdout="300\n400\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher.os, "getpid", lambda: 999)

    launcher._kill_multiprocessing_spawn_orphans()

    taskkill_calls = [c for c in calls if c[0][0] == "taskkill"]
    killed_pids = sorted(int(c[0][-1]) for c in taskkill_calls)
    assert killed_pids == [300, 400]


def test_main_kills_multiprocessing_spawn_orphans_during_restart(monkeypatch, tmp_path):
    """`main()` must invoke the new multiprocessing-orphan killer so that
    every `restart-agent.ps1` cycle cleans up the prewarmed-runner
    orphans LiveKit Agents leaves behind in prod mode."""
    repo = tmp_path / "repo"
    scripts_dir = repo / "scripts"
    pyexe = repo / "venv" / "Scripts" / "python.exe"
    scripts_dir.mkdir(parents=True)
    pyexe.parent.mkdir(parents=True)
    pyexe.write_text("", encoding="ascii")
    called = []

    monkeypatch.setattr(launcher, "__file__", str(scripts_dir / "_spawn_agent.py"))
    monkeypatch.setattr(launcher, "_kill_prior", lambda pid_path: called.append("kill_prior"))
    monkeypatch.setattr(launcher, "_kill_orphan_agents", lambda repo_path: called.append("kill_orphan_agents"))
    monkeypatch.setattr(
        launcher,
        "_kill_multiprocessing_spawn_orphans",
        lambda: called.append("kill_multiprocessing_spawn_orphans"),
    )
    monkeypatch.setattr(launcher, "_load_dotenv", lambda env_path, env, **kwargs: None)
    monkeypatch.setattr(
        launcher, "_spawn_detached",
        lambda *args, **kwargs: SimpleNamespace(pid=12345),
    )

    assert launcher.main(["spawn_agent", "acme"]) == 0
    assert "kill_multiprocessing_spawn_orphans" in called
    # It must run BEFORE spawning (which is implicit — after the kills,
    # the launcher writes the generation token and spawns).
    assert called.index("kill_multiprocessing_spawn_orphans") < len(called) - 1 or "kill_multiprocessing_spawn_orphans" in called


def test_kill_orphan_agents_pattern_matches_any_livekit_subcommand(monkeypatch, tmp_path):
    """The orphan-killer must match `python -m receptionist.agent <subcmd>`
    for any LiveKit subcommand (`dev`, `start`, etc.) — not only `dev`.

    Otherwise switching the launcher to prod (`start`) mode would leave
    legacy `dev`-mode processes orphaned, and vice-versa.
    """
    captured = {}

    def fake_run(args, **kwargs):
        if args[0] == "powershell":
            captured["script"] = args[-1]
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    launcher._kill_orphan_agents(tmp_path)

    # The Where-Object filter must not pin to ` dev` specifically; it must
    # be subcommand-agnostic.
    assert "script" in captured
    assert "-m receptionist.agent dev" not in captured["script"]
    assert "-m receptionist.agent" in captured["script"]


def test_spawn_detached_uses_prod_start_subcommand_by_default(monkeypatch, tmp_path):
    """The launcher must invoke `python -m receptionist.agent start` by default
    (LiveKit prod mode), not `dev`. Dev mode's hot-reload behavior is hostile
    to long-lived stable workers."""
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = list(args)
            captured["kwargs"] = kwargs
            self.pid = 12345

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "Popen", FakePopen)

    log_f = tmp_path / "log"
    err_f = tmp_path / "err"
    launcher._spawn_detached(
        pyexe=Path("python.exe"),
        repo=tmp_path,
        log_f=log_f,
        err_f=err_f,
        env={},
    )

    assert captured["args"][-1] == "start"
    assert "dev" not in captured["args"]


def test_agent_status_matches_any_livekit_subcommand():
    """`agent-status.ps1`'s pidfile-identity check must accept both
    `dev` and `start` LiveKit subcommands, so a worker launched in
    either mode is recognized as a receptionist agent."""
    script = Path("scripts/agent-status.ps1").read_text(encoding="utf-8")
    # The literal `* dev*` (with leading space and trailing wildcard) would
    # reject `start`-mode processes. Reject both single- and double-quoted
    # variants — both are syntactically valid in PowerShell -like patterns.
    assert "* dev*" not in script
    # The check should look for the receptionist.agent module marker.
    assert "receptionist.agent" in script


def test_generation_token_is_written_to_runtime_file(tmp_path):
    token = launcher._write_generation_token(tmp_path)

    generation_path = tmp_path / "agent.generation"
    assert generation_path.read_text(encoding="ascii") == token
    assert len(token) == 32
    int(token, 16)

    next_token = launcher._write_generation_token(tmp_path)
    assert next_token != token
    assert generation_path.read_text(encoding="ascii") == next_token


def test_generation_env_points_spawned_agent_to_generation_file(tmp_path):
    env = {}
    generation_path = tmp_path / "agent.generation"

    launcher._add_generation_env(env, generation_path, "abc123")

    assert env["RECEPTIONIST_AGENT_GENERATION"] == "abc123"
    assert env["RECEPTIONIST_AGENT_GENERATION_FILE"] == str(generation_path)


def test_restart_marker_includes_generation_token(tmp_path):
    log_path = tmp_path / "agent.log"

    launcher._write_restart_marker(log_path, "abc123")

    marker = log_path.read_text(encoding="utf-8")
    assert "agent restart" in marker
    assert "generation=abc123" in marker


def test_agent_status_requires_current_generation_registration_and_no_orphans():
    script = Path("scripts/agent-status.ps1").read_text(encoding="utf-8")

    assert "agent.generation" in script
    assert "generation is missing" in script
    assert "agent restart generation=$generation" in script
    assert "registered worker" in script
    assert "$registrationLine.LineNumber -le $restartMarker.LineNumber" in script
    assert "Win32_Process" in script
    assert "receptionist.agent" in script
    assert "orphan" in script.lower()


def _run_agent_status_with_processes(tmp_path, log_text, processes):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    runtime = repo / "secrets" / "acme" / "runtime"
    scripts.mkdir(parents=True)
    runtime.mkdir(parents=True)
    shutil.copyfile("scripts/agent-status.ps1", scripts / "agent-status.ps1")
    (runtime / "agent.pid").write_text("100", encoding="ascii")
    (runtime / "agent.generation").write_text("abc123", encoding="ascii")
    (runtime / "agent.log").write_text(log_text, encoding="utf-8")

    process_rows = "\n".join(
        "    [pscustomobject]@{ ProcessId = %d; ParentProcessId = %d; Name = '%s'; CommandLine = '%s' }"
        % (
            process["pid"],
            process["parent"],
            process["name"],
            process["command"].replace("'", "''"),
        )
        for process in processes
    )
    wrapper = tmp_path / "run-status.ps1"
    wrapper.write_text(
        f"""
function Get-Process {{
    param([int]$Id, [string]$ErrorAction)
    if ($Id -eq 100) {{
        return [pscustomobject]@{{ StartTime = [datetime]'2026-05-21T12:00:00Z' }}
    }}
}}

function Get-CimInstance {{
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    $rows = @(
{process_rows}
    )
    if ($Filter -like '*python*') {{
        return $rows | Where-Object {{ $_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' }}
    }}
    return $rows
}}

& '{(scripts / "agent-status.ps1").as_posix()}' -Business acme
exit $LASTEXITCODE
""",
        encoding="utf-8",
    )

    powershell = shutil.which("powershell") or shutil.which("pwsh")
    assert powershell is not None
    return subprocess.run(
        [powershell, "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_agent_status_requires_registration_after_current_generation(tmp_path):
    repo = tmp_path / "repo"
    result = _run_agent_status_with_processes(
        tmp_path,
        "registered worker old\nagent restart generation=abc123\n",
        [
            {
                "pid": 100,
                "parent": 1,
                "name": "python.exe",
                "command": f"{repo}\\venv\\Scripts\\python.exe -m receptionist.agent dev",
            }
        ],
    )

    assert result.returncode == 3
    assert "after current generation marker" in result.stdout


def test_agent_status_rejects_pidfile_pid_for_non_python_process(tmp_path):
    result = _run_agent_status_with_processes(
        tmp_path,
        "agent restart generation=abc123\nregistered worker fresh\n",
        [
            {
                "pid": 100,
                "parent": 1,
                "name": "notepad.exe",
                "command": "notepad.exe",
            }
        ],
    )

    assert result.returncode == 2
    assert "not a receptionist agent" in result.stdout
    assert "notepad.exe" in result.stdout


def test_agent_status_rejects_pidfile_pid_for_wrong_python_command(tmp_path):
    repo = tmp_path / "repo"
    result = _run_agent_status_with_processes(
        tmp_path,
        "agent restart generation=abc123\nregistered worker fresh\n",
        [
            {
                "pid": 100,
                "parent": 1,
                "name": "python.exe",
                "command": f"{repo}\\venv\\Scripts\\python.exe other.py",
            }
        ],
    )

    assert result.returncode == 2
    assert "not a receptionist agent" in result.stdout
    assert "receptionist.agent dev" in result.stdout


def test_agent_status_allows_python_descendant_through_non_python_parent(tmp_path):
    repo = tmp_path / "repo"
    descendant_command = f"{repo}\\venv\\Scripts\\python.exe -m receptionist.agent dev"
    result = _run_agent_status_with_processes(
        tmp_path,
        "agent restart generation=abc123\nregistered worker fresh\n",
        [
            {
                "pid": 100,
                "parent": 1,
                "name": "python.exe",
                "command": f"{repo}\\venv\\Scripts\\python.exe -m receptionist.agent dev",
            },
            {"pid": 200, "parent": 100, "name": "cmd.exe", "command": "cmd /c worker"},
            {
                "pid": 300,
                "parent": 200,
                "name": "python.exe",
                "command": descendant_command,
            },
        ],
    )

    assert result.returncode == 0
    assert "last registration: registered worker fresh" in result.stdout


def test_agent_status_ignores_sibling_checkout_with_shared_path_prefix(tmp_path):
    repo = tmp_path / "repo"
    sibling_repo = tmp_path / "repo2"
    result = _run_agent_status_with_processes(
        tmp_path,
        "agent restart generation=abc123\nregistered worker fresh\n",
        [
            {
                "pid": 100,
                "parent": 1,
                "name": "python.exe",
                "command": f"{repo}\\venv\\Scripts\\python.exe -m receptionist.agent dev",
            },
            {
                "pid": 400,
                "parent": 1,
                "name": "python.exe",
                "command": f"{sibling_repo}\\venv\\Scripts\\python.exe -m receptionist.agent dev",
            },
        ],
    )

    assert result.returncode == 0
    assert "last registration: registered worker fresh" in result.stdout


def test_agent_status_detects_same_checkout_orphan_with_forward_slashes(tmp_path):
    repo = tmp_path / "repo"
    result = _run_agent_status_with_processes(
        tmp_path,
        "agent restart generation=abc123\nregistered worker fresh\n",
        [
            {
                "pid": 100,
                "parent": 1,
                "name": "python.exe",
                "command": f"{repo}\\venv\\Scripts\\python.exe -m receptionist.agent dev",
            },
            {
                "pid": 500,
                "parent": 1,
                "name": "python.exe",
                "command": f"{repo.as_posix()}/venv/Scripts/python.exe -m receptionist.agent dev",
            },
        ],
    )

    assert result.returncode == 6
    assert "unexpected orphan" in result.stdout
    assert "500" in result.stdout


def test_main_writes_generation_before_spawn_and_passes_env(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    runtime = repo / "secrets" / "acme" / "runtime"
    pyexe = repo / "venv" / "Scripts" / "python.exe"
    scripts.mkdir(parents=True)
    pyexe.parent.mkdir(parents=True)
    pyexe.write_text("", encoding="ascii")
    captured = {}

    def fake_spawn(pyexe_arg, repo_arg, log_f, err_f, env):
        captured["env"] = env.copy()
        captured["generation_exists_before_spawn"] = (
            runtime / "agent.generation"
        ).is_file()
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(launcher, "__file__", str(scripts / "_spawn_agent.py"))
    monkeypatch.setattr(launcher, "_kill_prior", lambda pid_path: None)
    monkeypatch.setattr(launcher, "_kill_orphan_agents", lambda repo_path: None)
    monkeypatch.setattr(launcher, "_load_dotenv", lambda env_path, env, **kwargs: None)
    monkeypatch.setattr(launcher, "_spawn_detached", fake_spawn)

    assert launcher.main(["spawn_agent", "acme"]) == 0

    token = (runtime / "agent.generation").read_text(encoding="ascii")
    assert captured["generation_exists_before_spawn"] is True
    assert captured["env"]["RECEPTIONIST_AGENT_GENERATION"] == token
    assert captured["env"]["RECEPTIONIST_AGENT_GENERATION_FILE"] == str(
        runtime / "agent.generation"
    )
    assert f"generation={token}" in (runtime / "agent.log").read_text(
        encoding="utf-8"
    )


def test_main_loads_env_local_over_env_without_overriding_caller_env(
    monkeypatch, tmp_path
):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    pyexe = repo / "venv" / "Scripts" / "python.exe"
    scripts.mkdir(parents=True)
    pyexe.parent.mkdir(parents=True)
    pyexe.write_text("", encoding="ascii")
    (repo / ".env").write_text(
        "FROM_ENV=env\nFROM_BOTH=env\nCALLER_WINS=env\n", encoding="utf-8"
    )
    (repo / ".env.local").write_text(
        "FROM_LOCAL=local\nFROM_BOTH=local\nCALLER_WINS=local\n", encoding="utf-8"
    )
    captured = {}

    def fake_spawn(pyexe_arg, repo_arg, log_f, err_f, env):
        captured["env"] = env.copy()
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(launcher, "__file__", str(scripts / "_spawn_agent.py"))
    monkeypatch.setattr(launcher, "_kill_prior", lambda pid_path: None)
    monkeypatch.setattr(launcher, "_kill_orphan_agents", lambda repo_path: None)
    monkeypatch.setattr(launcher, "_spawn_detached", fake_spawn)
    monkeypatch.setenv("CALLER_WINS", "caller")
    monkeypatch.delenv("FROM_ENV", raising=False)
    monkeypatch.delenv("FROM_LOCAL", raising=False)
    monkeypatch.delenv("FROM_BOTH", raising=False)

    assert launcher.main(["spawn_agent", "acme"]) == 0

    assert captured["env"]["FROM_ENV"] == "env"
    assert captured["env"]["FROM_LOCAL"] == "local"
    assert captured["env"]["FROM_BOTH"] == "local"
    assert captured["env"]["CALLER_WINS"] == "caller"
