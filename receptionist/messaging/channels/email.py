# receptionist/messaging/channels/email.py
from __future__ import annotations

import logging

from receptionist.config import EmailChannel as EmailChannelConfig, EmailConfig
from receptionist.email.sender import EmailSendError, EmailSender
from receptionist.email.smtp import SMTPSender
from receptionist.email.resend import ResendSender
from receptionist.email.templates import build_message_email, build_call_end_email
from receptionist.messaging.models import Message, DispatchContext
from receptionist.messaging.retry import retry_with_backoff, RetryPolicy
from receptionist.transcript.metadata import CallMetadata

logger = logging.getLogger("receptionist")


def _build_sender(email_config: EmailConfig) -> EmailSender:
    if email_config.sender.type == "smtp":
        assert email_config.sender.smtp is not None
        return SMTPSender(email_config.sender.smtp)
    if email_config.sender.type == "resend":
        assert email_config.sender.resend is not None
        return ResendSender(email_config.sender.resend)
    raise ValueError(f"Unknown email sender type: {email_config.sender.type}")


class EmailChannel:
    def __init__(
        self,
        channel_config: EmailChannelConfig,
        email_config: EmailConfig,
        initial_delay: float = 1.0,
    ) -> None:
        self.channel_config = channel_config
        self.email_config = email_config
        self.sender: EmailSender = _build_sender(email_config)
        self.policy = RetryPolicy(max_attempts=3, initial_delay=initial_delay, factor=2.0)

    async def deliver(self, message: Message, context: DispatchContext) -> None:
        subject, body_text, body_html = build_message_email(message, context)
        await self._send_with_retry(subject, body_text, body_html)

    async def deliver_call_end(
        self, metadata: CallMetadata, context: DispatchContext
    ) -> None:
        subject, body_text, body_html = build_call_end_email(metadata, context)
        await self._send_with_retry(subject, body_text, body_html)

    async def _send_with_retry(self, subject: str, body_text: str, body_html: str) -> None:
        async def _send() -> None:
            await self.sender.send(
                from_=self.email_config.from_,
                to=self.channel_config.to,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
            )

        await retry_with_backoff(
            _send,
            self.policy,
            is_transient=lambda e: isinstance(e, EmailSendError) and e.transient,
        )
