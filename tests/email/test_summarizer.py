# tests/email/test_summarizer.py
from __future__ import annotations

import json

import httpx
import pytest
import respx

from receptionist.config import EmailSummaryConfig
from receptionist.email.summarizer import generate_call_summary, _API_URL
from receptionist.intakes.models import IntakeAnswer, IntakeSubmission
from receptionist.messaging.models import Message
from receptionist.transcript.capture import SpeakerRole, TranscriptSegment
from receptionist.transcript.metadata import CallMetadata


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(role=SpeakerRole.ASSISTANT, text="Thank you for calling.", created_at=1.0),
        TranscriptSegment(role=SpeakerRole.USER, text="I got hurt at work.", created_at=2.0),
        TranscriptSegment(role=SpeakerRole.TOOL, text="record_intake_answer", created_at=3.0),
    ]


def _metadata() -> CallMetadata:
    return CallMetadata(
        call_id="room-1", business_name="Acme Law",
        caller_phone="+16315551234", outcomes={"intake_submitted"},
    )


def _config(**overrides) -> EmailSummaryConfig:
    return EmailSummaryConfig(**overrides)


def _ok_response(content: str = "A caller completed a full intake.") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.mark.asyncio
@respx.mock
async def test_summary_success(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    route = respx.post(_API_URL).mock(return_value=_ok_response())
    result = await generate_call_summary(
        segments=_segments(), metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(),
    )
    assert result == "A caller completed a full intake."
    sent = route.calls[0].request
    body = json.loads(sent.content)
    assert body["model"] == "gpt-5-mini"
    assert body["reasoning_effort"] == "medium"
    assert "I got hurt at work." in body["messages"][1]["content"]
    assert "+16315551234" in body["messages"][1]["content"]
    assert sent.headers["authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
@respx.mock
async def test_summary_omits_reasoning_effort_when_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    route = respx.post(_API_URL).mock(return_value=_ok_response())
    await generate_call_summary(
        segments=[], metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(reasoning_effort=None),
    )
    body = json.loads(route.calls[0].request.content)
    assert "reasoning_effort" not in body


@pytest.mark.asyncio
@respx.mock
async def test_summary_skips_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = await generate_call_summary(
        segments=_segments(), metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(),
    )
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_summary_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = await generate_call_summary(
        segments=_segments(), metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(enabled=False),
    )
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_summary_returns_none_on_http_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    respx.post(_API_URL).mock(return_value=httpx.Response(400, json={"error": {"message": "bad model"}}))
    result = await generate_call_summary(
        segments=_segments(), metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(),
    )
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_summary_returns_none_on_network_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    respx.post(_API_URL).mock(side_effect=httpx.ConnectTimeout("boom"))
    result = await generate_call_summary(
        segments=_segments(), metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(),
    )
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_summary_returns_none_on_malformed_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    respx.post(_API_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
    result = await generate_call_summary(
        segments=_segments(), metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(),
    )
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_summary_truncates_transcript_to_last_chars(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    route = respx.post(_API_URL).mock(return_value=_ok_response())
    long_segments = [
        TranscriptSegment(role=SpeakerRole.USER, text="x" * 500, created_at=float(i))
        for i in range(100)
    ]
    await generate_call_summary(
        segments=long_segments, metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(max_transcript_chars=1000),
    )
    body = json.loads(route.calls[0].request.content)
    transcript_part = body["messages"][1]["content"].split("TRANSCRIPT:\n", 1)[1]
    assert len(transcript_part) <= 1000
    assert transcript_part.endswith("x" * 50)


@pytest.mark.asyncio
@respx.mock
async def test_summary_includes_intake_and_message_facts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    route = respx.post(_API_URL).mock(return_value=_ok_response())
    submission = IntakeSubmission(
        case_type="workers_comp", business_name="Acme Law", call_id="room-1",
        caller_name="Jane Doe", callback_number="+13475550000",
        answers=[IntakeAnswer(question_key="k", prompt="P?", spoken_text="A")],
        status="partial",
    )
    msg = Message("Jane Doe", "+13475550000", "Call me back", "Acme Law")
    await generate_call_summary(
        segments=[], metadata=_metadata(), submission=submission,
        captured_messages=[msg], config=_config(),
    )
    content = json.loads(route.calls[0].request.content)["messages"][1]["content"]
    assert "workers_comp" in content
    assert "partial" in content
    assert "Jane Doe" in content
    assert "Call me back" in content


@pytest.mark.asyncio
@respx.mock
async def test_summary_returns_none_on_non_string_content(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    respx.post(_API_URL).mock(return_value=httpx.Response(
        200,
        json={"choices": [{"message": {"content": [{"type": "text", "text": "hi"}]}}]},
    ))
    result = await generate_call_summary(
        segments=_segments(), metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(),
    )
    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, "", "   "])
@respx.mock
async def test_summary_returns_none_on_empty_content(monkeypatch, content):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    respx.post(_API_URL).mock(return_value=httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]},
    ))
    result = await generate_call_summary(
        segments=_segments(), metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(),
    )
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_summary_applies_configured_timeout(monkeypatch, mocker):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    respx.post(_API_URL).mock(return_value=_ok_response())
    spy = mocker.patch.object(httpx, "AsyncClient", wraps=httpx.AsyncClient)
    await generate_call_summary(
        segments=[], metadata=_metadata(), submission=None,
        captured_messages=[], config=_config(timeout_seconds=7.5),
    )
    assert spy.call_args.kwargs["timeout"] == 7.5
