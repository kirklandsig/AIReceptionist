# tests/test_receptionist_on_enter.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.agent import Receptionist
from receptionist.config import (
    BusinessConfig, ConsentPreambleConfig, LocalStorageConfig,
    RecordingConfig, RecordingStorageConfig,
)
from receptionist.lifecycle import CallLifecycle


def _with_recording(config: BusinessConfig, tmp_path, preamble_enabled: bool) -> BusinessConfig:
    return config.model_copy(update={
        "recording": RecordingConfig(
            enabled=True,
            storage=RecordingStorageConfig(
                type="local", local=LocalStorageConfig(path=str(tmp_path)),
            ),
            consent_preamble=ConsentPreambleConfig(
                enabled=preamble_enabled,
                text="This call may be recorded for quality purposes.",
            ),
        ),
    })


@pytest.fixture
def patched_session(monkeypatch):
    """Patch Agent.session (read-only property) to return a mock at the class level.

    Agent.session is `@property` with no setter; we cannot set it per-instance.
    Replacing it with a new property at the class level gives every instance
    the same mock_session for the duration of the test.
    """
    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()
    from livekit.agents import Agent
    monkeypatch.setattr(Agent, "session", property(lambda self: mock_session))
    return mock_session


@pytest.mark.asyncio
async def test_on_enter_speaks_preamble_before_greeting(v2_yaml, tmp_path, patched_session):
    config = _with_recording(BusinessConfig.from_yaml_string(v2_yaml), tmp_path, True)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)

    calls: list[str] = []

    async def _record(**kwargs) -> None:
        calls.append(kwargs.get("instructions", ""))

    patched_session.generate_reply = AsyncMock(side_effect=_record)

    receptionist = Receptionist(config, lifecycle)
    await receptionist.on_enter()

    # Preamble must be the FIRST instruction
    assert len(calls) == 2
    assert "recorded for quality purposes" in calls[0]
    assert config.greeting in calls[1]


@pytest.mark.asyncio
async def test_on_enter_skips_preamble_when_recording_disabled(v2_yaml, tmp_path, patched_session):
    # Recording not configured at all
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)

    receptionist = Receptionist(config, lifecycle)
    await receptionist.on_enter()

    # Only greeting, no preamble
    assert patched_session.generate_reply.call_count == 1
    kwargs = patched_session.generate_reply.call_args.kwargs
    assert config.greeting in kwargs["instructions"]


@pytest.mark.asyncio
async def test_on_enter_skips_preamble_when_preamble_disabled(v2_yaml, tmp_path, patched_session):
    """Recording enabled but consent_preamble.enabled=False → no preamble spoken."""
    config = _with_recording(BusinessConfig.from_yaml_string(v2_yaml), tmp_path, False)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)

    receptionist = Receptionist(config, lifecycle)
    await receptionist.on_enter()

    assert patched_session.generate_reply.call_count == 1
