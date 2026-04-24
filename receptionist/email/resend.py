# receptionist/email/resend.py
from __future__ import annotations

import base64
import logging
from typing import Sequence

import httpx

from receptionist.config import ResendConfig
from receptionist.email.sender import EmailAttachment, EmailSendError

logger = logging.getLogger("receptionist")

_API_URL = "https://api.resend.com/emails"


class ResendSender:
    def __init__(self, config: ResendConfig) -> None:
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
        body: dict = {
            "from": from_,
            "to": list(to),
            "subject": subject,
            "text": body_text,
        }
        if body_html is not None:
            body["html"] = body_html
        if attachments:
            body["attachments"] = [
                {
                    "filename": a.filename,
                    "content": base64.b64encode(a.content).decode("ascii"),
                }
                for a in attachments
            ]

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(_API_URL, json=body, headers=headers)
        except httpx.RequestError as e:
            raise EmailSendError(f"Resend request error: {e}", transient=True) from e

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            raise EmailSendError("Resend rate limited", transient=True, retry_after=retry_after)
        if 400 <= resp.status_code < 500:
            raise EmailSendError(
                f"Resend rejected: {resp.status_code} {resp.text[:200]}",
                transient=False,
            )
        if 500 <= resp.status_code < 600:
            raise EmailSendError(f"Resend server error: {resp.status_code}", transient=True)

        logger.info("ResendSender sent to=%s subject=%r", list(to), subject)
