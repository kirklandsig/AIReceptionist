# tests/messaging/test_retry.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from receptionist.messaging.retry import retry_with_backoff, RetryPolicy


@pytest.mark.asyncio
async def test_retry_succeeds_first_try():
    func = AsyncMock(return_value="ok")
    result = await retry_with_backoff(func, RetryPolicy(max_attempts=3, initial_delay=0.01, factor=2.0))
    assert result == "ok"
    assert func.call_count == 1


@pytest.mark.asyncio
async def test_retry_retries_on_transient_then_succeeds():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    result = await retry_with_backoff(
        flaky,
        RetryPolicy(max_attempts=3, initial_delay=0.001, factor=2.0),
        is_transient=lambda e: isinstance(e, ConnectionError),
    )
    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_retry_gives_up_after_max_attempts():
    func = AsyncMock(side_effect=ConnectionError("still bad"))
    with pytest.raises(ConnectionError):
        await retry_with_backoff(
            func,
            RetryPolicy(max_attempts=3, initial_delay=0.001, factor=2.0),
            is_transient=lambda e: True,
        )
    assert func.call_count == 3


@pytest.mark.asyncio
async def test_retry_does_not_retry_permanent():
    func = AsyncMock(side_effect=ValueError("permanent"))
    with pytest.raises(ValueError):
        await retry_with_backoff(
            func,
            RetryPolicy(max_attempts=3, initial_delay=0.001, factor=2.0),
            is_transient=lambda e: isinstance(e, ConnectionError),
        )
    assert func.call_count == 1


@pytest.mark.asyncio
async def test_retry_collects_attempt_records():
    func = AsyncMock(side_effect=ConnectionError("try again"))
    attempts: list[dict] = []
    with pytest.raises(ConnectionError):
        await retry_with_backoff(
            func,
            RetryPolicy(max_attempts=2, initial_delay=0.001, factor=2.0),
            is_transient=lambda e: True,
            record_attempts=attempts,
        )
    assert len(attempts) == 2
    assert attempts[0]["attempt"] == 1
    assert attempts[0]["error_type"] == "ConnectionError"


class _RateLimited(Exception):
    """Exception with a retry_after hint (e.g. 429 Retry-After)."""

    def __init__(self, msg: str, retry_after: float) -> None:
        super().__init__(msg)
        self.retry_after = retry_after


@pytest.mark.asyncio
async def test_retry_honors_retry_after_hint(mocker):
    """If the exception carries a retry_after, use it instead of the computed delay."""
    import asyncio as _asyncio
    sleeps: list[float] = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)

    mocker.patch.object(_asyncio, "sleep", _fake_sleep)

    func = AsyncMock(side_effect=[
        _RateLimited("slow down", retry_after=0.5),
        "ok",
    ])
    result = await retry_with_backoff(
        func,
        RetryPolicy(max_attempts=3, initial_delay=5.0, factor=2.0),
        is_transient=lambda e: True,
    )
    assert result == "ok"
    # Retry-after (0.5s) overrode the computed 5.0s delay
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_retry_clamps_retry_after_to_60s(mocker):
    """A misbehaving server cannot stall us longer than the clamp."""
    import asyncio as _asyncio
    sleeps: list[float] = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)

    mocker.patch.object(_asyncio, "sleep", _fake_sleep)

    func = AsyncMock(side_effect=[
        _RateLimited("go away", retry_after=999.0),
        "ok",
    ])
    await retry_with_backoff(
        func,
        RetryPolicy(max_attempts=3, initial_delay=1.0, factor=2.0),
        is_transient=lambda e: True,
    )
    assert sleeps == [60.0]
