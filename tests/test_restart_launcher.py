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
