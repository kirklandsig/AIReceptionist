# tests/email/test_smtp.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from receptionist.config import SMTPConfig
from receptionist.email.sender import EmailSendError
from receptionist.email.smtp import SMTPSender


@pytest.mark.asyncio
async def test_smtp_send_calls_aiosmtplib():
    cfg = SMTPConfig(host="smtp.test", port=587, username="u", password="p", use_tls=True)
    sender = SMTPSender(cfg)
    with patch("aiosmtplib.send", AsyncMock()) as mock_send:
        await sender.send(
            from_="from@test",
            to=["to@test"],
            subject="Hi",
            body_text="body",
            body_html=None,
        )
    assert mock_send.called
    kwargs = mock_send.call_args.kwargs
    assert kwargs["hostname"] == "smtp.test"
    assert kwargs["port"] == 587
    assert kwargs["username"] == "u"
    assert kwargs["password"] == "p"
    assert kwargs["start_tls"] is True


@pytest.mark.asyncio
async def test_smtp_connection_error_is_transient():
    import aiosmtplib
    cfg = SMTPConfig(host="smtp.test", port=587, username="u", password="p", use_tls=True)
    sender = SMTPSender(cfg)
    with patch("aiosmtplib.send", AsyncMock(side_effect=aiosmtplib.SMTPConnectError("down"))):
        with pytest.raises(EmailSendError) as exc:
            await sender.send(from_="a@b", to=["c@d"], subject="s", body_text="t", body_html=None)
    assert exc.value.transient is True


@pytest.mark.asyncio
async def test_smtp_auth_error_is_permanent():
    import aiosmtplib
    cfg = SMTPConfig(host="smtp.test", port=587, username="u", password="p", use_tls=True)
    sender = SMTPSender(cfg)
    # SMTPAuthenticationError takes positional-only (code, message) per aiosmtplib>=3
    with patch("aiosmtplib.send", AsyncMock(side_effect=aiosmtplib.SMTPAuthenticationError(535, "bad auth"))):
        with pytest.raises(EmailSendError) as exc:
            await sender.send(from_="a@b", to=["c@d"], subject="s", body_text="t", body_html=None)
    assert exc.value.transient is False


@pytest.mark.asyncio
async def test_smtp_includes_body_html_when_provided():
    cfg = SMTPConfig(host="smtp.test", port=587, username="u", password="p", use_tls=True)
    sender = SMTPSender(cfg)
    with patch("aiosmtplib.send", AsyncMock()) as mock_send:
        await sender.send(
            from_="a@b",
            to=["c@d"],
            subject="s",
            body_text="plain",
            body_html="<p>html</p>",
        )
    msg = mock_send.call_args.args[0]
    assert msg.is_multipart()
