# tests/booking/test_setup_cli.py
from __future__ import annotations

from unittest.mock import patch

import pytest

from receptionist.booking.setup_cli import main


def test_main_missing_business_exits_nonzero(capsys, tmp_path, monkeypatch):
    """If the business-slug doesn't match any config/businesses/*.yaml, exit 2."""
    monkeypatch.chdir(tmp_path)  # isolated cwd; no config/businesses/ exists
    exit_code = main(["setup", "nonexistent-business"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "nonexistent-business" in captured.err or "not found" in captured.err.lower()


def test_main_requires_subcommand(capsys, tmp_path, monkeypatch):
    """No args -> argparse prints help + exits."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main([])


def test_main_unknown_subcommand_exits_nonzero(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["unknown-command"])


def test_main_setup_invokes_oauth_flow_for_existing_business(tmp_path, monkeypatch, mocker):
    """When a business config exists and oauth-client JSON is present,
    the CLI calls InstalledAppFlow and writes the resulting token."""
    # Build a minimal working business config
    (tmp_path / "config" / "businesses").mkdir(parents=True)
    (tmp_path / "config" / "businesses" / "testbiz.yaml").write_text("""
business: { name: "Test", type: "t", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
""", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    secrets_dir = tmp_path / "secrets" / "testbiz"
    secrets_dir.mkdir(parents=True)
    client_file = secrets_dir / "google-calendar-oauth-client.json"
    client_file.write_text(
        '{"installed": {"client_id": "x", "client_secret": "y"}}',
        encoding="utf-8",
    )

    # Mock the OAuth flow
    fake_creds = mocker.MagicMock()
    fake_creds.to_json.return_value = '{"token": "abc"}'
    fake_flow = mocker.MagicMock()
    fake_flow.run_local_server.return_value = fake_creds
    mocker.patch(
        "receptionist.booking.setup_cli.InstalledAppFlow.from_client_secrets_file",
        return_value=fake_flow,
    )

    exit_code = main(["setup", "testbiz"])
    assert exit_code == 0

    token_file = secrets_dir / "google-calendar-oauth.json"
    assert token_file.exists()
    assert token_file.read_text(encoding="utf-8") == '{"token": "abc"}'


def test_main_setup_missing_oauth_client_json_helpful_error(tmp_path, monkeypatch, capsys):
    """If business config exists but the operator hasn't placed the OAuth
    client JSON yet, the CLI prints actionable guidance."""
    (tmp_path / "config" / "businesses").mkdir(parents=True)
    (tmp_path / "config" / "businesses" / "testbiz.yaml").write_text("""
business: { name: "Test", type: "t", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
""", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["setup", "testbiz"])
    assert exit_code == 2
    captured = capsys.readouterr()
    # Helpful error: tells operator where the file should go and what to do
    err = captured.err
    assert "google-calendar-oauth-client.json" in err
    assert "Google Cloud" in err or "console.cloud.google.com" in err
