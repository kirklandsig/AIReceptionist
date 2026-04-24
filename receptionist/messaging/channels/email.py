# receptionist/messaging/channels/email.py
from __future__ import annotations

import logging

from receptionist.config import EmailChannel as EmailChannelConfig, EmailConfig
from receptionist.messaging.models import Message, DispatchContext

logger = logging.getLogger("receptionist")


class EmailChannel:
    """Message email channel. Full implementation in Phase 4."""

    def __init__(self, channel_config: EmailChannelConfig, email_config: EmailConfig) -> None:
        self.channel_config = channel_config
        self.email_config = email_config

    async def deliver(self, message: Message, context: DispatchContext) -> None:
        raise NotImplementedError("EmailChannel.deliver implemented in Phase 4")
