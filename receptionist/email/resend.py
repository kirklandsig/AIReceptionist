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
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            raise EmailSendError("Resend rate limited", transient=True, retry_after=retry_after)
        if 400 <= resp.status_code < 500:
            raise EmailSendError(
                f"Resend rejected: {resp.status_code} {_resend_error_name(resp)}",
                transient=False,
            )
        if 500 <= resp.status_code < 600:
            raise EmailSendError(f"Resend server error: {resp.status_code}", transient=True)

        logger.info("ResendSender sent to=%s subject=%r", list(to), subject)


def _parse_retry_after(value: str | None) -> float:
    if value is None:
        return 1.0
    try:
        parsed = float(value)
    except ValueError:
        return 1.0
    return parsed if parsed > 0 else 1.0


def _resend_error_name(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return "error"
    if isinstance(data, dict):
        name = data.get("name") or data.get("error") or data.get("type")
        if isinstance(name, str) and name:
            return name
    return "error"
