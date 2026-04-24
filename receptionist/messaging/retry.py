# receptionist/messaging/retry.py
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger("receptionist")


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    initial_delay: float = 1.0
    factor: float = 2.0


async def retry_with_backoff(
    func: Callable[[], Awaitable[Any]],
    policy: RetryPolicy,
    is_transient: Callable[[Exception], bool] = lambda e: True,
    record_attempts: list[dict] | None = None,
) -> Any:
    """Run an async zero-arg callable with exponential backoff.

    Raises the last exception if all attempts fail or a permanent error is hit.
    """
    delay = policy.initial_delay
    last_exc: Exception | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await func()
        except Exception as e:
            last_exc = e
            if record_attempts is not None:
                record_attempts.append({
                    "attempt": attempt,
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                    "at": datetime.now(timezone.utc).isoformat(),
                })
            if not is_transient(e):
                logger.info("retry: permanent error on attempt %d: %s", attempt, e)
                raise
            if attempt == policy.max_attempts:
                logger.info("retry: exhausted %d attempts", attempt)
                raise
            logger.info("retry: attempt %d failed (%s), waiting %.2fs", attempt, e, delay)
            await asyncio.sleep(delay)
            delay *= policy.factor

    assert last_exc is not None  # unreachable
    raise last_exc
