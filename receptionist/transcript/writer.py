# receptionist/transcript/writer.py
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from receptionist.config import TranscriptsConfig
from receptionist.transcript.capture import TranscriptSegment
from receptionist.transcript.formatter import to_json, to_markdown
from receptionist.transcript.metadata import CallMetadata

logger = logging.getLogger("receptionist")


@dataclass
class TranscriptWriteResult:
    json_path: Path | None
    markdown_path: Path | None


async def write_transcript_files(
    config: TranscriptsConfig,
    metadata: CallMetadata,
    segments: Sequence[TranscriptSegment],
) -> TranscriptWriteResult:
    if not config.enabled:
        return TranscriptWriteResult(None, None)

    directory = Path(config.storage.path)
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_call_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", metadata.call_id or "unknown")
    stem = f"transcript_{ts}_{safe_call_id}"

    json_path: Path | None = None
    markdown_path: Path | None = None

    if "json" in config.formats:
        candidate = directory / f"{stem}.json"
        try:
            await asyncio.to_thread(
                candidate.write_text,
                to_json(segments, metadata),
                encoding="utf-8",
            )
            json_path = candidate
        except Exception:
            logger.exception("write_transcript_files: JSON write failed")

    if "markdown" in config.formats:
        candidate = directory / f"{stem}.md"
        try:
            await asyncio.to_thread(
                candidate.write_text,
                to_markdown(segments, metadata),
                encoding="utf-8",
            )
            markdown_path = candidate
        except Exception:
            logger.exception("write_transcript_files: Markdown write failed")

    return TranscriptWriteResult(json_path=json_path, markdown_path=markdown_path)
