from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class Message:
    caller_name: str
    callback_number: str
    message: str
    business_name: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def save_message(
    msg: Message,
    delivery: str,
    file_path: str | None = None,
    webhook_url: str | None = None,
) -> None:
    if delivery == "file":
        _save_to_file(msg, file_path)
    elif delivery == "webhook":
        _send_webhook(msg, webhook_url)
    else:
        raise ValueError(f"Unknown delivery method: {delivery}")


def _save_to_file(msg: Message, file_path: str | None) -> None:
    if file_path is None:
        raise ValueError("file_path is required for file delivery")

    directory = Path(file_path)
    directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"message_{timestamp}.json"

    filepath = directory / filename
    filepath.write_text(json.dumps(asdict(msg), indent=2))


def _send_webhook(msg: Message, webhook_url: str | None) -> None:
    if webhook_url is None:
        raise ValueError("webhook_url is required for webhook delivery")

    # Future: implement HTTP POST to webhook_url
    raise NotImplementedError("Webhook delivery not yet implemented")
