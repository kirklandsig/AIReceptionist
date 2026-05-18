# tests/messaging/test_email_channel.py
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from receptionist.config import (
    EmailChannel as EmailChannelConfig,
    EmailConfig, EmailSenderConfig, EmailTriggers, ResendConfig, SMTPConfig,
)
from receptionist.messaging.channels.email import EmailChannel
from receptionist.messaging.models import Message, DispatchContext


def _email_config_smtp() -> EmailConfig:
    return EmailConfig(
        **{"from": "noreply@acme.com"},
        sender=EmailSenderConfig(
            type="smtp",
            smtp=SMTPConfig(host="h", port=587, username="u", password="p", use_tls=True),
        ),
        triggers=EmailTriggers(on_message=True, on_call_end=False),
    )


@pytest.mark.asyncio
async def test_email_channel_sends_message_email(mocker):
    cfg = EmailChannelConfig(type="email", to=["owner@acme.com"])
    email_cfg = _email_config_smtp()

    sender_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    msg = Message("Jane", "+15551112222", "Call me", "Acme", "2026-04-23T14:30:00+00:00")
    await channel.deliver(msg, DispatchContext())

    sender_send.assert_called_once()
    kwargs = sender_send.call_args.kwargs
    assert kwargs["from_"] == "noreply@acme.com"
    assert kwargs["to"] == ["owner@acme.com"]
    assert "Jane" in kwargs["subject"]


@pytest.mark.asyncio
async def test_email_channel_resend_sender(mocker):
    cfg = EmailChannelConfig(type="email", to=["owner@acme.com"])
    email_cfg = EmailConfig(
        **{"from": "noreply@acme.com"},
        sender=EmailSenderConfig(type="resend", resend=ResendConfig(api_key="re_test")),
        triggers=EmailTriggers(),
    )
    sender_send = AsyncMock()
    mocker.patch("receptionist.email.resend.ResendSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    msg = Message("Jane", "+15551112222", "Call me", "Acme", "2026-04-23T14:30:00+00:00")
    await channel.deliver(msg, DispatchContext())
    sender_send.assert_called_once()


@pytest.mark.asyncio
async def test_email_channel_retries_on_transient(mocker):
    from receptionist.email.sender import EmailSendError
    cfg = EmailChannelConfig(type="email", to=["owner@acme.com"])
    email_cfg = _email_config_smtp()

    sender_send = AsyncMock(side_effect=[
        EmailSendError("down", transient=True),
        EmailSendError("down", transient=True),
        None,
    ])
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg, initial_delay=0.001)
    msg = Message("Jane", "+15551112222", "Call me", "Acme", "2026-04-23T14:30:00+00:00")
    await channel.deliver(msg, DispatchContext())

    assert sender_send.call_count == 3


@pytest.mark.asyncio
async def test_email_channel_no_retry_on_permanent(mocker):
    from receptionist.email.sender import EmailSendError
    cfg = EmailChannelConfig(type="email", to=["owner@acme.com"])
    email_cfg = _email_config_smtp()

    sender_send = AsyncMock(side_effect=EmailSendError("bad", transient=False))
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg, initial_delay=0.001)
    msg = Message("Jane", "+15551112222", "Call me", "Acme", "2026-04-23T14:30:00+00:00")
    with pytest.raises(EmailSendError):
        await channel.deliver(msg, DispatchContext())

    assert sender_send.call_count == 1


# ---- deliver_booking tests ----


def _call_metadata_for_booking():
    """CallMetadata fixture in the appointment-booked state."""
    from receptionist.transcript.metadata import CallMetadata
    md = CallMetadata(
        call_id="room-1",
        business_name="Acme",
        caller_phone="+15551112222",
        appointment_booked=True,
        appointment_details={
            "event_id": "evt1",
            "start_iso": "2026-04-28T14:00:00-04:00",
            "end_iso": "2026-04-28T14:30:00-04:00",
            "html_link": "https://calendar.google.com/event?eid=abc",
        },
    )
    md.outcomes.add("appointment_booked")
    md.mark_finalized()
    return md


@pytest.mark.asyncio
async def test_email_channel_deliver_booking_sends_via_smtp(mocker):
    cfg = EmailChannelConfig(type="email", to=["owner@acme.com"])
    email_cfg = _email_config_smtp()

    sender_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    md = _call_metadata_for_booking()
    await channel.deliver_booking(md, DispatchContext())

    sender_send.assert_called_once()
    kwargs = sender_send.call_args.kwargs
    assert kwargs["to"] == ["owner@acme.com"]
    assert "appointment" in kwargs["subject"].lower() or "New appointment booked" in kwargs["subject"]
    assert "calendar.google.com" in kwargs["body_text"]


