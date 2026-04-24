# tests/retention/test_sweeper.py
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from receptionist.retention.sweeper import SweepResult, sweep_directory


def _make_file(path: Path, age_days: int) -> None:
    """Create a file and backdate its mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    past = time.time() - (age_days * 86400)
    os.utime(path, (past, past))


def test_sweep_deletes_files_older_than_ttl(tmp_path):
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    _make_file(old, age_days=45)
    _make_file(new, age_days=5)

    result = sweep_directory(tmp_path, retention_days=30, dry_run=False)

    assert isinstance(result, SweepResult)
    assert old in result.deleted
    assert new not in result.deleted
    assert not old.exists()
    assert new.exists()


def test_sweep_zero_days_keeps_forever(tmp_path):
    f = tmp_path / "a.json"
    _make_file(f, age_days=9999)

    result = sweep_directory(tmp_path, retention_days=0, dry_run=False)

    assert result.deleted == []
    assert result.kept == [f]
    assert f.exists()


def test_sweep_skips_failures_directory(tmp_path):
    """.failures/ content is never swept, even if old."""
    keep_me = tmp_path / ".failures" / "old_failure.json"
    _make_file(keep_me, age_days=9999)

    # Also an old regular file that SHOULD be swept
    also_old = tmp_path / "other_old.json"
    _make_file(also_old, age_days=500)

    result = sweep_directory(tmp_path, retention_days=30, dry_run=False)

    assert keep_me.exists()
    assert not also_old.exists()
    assert keep_me not in result.deleted


def test_sweep_dry_run_does_not_delete(tmp_path):
    old = tmp_path / "old.json"
    _make_file(old, age_days=999)

    result = sweep_directory(tmp_path, retention_days=30, dry_run=True)

    assert old in result.would_delete
    assert old.exists()
    assert result.deleted == []


def test_sweep_missing_directory_is_no_op(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = sweep_directory(missing, retention_days=30, dry_run=False)
    assert result.deleted == []
    assert result.would_delete == []
    assert result.errors == []


def test_sweep_permission_error_is_per_file(tmp_path, monkeypatch):
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    _make_file(f1, age_days=999)
    _make_file(f2, age_days=999)

    original_unlink = Path.unlink

    def flaky_unlink(self):
        if self.name == "a.json":
            raise PermissionError("locked")
        return original_unlink(self)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    result = sweep_directory(tmp_path, retention_days=30, dry_run=False)

    assert f2 in result.deleted
    assert len(result.errors) == 1
    assert f1 not in result.deleted
