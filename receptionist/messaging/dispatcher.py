# receptionist/messaging/dispatcher.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Sequence

from receptionist.config import (
    FileChannel as FileChannelConfig,
    EmailChannel as EmailChannelConfig,
    WebhookChannel as WebhookChannelConfig,
    EmailConfig,
)
from receptionist.messaging.channels.file import FileChannel
from receptionist.messaging.channels.webhook import WebhookChannel
from receptionist.messaging.channels.email import EmailChannel
from receptionist.messaging.failures import record_failure, resolve_failures_dir
from receptionist.messaging.models import Message, DispatchContext

logger = logging.getLogger("receptionist")

# Preference order when picking which channel to await synchronously (file > webhook > email)
_SYNC_PREFERENCE = (FileChannelConfig, WebhookChannelConfig, EmailChannelConfig)


class Dispatcher:
    """Fans out a Message to all configured channels.

    Awaits one channel synchronously (file > webhook > email preference) so
    a durable copy exists before the caller-facing tool returns. Remaining
    channels run as background tasks; on exhaustion their failures are
    written to .failures/.
    """

    def __init__(
        self,
        channels: Sequence,
        business_name: str,
        email_config: EmailConfig | None = None,
    ) -> None:
        self.channels = list(channels)
        self.business_name = business_name
        self.email_config = email_config
        self.failures_dir = resolve_failures_dir(self.channels, business_name)

    async def dispatch_message(self, message: Message, context: DispatchContext) -> None:
        if not self.channels:
            logger.info("Dispatcher has no channels; dispatch_message is a no-op")
            return

        sync_channel, background_channels = self._split_channels()

        # Sync channel: await, propagate errors to caller (take_message)
        sync_channel_name = sync_channel.type
        await self._get_channel(sync_channel).deliver(message, context)
        logger.info("Sync dispatch via %s succeeded", sync_channel_name)

        # Background channels: fire and forget
        for ch_cfg in background_channels:
            asyncio.create_task(self._run_background(ch_cfg, message, context))

    def _split_channels(self):
        """Pick one sync channel (file preferred), return the rest as background."""
        for cls in _SYNC_PREFERENCE:
            for ch in self.channels:
                if isinstance(ch, cls):
                    return ch, [c for c in self.channels if c is not ch]
        # Should be unreachable: all channel types are in _SYNC_PREFERENCE
        return self.channels[0], self.channels[1:]

    async def _run_background(self, ch_cfg, message: Message, context: DispatchContext) -> None:
        channel_name = ch_cfg.type
        channel = self._get_channel(ch_cfg)
        attempts: list[dict] = []
        try:
            await channel.deliver(message, context)
            logger.info("Background dispatch via %s succeeded", channel_name)
        except Exception as e:
            attempts.append({
                "attempt": 1,
                "error_type": type(e).__name__,
                "error_detail": str(e),
                "at": datetime.now(timezone.utc).isoformat(),
            })
            logger.error(
                "Background dispatch via %s failed: %s",
                channel_name, e,
                extra={"business_name": self.business_name, "component": f"messaging.channels.{channel_name}"},
            )
            await record_failure(self.failures_dir, channel_name, message, context, attempts)

    def _get_channel(self, ch_cfg):
        if isinstance(ch_cfg, FileChannelConfig):
            return FileChannel(ch_cfg)
        if isinstance(ch_cfg, WebhookChannelConfig):
            return WebhookChannel(ch_cfg)
        if isinstance(ch_cfg, EmailChannelConfig):
            if self.email_config is None:
                raise ValueError("EmailChannel configured but no EmailConfig provided to Dispatcher")
            return EmailChannel(ch_cfg, self.email_config)
        raise ValueError(f"Unknown channel config type: {type(ch_cfg).__name__}")
