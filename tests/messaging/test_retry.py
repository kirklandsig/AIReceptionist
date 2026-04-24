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