@pytest.mark.asyncio
async def test_email_channel_deliver_booking_retries_on_transient(mocker):
    from receptionist.email.sender import EmailSendError
    cfg = EmailChannelConfig(type="email", to=["owner@acme.com"])
    email_cfg = _email_config_smtp()

    sender_send = AsyncMock(side_effect=[
        EmailSendError("down", transient=True),
        None,
    ])
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg, initial_delay=0.001)
    md = _call_metadata_for_booking()
    await channel.deliver_booking(md, DispatchContext())

    assert sender_send.call_count == 2


# ---- include_transcript / include_recording_link wiring ----


@pytest.mark.asyncio
async def test_deliver_call_end_embeds_transcript_when_include_transcript_true(
    mocker, tmp_path,
):
    """The YAML knob `include_transcript: true` must reach the template so the
    actual transcript content lands in the email body, not just the path."""
    transcript_md = tmp_path / "t.md"
    transcript_md.write_text(
        "**Agent:** hi\n**Caller:** I want to reschedule.\n",
        encoding="utf-8",
    )
    cfg = EmailChannelConfig(
        type="email", to=["owner@acme.com"], include_transcript=True,
    )
    email_cfg = _email_config_smtp()
    sender_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    md = _call_metadata_for_booking()
    md.outcomes = {"hung_up"}
    ctx = DispatchContext(transcript_markdown_path=str(transcript_md))
    await channel.deliver_call_end(md, ctx)

    kwargs = sender_send.call_args.kwargs
    assert "I want to reschedule." in kwargs["body_text"]
    assert "I want to reschedule." in kwargs["body_html"]


@pytest.mark.asyncio
async def test_deliver_call_end_suppresses_transcript_when_include_transcript_false(
    mocker, tmp_path,
):
    transcript_md = tmp_path / "t.md"
    transcript_md.write_text("**Agent:** confidential\n", encoding="utf-8")
    cfg = EmailChannelConfig(
        type="email", to=["owner@acme.com"], include_transcript=False,
    )
    email_cfg = _email_config_smtp()
    sender_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    md = _call_metadata_for_booking()
    md.outcomes = {"hung_up"}
    ctx = DispatchContext(transcript_markdown_path=str(transcript_md))
    await channel.deliver_call_end(md, ctx)

    kwargs = sender_send.call_args.kwargs
    assert "confidential" not in kwargs["body_text"]
    assert "confidential" not in kwargs["body_html"]


@pytest.mark.asyncio
async def test_deliver_call_end_suppresses_recording_when_include_recording_link_false(
    mocker,
):
    cfg = EmailChannelConfig(
        type="email", to=["owner@acme.com"], include_recording_link=False,
    )
    email_cfg = _email_config_smtp()
    sender_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    md = _call_metadata_for_booking()
    md.outcomes = {"hung_up"}
    ctx = DispatchContext(recording_url="https://example.com/r/123.mp3")
    await channel.deliver_call_end(md, ctx)

    kwargs = sender_send.call_args.kwargs
    assert "example.com/r/123.mp3" not in kwargs["body_text"]
    assert "example.com/r/123.mp3" not in kwargs["body_html"]


@pytest.mark.asyncio
async def test_deliver_message_embeds_transcript_when_include_transcript_true(
    mocker, tmp_path,
):
    """When a take_message email fires with a transcript path in context
    (i.e. dispatched at call-end, not mid-call), the full transcript must
    be embedded in the message email body."""
    transcript_md = tmp_path / "t.md"
    transcript_md.write_text(
        "**Caller:** Please tell Alex I'll call back tomorrow.\n",
        encoding="utf-8",
    )
    cfg = EmailChannelConfig(
        type="email", to=["owner@acme.com"], include_transcript=True,
    )
    email_cfg = _email_config_smtp()
    sender_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    msg = Message("Jane", "+15551112222", "Call me back tomorrow", "Acme", "2026-04-23T14:30:00+00:00")
    ctx = DispatchContext(transcript_markdown_path=str(transcript_md))
    await channel.deliver(msg, ctx)

    kwargs = sender_send.call_args.kwargs
    assert "Please tell Alex I'll call back tomorrow." in kwargs["body_text"]
    assert "Please tell Alex I&#x27;ll call back tomorrow." in kwargs["body_html"] \
        or "Please tell Alex I'll call back tomorrow." in kwargs["body_html"]


@pytest.mark.asyncio
async def test_deliver_message_suppresses_transcript_when_include_transcript_false(
    mocker, tmp_path,
):
    transcript_md = tmp_path / "t.md"
    transcript_md.write_text("**Caller:** super private\n", encoding="utf-8")
    cfg = EmailChannelConfig(
        type="email", to=["owner@acme.com"], include_transcript=False,
    )
    email_cfg = _email_config_smtp()
    sender_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    msg = Message("Jane", "+15551112222", "Call me", "Acme", "2026-04-23T14:30:00+00:00")
    ctx = DispatchContext(transcript_markdown_path=str(transcript_md))
    await channel.deliver(msg, ctx)

    kwargs = sender_send.call_args.kwargs
    assert "super private" not in kwargs["body_text"]
    assert "super private" not in kwargs["body_html"]
