# tests/messaging/test_failures_cli.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from receptionist.messaging.failures_cli import list_failures


def _write_failure(directory: Path, filename: str, payload: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(json.dumps(payload), encoding="utf-8")


def _sample(channel: str = "email") -> dict:
    return {
        "failed_at": "2026-04-23T14:30:00+00:00",
        "channel": channel,
        "message": {"caller_name": "Jane", "callback_number": "+1", "message": "x", "business_name": "Acme", "timestamp": "2026-04-23T14:29:00+00:00"},
        "context": {},
        "attempts": [
            {"attempt": 1, "error_type": "SMTPAuthError", "error_detail": "535 bad", "at": "2026-04-23T14:30:00+00:00"},
        ],
    }


def test_list_empty_prints_no_failures(tmp_path, capsys):
    exit_code = list_failures([str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No failures" in captured.out


def test_list_single_failure_shows_channel_and_caller(tmp_path, capsys):
    _write_failure(tmp_path / ".failures", "2026_x.json", _sample("email"))
    exit_code = list_failures([str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "email" in captured.out
    assert "Jane" in captured.out


def test_list_corrupt_json_is_skipped(tmp_path, capsys):
    (tmp_path / ".failures").mkdir(parents=True)
    (tmp_path / ".failures" / "corrupt.json").write_text("{not json", encoding="utf-8")
    _write_failure(tmp_path / ".failures", "valid.json", _sample("webhook"))

    exit_code = list_failures([str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "webhook" in captured.out
    assert "corrupt" in captured.err.lower() or "skip" in captured.err.lower()


def test_list_multiple_paths(tmp_path, capsys):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    _write_failure(dir_a / ".failures", "a1.json", _sample("email"))
    _write_failure(dir_b / ".failures", "b1.json", _sample("webhook"))

    exit_code = list_failures([str(dir_a), str(dir_b)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "email" in captured.out
    assert "webhook" in captured.out
