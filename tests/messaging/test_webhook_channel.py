# tests/messaging/test_webhook_channel.py
from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from receptionist.config import WebhookChannel as WebhookChannelConfig
from receptionist.messaging.channels.webhook import WebhookChannel
from receptionist.messaging.models import Message, DispatchContext


def _make_message() -> Message:
    return Message("Jane", "+15551112222", "Call me", "Acme")


@pytest.mark.asyncio
@respx.mock
async def test_webhook_posts_json_body():
    route = respx.post("https://example.com/hook").mock(return_value=Response(200))
    cfg = WebhookChannelConfig(type="webhook", url="https://example.com/hook", headers={})
    channel = WebhookChannel(cfg)
    await channel.deliver(_make_message(), DispatchContext())
    assert route.called
    payload = json.loads(route.calls.last.request.content)
    assert payload["message"]["caller_name"] == "Jane"


@pytest.mark.asyncio
@respx.mock
async def test_webhook_sends_custom_headers():
    route = respx.post("https://example.com").mock(return_value=Response(200))
    cfg = WebhookChannelConfig(type="webhook", url="https://example.com", headers={"X-Api-Key": "secret"})
    channel = WebhookChannel(cfg)
    await channel.deliver(_make_message(), DispatchContext())
    assert route.calls.last.request.headers["x-api-key"] == "secret"


@pytest.mark.asyncio
@respx.mock
async def test_webhook_4xx_is_permanent_no_retry():
    route = respx.post("https://example.com").mock(return_value=Response(400))
    cfg = WebhookChannelConfig(type="webhook", url="https://example.com", headers={})
    channel = WebhookChannel(cfg)
    with pytest.raises(Exception):
        await channel.deliver(_make_message(), DispatchContext())
    assert route.call_count == 1  # no retry


@pytest.mark.asyncio
@respx.mock
async def test_webhook_5xx_retries():
    route = respx.post("https://example.com").mock(
        side_effect=[Response(503), Response(503), Response(200)]
    )
    cfg = WebhookChannelConfig(type="webhook", url="https://example.com", headers={})
    channel = WebhookChannel(cfg, initial_delay=0.001)
    await channel.deliver(_make_message(), DispatchContext())
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_webhook_5xx_exhaustion_raises():
    route = respx.post("https://example.com").mock(return_value=Response(500))
    cfg = WebhookChannelConfig(type="webhook", url="https://example.com", headers={})
    channel = WebhookChannel(cfg, initial_delay=0.001)
    with pytest.raises(Exception):
        await channel.deliver(_make_message(), DispatchContext())
    assert route.call_count == 3
