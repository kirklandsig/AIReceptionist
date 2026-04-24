# tests/transcript/test_formatter.py
from __future__ import annotations

import json

from receptionist.transcript.capture import TranscriptSegment, SpeakerRole
from receptionist.transcript.formatter import to_json, to_markdown
from receptionist.transcript.metadata import CallMetadata


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(role=SpeakerRole.ASSISTANT, text="Thanks for calling Acme.", created_at=100.0),
        TranscriptSegment(role=SpeakerRole.USER, text="Do you accept Cigna?", created_at=101.0, language="en"),
        TranscriptSegment(role=SpeakerRole.TOOL, text="lookup_faq", created_at=102.0,
                          tool_arguments='{"question": "Cigna"}', tool_output="Yes, we accept Cigna."),
        TranscriptSegment(role=SpeakerRole.ASSISTANT, text="Yes, we accept Cigna.", created_at=103.0),
    ]


def _metadata() -> CallMetadata:
    md = CallMetadata(
        call_id="room-1", business_name="Acme",
        caller_phone="+15551112222",
        start_ts="2026-04-23T14:30:00+00:00",
    )
    md.languages_detected.add("en")
    md.faqs_answered.append("Cigna")
    return md


def test_to_json_is_valid_and_has_expected_keys():
    out = to_json(_segments(), _metadata())
    data = json.loads(out)
    assert data["metadata"]["call_id"] == "room-1"
    assert len(data["segments"]) == 4
    assert data["segments"][0]["role"] == "assistant"
    assert data["segments"][2]["role"] == "tool"
    assert data["segments"][2]["tool_arguments"] == '{"question": "Cigna"}'


def test_to_markdown_has_headers_and_roles():
    out = to_markdown(_segments(), _metadata())
    assert "# Call transcript — Acme" in out
    assert "Caller: +15551112222" in out
    assert "**Agent:**" in out
    assert "**Caller:**" in out
    assert "**Tool:** lookup_faq" in out


def test_to_markdown_shows_tool_arguments_and_output():
    out = to_markdown(_segments(), _metadata())
    assert '{"question": "Cigna"}' in out
    assert "Yes, we accept Cigna." in out


def test_to_json_empty_segments():
    out = to_json([], _metadata())
    data = json.loads(out)
    assert data["segments"] == []
