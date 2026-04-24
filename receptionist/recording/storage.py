# receptionist/recording/storage.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from receptionist.config import RecordingStorageConfig


@dataclass
class RecordingDestination:
    kind: Literal["local", "s3"]
    local_path: Path | None = None
    s3_bucket: str | None = None
    s3_key: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None


def resolve_destination(
    config: RecordingStorageConfig, call_id: str
) -> RecordingDestination:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", call_id).strip("-") or "unknown"
    filename = f"recording_{ts}_{safe_id}.mp4"

    if config.type == "local":
        assert config.local is not None
        return RecordingDestination(
            kind="local",
            local_path=Path(config.local.path) / filename,
        )
    if config.type == "s3":
        assert config.s3 is not None
        prefix = config.s3.prefix or ""
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return RecordingDestination(
            kind="s3",
            s3_bucket=config.s3.bucket,
            s3_key=f"{prefix}{filename}",
            s3_region=config.s3.region,
            s3_endpoint_url=config.s3.endpoint_url,
        )
    raise ValueError(f"Unknown recording storage type: {config.type}")
