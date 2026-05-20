# receptionist/intakes/storage.py
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from receptionist.intakes.models import IntakeSubmission

logger = logging.getLogger("receptionist")


def _safe_call_id(call_id: str) -> str:
    """Sanitize a call_id for filesystem use.

    Strips anything that isn't alnum/dash/underscore. Falls back to a
    random suffix if the result is empty so partial writes still land
    somewhere deterministic.
    """
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", call_id or "").strip("-")
    return safe or f"unknown-{uuid.uuid4().hex[:8]}"


def _partial_path(directory: Path, call_id: str) -> Path:
    return directory / f"intake_{_safe_call_id(call_id)}.partial.json"


def _final_path(directory: Path, call_id: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return directory / f"intake_{ts}_{_safe_call_id(call_id)}.final.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically by writing to a sibling tmp file and renaming.

    Avoids a half-written file being read by an operator or replay tool
    if the process crashes between open and close.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # Best-effort cleanup. The next call will overwrite the tmp anyway
        # but leaving stale temp files around clutters the intake dir.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


async def persist_partial(submission: IntakeSubmission, directory: str | Path) -> Path:
    """Write or overwrite the partial intake JSON for this call.

    Returns the path that was written. Safe to call repeatedly as
    answers come in — each call replaces the file atomically.
    """
    dir_path = Path(directory)
    target = _partial_path(dir_path, submission.call_id)
    await asyncio.to_thread(_atomic_write_json, target, submission.to_dict())
    logger.info("Intake partial persisted: %s", target)
    return target


async def persist_final(submission: IntakeSubmission, directory: str | Path) -> Path:
    """Write the final intake JSON and remove the partial copy.

    Returns the final-file path. If the partial removal fails, the final
    file is still written — operators can clean up by hand. We never
    fail the call over a leftover partial.
    """
    if submission.status != "final":
        raise ValueError(
            f"persist_final called with non-final submission (status={submission.status!r})"
        )
    dir_path = Path(directory)
    target = _final_path(dir_path, submission.call_id)
    await asyncio.to_thread(_atomic_write_json, target, submission.to_dict())
    logger.info("Intake final persisted: %s", target)
    # Best-effort partial removal — the final file is the source of truth now.
    partial = _partial_path(dir_path, submission.call_id)
    try:
        await asyncio.to_thread(partial.unlink)
        logger.info("Intake partial removed after finalization: %s", partial)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Failed to remove intake partial %s: %s", partial, e)
    return target
