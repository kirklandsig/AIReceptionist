# tests/test_lifecycle.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.lifecycle import CallLifecycle
from receptionist.transcript.metadata import CallMetadata


@pytest.fixture
def config(v2_yaml):
    from receptionist.config import BusinessConfig
    return BusinessConfig.from_yaml_string(v2_yaml)


def test_lifecycle_constructs_metadata_with_call_id(config):
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone="+15551112222")
    assert lifecycle.metadata.call_id == "room-abc"
    assert lifecycle.metadata.business_name == "Test Dental"
    assert lifecycle.metadata.caller_phone == "+15551112222"


def test_lifecycle_record_faq_populates_metadata(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_faq_answered("hours")
    lifecycle.record_faq_answered("insurance")
    assert lifecycle.metadata.faqs_answered == ["hours", "insurance"]


def test_lifecycle_record_transfer_sets_outcome(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_transfer("Front Desk")
    assert lifecycle.metadata.transfer_target == "Front Desk"
    assert lifecycle.metadata.outcome == "transferred"


def test_lifecycle_record_message_taken_sets_outcome(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_message_taken()
    assert lifecycle.metadata.message_taken is True
    assert lifecycle.metadata.outcome == "message_taken"


def test_lifecycle_transfer_overrides_message(config):
    """If both fire (edge case), transferred wins (higher priority outcome)."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_message_taken()
    lifecycle.record_transfer("Front Desk")
    assert lifecycle.metadata.outcome == "transferred"


def test_lifecycle_message_does_not_override_transfer(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_transfer("Front Desk")
    lifecycle.record_message_taken()
    assert lifecycle.metadata.outcome == "transferred"


@pytest.mark.asyncio
async def test_lifecycle_on_call_ended_finalizes_metadata(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    await lifecycle.on_call_ended()
    assert lifecycle.metadata.end_ts is not None
    assert lifecycle.metadata.outcome == "hung_up"  # no earlier event
    assert lifecycle.metadata.duration_seconds is not None


@pytest.mark.asyncio
async def test_lifecycle_on_call_ended_writes_transcript(tmp_path, config):
    # Override transcripts to enabled + point at tmp_path
    from receptionist.config import TranscriptsConfig, TranscriptStorageConfig
    config = config.model_copy(update={
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path)),
            formats=["json", "markdown"],
        ),
    })
    lifecycle = CallLifecycle(config=config, call_id="room-x", caller_phone=None)
    await lifecycle.on_call_ended()
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert len(list(tmp_path.glob("*.md"))) == 1
