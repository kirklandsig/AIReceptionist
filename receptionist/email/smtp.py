# receptionist/email/smtp.py
from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Sequence

import aiosmtplib

from receptionist.config import SMTPConfig
from receptionist.email.sender import EmailAttachment, EmailSendError

logger = logging.getLogger("receptionist")


class SMTPSender:
    def __init__(self, config: SMTPConfig) -> None:
        self.config = config

    async def send(
        self,
        *,
        from_: str,
        to: Sequence[str],
        subject: str,
        body_text: str,
        body_html: str | None,
        attachments: Sequence[EmailAttachment] = (),
    ) -> None:
        msg = EmailMessage()
        msg["From"] = from_
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content(body_text)
        if body_html is not None:
            msg.add_alternative(body_html, subtype="html")
        for att in attachments:
            maintype, _, subtype = att.content_type.partition("/")
            subtype = subtype or "octet-stream"
            msg.add_attachment(
                att.content,
                maintype=maintype or "application",
                subtype=subtype,
                filename=att.filename,
            )

        try:
            await aiosmtplib.send(
                msg,
                hostname=self.config.host,
                port=self.config.port,
                username=self.config.username,
                password=self.config.password,
                start_tls=self.config.use_tls,
            )
        except aiosmtplib.SMTPAuthenticationError as e:
            raise EmailSendError(f"SMTP auth failed: {e}", transient=False) from e
        except aiosmtplib.SMTPConnectError as e:
            raise EmailSendError(f"SMTP connect failed: {e}", transient=True) from e
        except aiosmtplib.SMTPResponseException as e:
            raise EmailSendError(
                f"SMTP response {e.code}: {e.message}",
                transient=500 <= e.code < 600,
            ) from e
        except Exception as e:
            raise EmailSendError(f"SMTP send failed: {e}", transient=True) from e

        logger.info("SMTPSender sent to=%s subject=%r", list(to), subject)
