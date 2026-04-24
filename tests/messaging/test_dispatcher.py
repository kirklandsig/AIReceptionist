# tests/messaging/test_dispatcher.py
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from receptionist.config import (
    BusinessConfig, FileChannel as FileChannelConfig,
    EmailChannel as EmailChannelConfig, WebhookChannel as WebhookChannelConfig,
)
from receptionist.messaging.models import Message, DispatchContext
from receptionist.messaging.dispatcher import Dispatcher


def _make_message() -> Message:
    return Message("Jane", "+15551112222", "Call me", "Acme")


async def _drain_pending_tasks() -> None:
    """Wait for all non-current tasks to complete. Replaces the sleep(0) pattern."""
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_dispatcher_file_only(tmp_path):
    channel_cfg = FileChannelConfig(type="file", file_path=str(tmp_path))
    dispatcher = Dispatcher(channels=[channel_cfg], business_name="Acme")
    await dispatcher.dispatch_message(_make_message(), DispatchContext())
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_dispatcher_awaits_file_fires_others_as_tasks(tmp_path, mocker):
    """File channel completes synchronously; email/webhook are scheduled as tasks."""
    file_cfg = FileChannelConfig(type="file", file_path=str(tmp_path))
    webhook_cfg = WebhookChannelConfig(type="webhook", url="https://example.com", headers={})

    webhook_deliver = AsyncMock()
    mocker.patch(
        "receptionist.messaging.channels.webhook.WebhookChannel.deliver",
        webhook_deliver,
    )

    dispatcher = Dispatcher(channels=[file_cfg, webhook_cfg], business_name="Acme")
    await dispatcher.dispatch_message(_make_message(), DispatchContext())

    # File channel fired synchronously
    assert len(list(tmp_path.glob("*.json"))) == 1

    # Webhook was scheduled as a background task; drain the loop deterministically
    await _drain_pending_tasks()
    webhook_deliver.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_file_failure_raises(tmp_path, mocker):
    """File channel failure propagates so take_message can tell LLM."""
    file_cfg = FileChannelConfig(type="file", file_path=str(tmp_path))
    mocker.patch(
        "receptionist.messaging.channels.file.FileChannel.deliver",
        AsyncMock(side_effect=OSError("disk full")),
    )
    dispatcher = Dispatcher(channels=[file_cfg], business_name="Acme")
    with pytest.raises(OSError, match="disk full"):
        await dispatcher.dispatch_message(_make_message(), DispatchContext())


@pytest.mark.asyncio
async def test_dispatcher_no_channels_is_noop():
    dispatcher = Dispatcher(channels=[], business_name="Acme")
    # Should not raise; should simply return.
    await dispatcher.dispatch_message(_make_message(), DispatchContext())


@pytest.mark.asyncio
async def test_dispatcher_sync_fallback_prefers_webhook_when_no_file(tmp_path, mocker):
    """When no file channel configured, dispatcher awaits webhook synchronously."""
    webhook_cfg = WebhookChannelConfig(type="webhook", url="https://example.com", headers={})
    call_order: list[str] = []

    async def sync_webhook_deliver(self, msg, ctx):
        call_order.append("webhook-done")

    mocker.patch(
        "receptionist.messaging.channels.webhook.WebhookChannel.deliver",
        sync_webhook_deliver,
    )

    dispatcher = Dispatcher(channels=[webhook_cfg], business_name="Acme")
    await dispatcher.dispatch_message(_make_message(), DispatchContext())
    assert call_order == ["webhook-done"]


@pytest.mark.asyncio
async def test_dispatcher_background_failure_writes_to_failures_dir(tmp_path, mocker):
    """Email/webhook failures in background write a record to .failures/."""
    file_cfg = FileChannelConfig(type="file", file_path=str(tmp_path))
    webhook_cfg = WebhookChannelConfig(type="webhook", url="https://example.com", headers={})
    mocker.patch(
        "receptionist.messaging.channels.webhook.WebhookChannel.deliver",
        AsyncMock(side_effect=RuntimeError("all retries exhausted")),
    )

    dispatcher = Dispatcher(channels=[file_cfg, webhook_cfg], business_name="Acme")
    await dispatcher.dispatch_message(_make_message(), DispatchContext())

    # Drain the scheduled background task(s) so the failure record is written
    await _drain_pending_tasks()

    failures = list((tmp_path / ".failures").glob("*.json"))
    assert len(failures) == 1
    record = json.loads(failures[0].read_text(encoding="utf-8"))
    assert record["channel"] == "webhook"
    assert "all retries exhausted" in str(record["attempts"])
