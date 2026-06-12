# receptionist/messaging/channels/email.py
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from receptionist.config import EmailChannel as EmailChannelConfig, EmailConfig
from receptionist.email.sender import EmailAttachment, EmailSendError, EmailSender
from receptionist.email.smtp import SMTPSender
from receptionist.email.resend import ResendSender
from receptionist.email.templates import (
    build_booking_email,
    build_call_end_email,
    build_intake_email,
    build_message_email,
    transcript_filename,
)
from receptionist.intakes.models import IntakeSubmission
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
        subject, body_text, body_html = build_message_email(
            message,
            context,
            include_transcript=self.channel_config.include_transcript,
            include_recording_link=self.channel_config.include_recording_link,
        )
        await self._send_with_retry(subject, body_text, body_html, await self._transcript_attachments(context))

    async def deliver_call_end(
        self,
        metadata: CallMetadata,
        context: DispatchContext,
        *,
        captured_messages: list[Message] | tuple[Message, ...] | None = None,
    ) -> None:
        subject, body_text, body_html = build_call_end_email(
            metadata,
            context,
            captured_messages=captured_messages,
            include_transcript=self.channel_config.include_transcript,
            include_recording_link=self.channel_config.include_recording_link,
        )
        await self._send_with_retry(subject, body_text, body_html, await self._transcript_attachments(context))

    async def deliver_booking(
        self, metadata: CallMetadata, context: DispatchContext
    ) -> None:
        subject, body_text, body_html = build_booking_email(metadata, context)
        await self._send_with_retry(subject, body_text, body_html, await self._transcript_attachments(context))

    async def deliver_intake(
        self,
        submission: IntakeSubmission,
        context: DispatchContext,
        *,
        case_type_display: str | None = None,
    ) -> None:
        subject, body_text, body_html = build_intake_email(
            submission,
            context,
            case_type_display=case_type_display,
            include_transcript=self.channel_config.include_transcript,
            include_recording_link=self.channel_config.include_recording_link,
        )
        await self._send_with_retry(subject, body_text, body_html, await self._transcript_attachments(context))

    async def _transcript_attachments(self, context: DispatchContext) -> list[EmailAttachment]:
        """Read the markdown transcript and wrap it as a .txt attachment.

        Returns [] when the channel disables transcripts, no transcript was
        written, or the file is unreadable — the email must still send.
        """
        if not self.channel_config.include_transcript or not context.transcript_markdown_path:
            return []
        try:
            content = await asyncio.to_thread(Path(context.transcript_markdown_path).read_bytes)
        except OSError:
            logger.warning(
                "transcript attachment unavailable: %s",
                context.transcript_markdown_path,
                extra={"component": "email.attachment"},
            )
            return []
        return [EmailAttachment(
            filename=transcript_filename(context.call_id),
            content=content,
            content_type="text/plain",
        )]

    async def _send_with_retry(
        self, subject: str, body_text: str, body_html: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        async def _send() -> None:
            await self.sender.send(
                from_=self.email_config.from_,
                to=self.channel_config.to,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                attachments=attachments or [],
            )

        await retry_with_backoff(
            _send,
            self.policy,
            is_transient=lambda e: isinstance(e, EmailSendError) and e.transient,
        )
