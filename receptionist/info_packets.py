from __future__ import annotations

import re

from receptionist.config import EmailConfig, InfoPacket
from receptionist.email.resend import ResendSender
from receptionist.email.sender import EmailSendError, EmailSender
from receptionist.email.smtp import SMTPSender
from receptionist.email.templates import build_info_packet_email
from receptionist.messaging.retry import RetryPolicy, retry_with_backoff

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email_destination(value: str) -> bool:
    return bool(_EMAIL_RE.fullmatch((value or "").strip()))


def _build_sender(email_config: EmailConfig) -> EmailSender:
    if email_config.sender.type == "smtp":
        assert email_config.sender.smtp is not None
        return SMTPSender(email_config.sender.smtp)
    if email_config.sender.type == "resend":
        assert email_config.sender.resend is not None
        return ResendSender(email_config.sender.resend)
    raise ValueError(f"Unknown email sender type: {email_config.sender.type}")


async def send_info_packet_email(
    *,
    packet: InfoPacket,
    email_config: EmailConfig,
    destination: str,
    business_name: str,
    call_id: str,
) -> None:
    subject, body_text, body_html = build_info_packet_email(
        packet, business_name=business_name, call_id=call_id,
    )
    sender = _build_sender(email_config)
    policy = RetryPolicy(max_attempts=3, initial_delay=1.0, factor=2.0)

    async def _send() -> None:
        await sender.send(
            from_=email_config.from_,
            to=[destination],
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

    await retry_with_backoff(
        _send,
        policy,
        is_transient=lambda e: isinstance(e, EmailSendError) and e.transient,
    )
