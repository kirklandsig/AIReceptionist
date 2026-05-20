# receptionist/intakes/models.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Literal


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Languages we expect from the LLM via `record_intake_answer`. Other values
# pass through unchanged so callers using less-common languages still get
# their answers stored — the LLM is not bound to this set, it is just the
# advisory shape.
IntakeLanguage = Literal["en", "es"]


@dataclass
class IntakeAnswer:
    """A single question's worth of an in-progress intake.

    `spoken_text` is the verbatim answer in whatever language the caller
    used. `english_summary` is Riley's concise English-language rendering
    of the same answer so the receiving team can scan the submission
    without knowing Spanish (or whatever language the caller spoke).

    For English-language calls, `spoken_text` and `english_summary` are
    typically identical (the LLM may still tidy filler words).
    """

    question_key: str
    prompt: str  # the prompt actually spoken to the caller
    spoken_text: str
    language: str = "en"
    english_summary: str = ""
    captured_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IntakeSubmission:
    """A full intake — partial or final.

    `status="partial"` means Riley is still gathering answers. The file
    on disk is overwritten as new answers come in.

    `status="final"` means `finalize_intake` was called. The partial file
    is removed and a final file is written under a different name.
    """

    case_type: str
    business_name: str
    call_id: str
    caller_name: str
    callback_number: str
    answers: list[IntakeAnswer]
    language: str = "en"
    english_overview: str = ""
    status: Literal["partial", "final"] = "partial"
    started_at: str = field(default_factory=_utc_now_iso)
    completed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "case_type": self.case_type,
            "business_name": self.business_name,
            "call_id": self.call_id,
            "caller_name": self.caller_name,
            "callback_number": self.callback_number,
            "language": self.language,
            "english_overview": self.english_overview,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "answers": [a.to_dict() for a in self.answers],
        }

    def answer_for(self, question_key: str) -> IntakeAnswer | None:
        for a in self.answers:
            if a.question_key == question_key:
                return a
        return None
