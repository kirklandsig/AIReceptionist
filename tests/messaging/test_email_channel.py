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
