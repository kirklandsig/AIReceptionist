# receptionist/messaging/channels/webhook.py
from __future__ import annotations

import logging

import httpx

from receptionist.config import WebhookChannel as WebhookChannelConfig
from receptionist.messaging.models import Message, DispatchContext

logger = logging.getLogger("receptionist")


class WebhookChannel:
    """POSTs message as JSON to a configured URL.

    This skeleton performs a single POST; full retry/backoff is added in Task 3.3.
    """

    def __init__(self, config: WebhookChannelConfig) -> None:
        self.config = config

    async def deliver(self, message: Message, context: DispatchContext) -> None:
        body = {"message": message.to_dict(), "context": context.to_dict()}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self.config.url, json=body, headers=self.config.headers)
        resp.raise_for_status()
        logger.info("WebhookChannel POST %s -> %d", self.config.url, resp.status_code)
