# tests/integration/test_call_flow.py
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx
from httpx import Response

from receptionist.config import (
    BusinessConfig, EmailChannel as EmailChannelConfig,
    EmailConfig, EmailSenderConfig, EmailTriggers,
    FileChannel as FileChannelConfig, SMTPConfig,
    TranscriptsConfig, TranscriptStorageConfig,
    WebhookChannel as WebhookChannelConfig,
)
from receptionist.lifecycle import CallLifecycle
from receptionist.messaging.dispatcher import Dispatcher
from receptionist.messaging.models import DispatchContext, Message


def _full_config(tmp_path, v2_yaml) -> BusinessConfig:
    """Config with file + email + webhook channels, transcripts enabled,
    and an on_call_end email trigger.
    """
    base = BusinessConfig.from_yaml_string(v2_yaml)
    return base.model_copy(update={
        "messages": base.messages.model_copy(update={
            "channels": [
                FileChannelConfig(type="file", file_path=str(tmp_path / "messages")),
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
                WebhookChannelConfig(type="webhook", url="https://hooks.example.com/in", headers={}),
            ],
        }),
        "email": EmailConfig(
            **{"from": "noreply@acme.com"},
            sender=EmailSenderConfig(
                type="smtp",
                smtp=SMTPConfig(host="h", port=587, username="u", password="p", use_tls=True),
            ),
            triggers=EmailTriggers(on_message=True, on_call_end=True),
        ),
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path / "transcripts")),
            formats=["json", "markdown"],
        ),
    })


async def _drain_pending_tasks() -> None:
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
@respx.mock
async def test_take_message_dispatches_to_all_three_channels(tmp_path, v2_yaml, mocker):
    config = _full_config(tmp_path, v2_yaml)

    # Mock the email sender + webhook endpoint
    smtp_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", smtp_send)

    webhook_route = respx.post("https://hooks.example.com/in").mock(return_value=Response(200))

    dispatcher = Dispatcher(
        channels=config.messages.channels,
        business_name=config.business.name,
        email_config=config.email,
    )
    msg = Message("Jane", "+15551112222", "Call me", config.business.name)
    await dispatcher.dispatch_message(msg, DispatchContext(call_id="room-1", business_name=config.business.name))
    await _drain_pending_tasks()

    # File channel fired synchronously
    files = list((tmp_path / "messages").glob("*.json"))
    assert len(files) == 1

    # Email + webhook fired as background tasks
    smtp_send.assert_called_once()
    assert webhook_route.called


@pytest.mark.asyncio
async def test_call_end_writes_transcript_and_fires_call_end_email(tmp_path, v2_yaml, mocker):
    config = _full_config(tmp_path, v2_yaml)

    smtp_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", smtp_send)

    lifecycle = CallLifecycle(config=config, call_id="room-xyz", caller_phone="+15551112222")
    lifecycle.record_faq_answered("hours")  # simulate a tool invocation

    await lifecycle.on_call_ended()
    await _drain_pending_tasks()

    # Transcript files written
    transcripts_dir = tmp_path / "transcripts"
    assert len(list(transcripts_dir.glob("*.json"))) == 1
    assert len(list(transcripts_dir.glob("*.md"))) == 1

    # Metadata finalized
    assert lifecycle.metadata.end_ts is not None
    assert lifecycle.metadata.outcome == "hung_up"  # no transfer or message event
    assert lifecycle.metadata.faqs_answered == ["hours"]

    # Call-end email sent
    smtp_send.assert_called_once()
    kwargs = smtp_send.call_args.kwargs
    assert "hung_up" in kwargs["subject"].lower() or "Hung up" in kwargs["subject"]


@pytest.mark.asyncio
async def test_call_end_email_includes_transcript_path(tmp_path, v2_yaml, mocker):
    config = _full_config(tmp_path, v2_yaml)
    smtp_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", smtp_send)

    lifecycle = CallLifecycle(config=config, call_id="room-xyz", caller_phone=None)
    await lifecycle.on_call_ended()
    await _drain_pending_tasks()

    body_text = smtp_send.call_args.kwargs["body_text"]
    assert "transcript" in body_text.lower()
    assert "room-xyz" in body_text or str(tmp_path / "transcripts") in body_text


@pytest.mark.asyncio
async def test_call_end_without_email_config_does_not_raise(tmp_path, v2_yaml):
    """If on_call_end trigger is on but no email channel exists, we log + continue."""
    base = BusinessConfig.from_yaml_string(v2_yaml)
    # Only a file channel; on_call_end trigger on but no email channel
    config = base.model_copy(update={
        "email": EmailConfig(
            **{"from": "noreply@acme.com"},
            sender=EmailSenderConfig(
                type="smtp",
                smtp=SMTPConfig(host="h", port=587, username="u", password="p", use_tls=True),
            ),
            triggers=EmailTriggers(on_message=False, on_call_end=True),
        ),
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path)),
            formats=["json"],
        ),
    })
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    # Should not raise
    await lifecycle.on_call_ended()
