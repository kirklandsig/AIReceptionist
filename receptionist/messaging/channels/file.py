# receptionist/messaging/channels/file.py
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from receptionist.config import FileChannel as FileChannelConfig
from receptionist.messaging.models import Message, DispatchContext

logger = logging.getLogger("receptionist")


class FileChannel:
    """Writes messages as JSON files to a configured directory."""

    def __init__(self, config: FileChannelConfig) -> None:
        self.config = config

    async def deliver(self, message: Message, context: DispatchContext) -> None:
        await asyncio.to_thread(self._write, message)

    def _write(self, message: Message) -> None:
        directory = Path(self.config.file_path)
        directory.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"message_{ts}.json"
        path = directory / filename
        path.write_text(json.dumps(message.to_dict(), indent=2), encoding="utf-8")
        logger.info("FileChannel wrote %s", path)
