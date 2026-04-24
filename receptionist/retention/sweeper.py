# receptionist/retention/sweeper.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from receptionist.config import BusinessConfig

logger = logging.getLogger("receptionist")


@dataclass
class SweepResult:
    deleted: list[Path] = field(default_factory=list)
    would_delete: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, Exception]] = field(default_factory=list)


def sweep_directory(
    directory: Path | str,
    retention_days: int,
    dry_run: bool = False,
) -> SweepResult:
    """Delete files under `directory` older than `retention_days`.

    `retention_days == 0` means "keep forever" — no deletions.
    `.failures/` directories are skipped entirely (failure records are
    not subject to TTL).
    """
    result = SweepResult()
    directory = Path(directory)
    if not directory.exists():
        return result
    if retention_days <= 0:
        # Still list kept files for symmetry
        for path in _walk_files(directory):
            result.kept.append(path)
        return result

    cutoff = time.time() - (retention_days * 86400)

    for path in _walk_files(directory):
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            continue
        except OSError as e:
            # Permission denied, file locked on Windows, etc. Log + continue.
            result.errors.append((path, e))
            logger.warning("retention: stat failed on %s: %s", path, e)
            continue

        if mtime < cutoff:
            if dry_run:
                result.would_delete.append(path)
            else:
                try:
                    path.unlink()
                    result.deleted.append(path)
                    logger.info("retention: deleted %s", path)
                except Exception as e:
                    result.errors.append((path, e))
                    logger.warning("retention: failed to delete %s: %s", path, e)
        else:
            result.kept.append(path)

    return result


def _walk_files(directory: Path):
    """Yield all files under `directory`, skipping anything under a `.failures/` dir."""
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if any(part == ".failures" for part in path.parts):
            continue
        yield path


def sweep_business(
    config: BusinessConfig, dry_run: bool = False
) -> dict[str, SweepResult]:
    """Run sweep for all configured artifact directories of one business."""
    results: dict[str, SweepResult] = {}

    # Messages (file-channel directories only)
    for ch in config.messages.channels:
        if getattr(ch, "type", None) == "file":
            file_path = ch.file_path
            results[f"messages:{file_path}"] = sweep_directory(
                file_path, config.retention.messages_days, dry_run
            )

    # Recordings (local storage only — S3 has its own lifecycle policies)
    if config.recording and config.recording.enabled:
        storage = config.recording.storage
        if storage.type == "local" and storage.local is not None:
            results[f"recordings:{storage.local.path}"] = sweep_directory(
                storage.local.path, config.retention.recordings_days, dry_run
            )

    # Transcripts
    if config.transcripts and config.transcripts.enabled:
        results[f"transcripts:{config.transcripts.storage.path}"] = sweep_directory(
            config.transcripts.storage.path, config.retention.transcripts_days, dry_run
        )

    return results
