# receptionist/messaging/models.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


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

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DispatchContext:
    """Auxiliary info passed alongside a Message to channels.

    Populated for call-end dispatch (transcript/recording refs); mostly empty
    for in-call take_message dispatch.
    """
    transcript_json_path: str | None = None
    transcript_markdown_path: str | None = None
    recording_url: str | None = None
    call_id: str | None = None
    business_name: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
