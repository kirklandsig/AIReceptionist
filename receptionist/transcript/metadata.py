# receptionist/transcript/metadata.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CallMetadata:
    call_id: str
    business_name: str
    caller_phone: str | None = None
    start_ts: str = ""
    end_ts: str | None = None
    duration_seconds: float | None = None
    outcome: str | None = None  # "transferred" | "message_taken" | "hung_up" | None
    transfer_target: str | None = None
    message_taken: bool = False
    faqs_answered: list[str] = field(default_factory=list)
    languages_detected: set[str] = field(default_factory=set)
    recording_failed: bool = False
    recording_artifact: str | None = None

    def __post_init__(self):
        if not self.start_ts:
            self.start_ts = datetime.now(timezone.utc).isoformat()

    def mark_finalized(self) -> None:
        if self.end_ts is None:
            self.end_ts = datetime.now(timezone.utc).isoformat()
        if self.outcome is None:
            self.outcome = "hung_up"
        try:
            start = datetime.fromisoformat(self.start_ts)
            end = datetime.fromisoformat(self.end_ts)
            self.duration_seconds = (end - start).total_seconds()
        except ValueError:
            pass

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "business_name": self.business_name,
            "caller_phone": self.caller_phone,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "duration_seconds": self.duration_seconds,
            "outcome": self.outcome,
            "transfer_target": self.transfer_target,
            "message_taken": self.message_taken,
            "faqs_answered": list(self.faqs_answered),
            "languages_detected": sorted(self.languages_detected),
            "recording_failed": self.recording_failed,
            "recording_artifact": self.recording_artifact,
        }
