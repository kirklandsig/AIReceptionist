# receptionist/email/sender.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


class EmailSendError(Exception):
    """Raised by EmailSender implementations on failure.

    `transient=True` signals the caller should retry with backoff; False
    means retrying will not help (auth error, malformed address).
    """

    def __init__(self, message: str, transient: bool, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.retry_after = retry_after


class EmailSender(Protocol):
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
        ...
