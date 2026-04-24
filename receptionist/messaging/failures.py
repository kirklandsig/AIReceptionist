# receptionist/messaging/failures.py
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from receptionist.config import FileChannel as FileChannelConfig
from receptionist.messaging.models import Message, DispatchContext

logger = logging.getLogger("receptionist")


def resolve_failures_dir(channels: list, business_name: str) -> Path:
    """Return the directory where failure records should be written.

    Path resolution order:
      1. If a FileChannel is configured in `channels`, use `<file_path>/.failures/`.
      2. Otherwise, use `./messages/<business_name_slug>/.failures/` resolved
         to an ABSOLUTE path — so operators always know where to look even
         when the agent was started from a non-project cwd.
    """
    for ch in channels:
        if isinstance(ch, FileChannelConfig):
            return Path(ch.file_path) / ".failures"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", business_name).strip("-").lower() or "unknown"
    resolved = (Path.cwd() / "messages" / slug / ".failures").resolve()
    logger.info("resolve_failures_dir: no FileChannel; using fallback %s", resolved)
    return resolved


async def record_failure(
    directory: Path,
    channel_name: str,
    message: Message,
    context: DispatchContext,
    attempts: list[dict],
) -> None:
    await asyncio.to_thread(_write_record, directory, channel_name, message, context, attempts)


def _write_record(
    directory: Path,
    channel_name: str,
    message: Message,
    context: DispatchContext,
    attempts: list[dict],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = directory / f"{ts}_{channel_name}.json"
    record = {
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "channel": channel_name,
        "message": message.to_dict(),
        "context": context.to_dict(),
        "attempts": attempts,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.warning("Recorded delivery failure: %s", path)
