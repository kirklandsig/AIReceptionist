from pathlib import Path


def test_restart_agent_powershell_delegates_to_python_launcher():
    script = Path("scripts/restart-agent.ps1").read_text(encoding="utf-8")
    assert "scripts\\_spawn_agent.py" in script or "scripts/_spawn_agent.py" in script
    assert "Win32_Process" not in script
