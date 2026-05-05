from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import yaml

from receptionist.voice.setup_cli import main


def test_main_requires_subcommand(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main([])


@pytest.mark.parametrize("evil_slug", [
    "../../etc/passwd",
    "../etc",
    "biz/with/slash",
    "biz with space",
    "biz;rm -rf /",
    "biz\x00null",
    "..\\..\\Windows",
])
def test_main_setup_rejects_traversal_in_business_slug(evil_slug, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["setup", evil_slug])
    captured = capsys.readouterr()
    assert "Invalid business slug" in captured.err


def test_main_setup_missing_business_exits_nonzero(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["setup", "missing"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Business config not found" in captured.err


def test_main_setup_existing_token_updates_yaml_without_codex_login(tmp_path, monkeypatch, mocker):
    _write_business_config(tmp_path, "testbiz")
    auth_path = tmp_path / "secrets" / "testbiz" / "openai_auth.json"
    _write_codex_auth(auth_path)
    monkeypatch.chdir(tmp_path)
    run = mocker.patch("receptionist.voice.setup_cli.subprocess.run")

    exit_code = main([
        "setup", "testbiz",
        "--codex-auth-source", str(tmp_path / "missing" / "auth.json"),
    ])

    assert exit_code == 0
    run.assert_not_called()
    config = yaml.safe_load((tmp_path / "config" / "businesses" / "testbiz.yaml").read_text(
        encoding="utf-8",
    ))
    assert config["voice"]["auth"] == {
        "type": "oauth_codex",
        "path": "secrets/testbiz/openai_auth.json",
    }


def test_main_setup_runs_codex_login_even_when_source_auth_exists(tmp_path, monkeypatch, mocker):
    _write_business_config(tmp_path, "testbiz")
    source = tmp_path / "codex" / "auth.json"
    _write_codex_auth(source)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("receptionist.voice.setup_cli.shutil.which", lambda name: "codex")
    run = mocker.patch(
        "receptionist.voice.setup_cli.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    )

    exit_code = main([
        "setup", "testbiz",
        "--codex-auth-source", str(source),
    ])

    assert exit_code == 0
    run.assert_called_once_with(["codex", "login"], check=False)
    target = tmp_path / "secrets" / "testbiz" / "openai_auth.json"
    assert json.loads(target.read_text(encoding="utf-8"))["tokens"]["access_token"]
    config = yaml.safe_load((tmp_path / "config" / "businesses" / "testbiz.yaml").read_text(
        encoding="utf-8",
    ))
    assert config["voice"]["auth"]["path"] == "secrets/testbiz/openai_auth.json"


def test_main_setup_can_reuse_existing_source_auth_for_smoke_tests(tmp_path, monkeypatch, mocker):
    _write_business_config(tmp_path, "testbiz")
    source = tmp_path / "codex" / "auth.json"
    _write_codex_auth(source)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("receptionist.voice.setup_cli.shutil.which", lambda name: "codex")
    run = mocker.patch("receptionist.voice.setup_cli.subprocess.run")

    exit_code = main([
        "setup", "testbiz",
        "--codex-auth-source", str(source),
        "--reuse-existing-codex-auth",
    ])

    assert exit_code == 0
    run.assert_not_called()
    target = tmp_path / "secrets" / "testbiz" / "openai_auth.json"
    assert json.loads(target.read_text(encoding="utf-8"))["tokens"]["access_token"]


def test_main_setup_runs_codex_login_when_source_missing_then_copies_auth(
    tmp_path, monkeypatch, mocker,
):
    _write_business_config(tmp_path, "testbiz")
    source = tmp_path / "codex" / "auth.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("receptionist.voice.setup_cli.shutil.which", lambda name: "codex")

    def run_login(args, check):
        _write_codex_auth(source)
        return SimpleNamespace(returncode=0)

    run = mocker.patch("receptionist.voice.setup_cli.subprocess.run", side_effect=run_login)

    exit_code = main([
        "setup", "testbiz",
        "--codex-auth-source", str(source),
    ])

    assert exit_code == 0
    run.assert_called_once_with(["codex", "login"], check=False)
    target = tmp_path / "secrets" / "testbiz" / "openai_auth.json"
    assert target.exists()


def test_main_setup_reports_missing_codex_cli(tmp_path, monkeypatch, capsys):
    _write_business_config(tmp_path, "testbiz")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("receptionist.voice.setup_cli.shutil.which", lambda name: None)

    exit_code = main([
        "setup", "testbiz",
        "--codex-auth-source", str(tmp_path / "missing" / "auth.json"),
    ])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Codex CLI not found" in captured.err


def test_main_setup_respects_existing_voice_auth_path(tmp_path, monkeypatch, mocker):
    _write_business_config(
        tmp_path,
        "testbiz",
        voice_block="""
voice:
  voice_id: marin
  model: gpt-realtime-1.5
  auth:
    type: oauth_codex
    path: custom/auth.json
""",
    )
    source = tmp_path / "codex" / "auth.json"
    _write_codex_auth(source)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("receptionist.voice.setup_cli.shutil.which", lambda name: "codex")
    mocker.patch(
        "receptionist.voice.setup_cli.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    )

    exit_code = main([
        "setup", "testbiz",
        "--codex-auth-source", str(source),
    ])

    assert exit_code == 0
    target = tmp_path / "custom" / "auth.json"
    assert target.exists()
    config = yaml.safe_load((tmp_path / "config" / "businesses" / "testbiz.yaml").read_text(
        encoding="utf-8",
    ))
    assert config["voice"]["auth"] == {"type": "oauth_codex", "path": "custom/auth.json"}


def _write_business_config(tmp_path, slug: str, *, voice_block: str | None = None) -> None:
    (tmp_path / "config" / "businesses").mkdir(parents=True)
    voice = voice_block or """
voice:
  voice_id: marin
  model: gpt-realtime-1.5
"""
    (tmp_path / "config" / "businesses" / f"{slug}.yaml").write_text(f"""
business: {{ name: "Test", type: "t", timezone: "UTC" }}
{voice.strip()}
languages: {{ primary: "en", allowed: ["en"] }}
greeting: "Hi"
personality: "Nice"
hours: {{ monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }}
after_hours_message: "Closed"
routing: []
faqs: []
messages: {{ channels: [{{type: "file", file_path: "./m/"}}] }}
""".lstrip(), encoding="utf-8")


def _write_codex_auth(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": "id",
                "access_token": _jwt(exp=datetime.now(timezone.utc) + timedelta(minutes=30)),
                "refresh_token": "refresh",
                "account_id": "acct",
            },
        }),
        encoding="utf-8",
    )


def _jwt(*, exp: datetime) -> str:
    def encode(data: dict[str, object]) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return ".".join([
        encode({"alg": "none", "typ": "JWT"}),
        encode({"exp": int(exp.timestamp())}),
        "sig",
    ])
