# receptionist/transcript/capture.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from receptionist.transcript.metadata import CallMetadata

logger = logging.getLogger("receptionist")


class SpeakerRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class TranscriptSegment:
    role: SpeakerRole
    text: str
    created_at: float
    language: str | None = None
    tool_arguments: str | None = None
    tool_output: str | None = None


class TranscriptCapture:
    """Subscribes to AgentSession events and accumulates TranscriptSegments.

    Event names verified against livekit-agents==1.5.6:
      - user_input_transcribed (UserInputTranscribedEvent)
      - conversation_item_added (ConversationItemAddedEvent) — assistant chat
      - function_tools_executed (FunctionToolsExecutedEvent)
    """

    def __init__(self, emitter: Any, metadata: CallMetadata) -> None:
        self.segments: list[TranscriptSegment] = []
        self.metadata = metadata
        emitter.on("user_input_transcribed", self._on_user_input)
        emitter.on("conversation_item_added", self._on_conversation_item)
        emitter.on("function_tools_executed", self._on_tools_executed)

    def _on_user_input(self, event: Any) -> None:
        try:
            if not getattr(event, "is_final", False):
                return
            text = event.transcript
            lang = getattr(event, "language", None)
            self.segments.append(TranscriptSegment(
                role=SpeakerRole.USER,
                text=text,
                created_at=event.created_at,
                language=lang,
            ))
            if lang:
                self.metadata.languages_detected.add(lang)
        except Exception:
            logger.exception("TranscriptCapture: error handling user_input_transcribed")

    def _on_conversation_item(self, event: Any) -> None:
        try:
            item = event.item
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None) or getattr(item, "text", None)
            if role != "assistant" or not text:
                return
            self.segments.append(TranscriptSegment(
                role=SpeakerRole.ASSISTANT,
                text=text,
                created_at=event.created_at,
            ))
        except Exception:
            logger.exception("TranscriptCapture: error handling conversation_item_added")

    def _on_tools_executed(self, event: Any) -> None:
        try:
            calls = event.function_calls or []
            outputs = event.function_call_outputs or []
            for i, call in enumerate(calls):
                out = outputs[i] if i < len(outputs) else None
                self.segments.append(TranscriptSegment(
                    role=SpeakerRole.TOOL,
                    text=call.name,
                    created_at=event.created_at,
                    tool_arguments=getattr(call, "arguments", None),
                    tool_output=(getattr(out, "output", None) if out is not None else None),
                ))
        except Exception:
            logger.exception("TranscriptCapture: error handling function_tools_executed")
