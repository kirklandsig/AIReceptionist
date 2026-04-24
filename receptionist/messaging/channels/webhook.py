# receptionist/messaging/channels/webhook.py
from __future__ import annotations

import logging

import httpx

from receptionist.config import WebhookChannel as WebhookChannelConfig
from receptionist.messaging.models import Message, DispatchContext
from receptionist.messaging.retry import retry_with_backoff, RetryPolicy

logger = logging.getLogger("receptionist")


class _PermanentHTTPError(Exception):
    """4xx response — no retry."""


class WebhookChannel:
    """POSTs message + context to a configured URL with retry on 5xx/timeout."""

    def __init__(self, config: WebhookChannelConfig, initial_delay: float = 1.0) -> None:
        self.config = config
        self.policy = RetryPolicy(max_attempts=3, initial_delay=initial_delay, factor=2.0)

    async def deliver(self, message: Message, context: DispatchContext) -> None:
        body = {"message": message.to_dict(), "context": context.to_dict()}

        async def _post() -> None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.config.url, json=body, headers=self.config.headers)
            if 400 <= resp.status_code < 500:
                raise _PermanentHTTPError(f"HTTP {resp.status_code} from {self.config.url}")
            resp.raise_for_status()
            logger.info("WebhookChannel POST %s -> %d", self.config.url, resp.status_code)

        await retry_with_backoff(
            _post,
            self.policy,
            is_transient=lambda e: not isinstance(e, _PermanentHTTPError),
        )
