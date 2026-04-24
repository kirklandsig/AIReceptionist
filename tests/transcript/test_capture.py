# tests/transcript/test_capture.py
from __future__ import annotations

from unittest.mock import MagicMock

from receptionist.transcript.capture import (
    TranscriptCapture, TranscriptSegment, SpeakerRole,
)
from receptionist.transcript.metadata import CallMetadata


class FakeEmitter:
    """Mimics the subset of livekit.agents.AgentSession.on() we use."""

    def __init__(self):
        self.handlers: dict[str, list] = {}

    def on(self, event: str, fn):
        self.handlers.setdefault(event, []).append(fn)
        return fn

    def emit(self, event: str, payload):
        for fn in self.handlers.get(event, []):
            fn(payload)


def test_capture_records_user_input():
    emitter = FakeEmitter()
    md = CallMetadata(call_id="room-1", business_name="Acme")
    capture = TranscriptCapture(emitter, md)

    user_event = MagicMock(
        transcript="Hi, I'd like to book an appointment.",
        is_final=True,
        language="en",
        created_at=100.0,
    )
    emitter.emit("user_input_transcribed", user_event)

    assert len(capture.segments) == 1
    seg = capture.segments[0]
    assert seg.role == SpeakerRole.USER
    assert seg.text == "Hi, I'd like to book an appointment."
    assert seg.language == "en"


def test_capture_skips_non_final_user_segments():
    emitter = FakeEmitter()
    md = CallMetadata(call_id="room-1", business_name="Acme")
    capture = TranscriptCapture(emitter, md)

    emitter.emit("user_input_transcribed", MagicMock(
        transcript="hi", is_final=False, language="en", created_at=100.0,
    ))
    assert capture.segments == []


def test_capture_records_assistant_messages():
    emitter = FakeEmitter()
    md = CallMetadata(call_id="room-1", business_name="Acme")
    capture = TranscriptCapture(emitter, md)

    item = MagicMock(role="assistant", text_content="Sure, I can help.")
    event = MagicMock(item=item, created_at=101.0)
    emitter.emit("conversation_item_added", event)

    assert len(capture.segments) == 1
    assert capture.segments[0].role == SpeakerRole.ASSISTANT
    assert capture.segments[0].text == "Sure, I can help."


def test_capture_records_tool_calls():
    emitter = FakeEmitter()
    md = CallMetadata(call_id="room-1", business_name="Acme")
    capture = TranscriptCapture(emitter, md)

    call = MagicMock()
    call.name = "lookup_faq"
    call.arguments = '{"question": "hours"}'

    output = MagicMock()
    output.output = "We are open 8-5."

    event = MagicMock(
        function_calls=[call],
        function_call_outputs=[output],
        created_at=102.0,
    )
    emitter.emit("function_tools_executed", event)

    assert len(capture.segments) == 1
    seg = capture.segments[0]
    assert seg.role == SpeakerRole.TOOL
    assert seg.text == "lookup_faq"
    assert "hours" in (seg.tool_arguments or "")


def test_capture_updates_language_on_metadata():
    emitter = FakeEmitter()
    md = CallMetadata(call_id="room-1", business_name="Acme")
    capture = TranscriptCapture(emitter, md)

    emitter.emit("user_input_transcribed", MagicMock(
        transcript="Hola", is_final=True, language="es", created_at=100.0,
    ))
    emitter.emit("user_input_transcribed", MagicMock(
        transcript="Hello", is_final=True, language="en", created_at=101.0,
    ))
    assert md.languages_detected == {"es", "en"}


def test_capture_handler_exceptions_are_swallowed():
    """A malformed event must not propagate — the call must keep going."""
    emitter = FakeEmitter()
    md = CallMetadata(call_id="room-1", business_name="Acme")
    capture = TranscriptCapture(emitter, md)

    bad_event = object()
    emitter.emit("user_input_transcribed", bad_event)
    assert capture.segments == []
