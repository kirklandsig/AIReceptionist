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


def test_lifecycle_record_transfer_adds_outcome(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_transfer("Front Desk")
    assert lifecycle.metadata.transfer_target == "Front Desk"
    assert "transferred" in lifecycle.metadata.outcomes


def test_lifecycle_record_message_taken_adds_outcome(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_message_taken()
    assert lifecycle.metadata.message_taken is True
    assert "message_taken" in lifecycle.metadata.outcomes


def test_lifecycle_record_appointment_booked_adds_outcome(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    details = {
        "event_id": "evt123",
        "start_iso": "2026-04-28T14:00:00-04:00",
        "end_iso": "2026-04-28T14:30:00-04:00",
        "html_link": "https://calendar.google.com/event?eid=abc",
    }
    lifecycle.record_appointment_booked(details)
    assert lifecycle.metadata.appointment_booked is True
    assert lifecycle.metadata.appointment_details == details
    assert "appointment_booked" in lifecycle.metadata.outcomes


def test_lifecycle_multi_outcome_transfer_and_booking(config):
    """A call can be both transferred AND book an appointment. Both outcomes recorded."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_transfer("Front Desk")
    lifecycle.record_appointment_booked({
        "event_id": "e", "start_iso": "t1", "end_iso": "t2", "html_link": "url",
    })
    assert lifecycle.metadata.outcomes == {"transferred", "appointment_booked"}


def test_lifecycle_add_outcome_rejects_unknown(config):
    """Regression: _add_outcome must raise on outcomes not in VALID_OUTCOMES."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    with pytest.raises(ValueError, match="Unknown outcome"):
        lifecycle._add_outcome("abducted_by_aliens")


def test_lifecycle_add_outcome_does_not_demote(config):
    """Set semantics: re-adding any outcome (including hung_up) is a no-op
    that does not 'demote' or remove anything already in outcomes."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_transfer("Front Desk")
    lifecycle._add_outcome("hung_up")  # add hung_up to a transferred call
    # transferred must still be present; sets don't displace
    assert "transferred" in lifecycle.metadata.outcomes
    assert "hung_up" in lifecycle.metadata.outcomes


def test_lifecycle_appointment_booked_bool_mirrors_outcomes(config):
    """Regression: when record_appointment_booked fires, both the bool flag
    and the outcomes set must agree. Prevents drift between the two
    sources of truth (mirror field vs. outcomes membership)."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_appointment_booked({
        "event_id": "e", "start_iso": "s", "end_iso": "x", "html_link": "u",
    })
    # Both signals must be true and consistent
    assert lifecycle.metadata.appointment_booked is True
    assert "appointment_booked" in lifecycle.metadata.outcomes
    assert lifecycle.metadata.appointment_booked == (
        "appointment_booked" in lifecycle.metadata.outcomes
    )


def test_outcomes_is_a_set_not_a_string(config):
    """Regression guard against reverting to the old priority-based single-outcome shape."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    assert isinstance(lifecycle.metadata.outcomes, set)
    # Must support multi-element population
    lifecycle.record_transfer("Front Desk")
    lifecycle.record_message_taken()
    assert len(lifecycle.metadata.outcomes) == 2


@pytest.mark.asyncio
async def test_lifecycle_on_call_ended_finalizes_metadata(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    await lifecycle.on_call_ended()
    assert lifecycle.metadata.end_ts is not None
    assert lifecycle.metadata.outcomes == {"hung_up"}
    assert lifecycle.metadata.duration_seconds is not None


def test_lifecycle_email_channels_constructed_once_at_init(config):
    """Performance regression: pre-build EmailChannel instances at __init__,
    not per-trigger fire. Without caching, each call_end + each booking
    fired a fresh constructor over the channel list."""
    from receptionist.config import (
        EmailChannel as EmailChannelConfig,
        EmailConfig, EmailTriggers, SMTPConfig, EmailSenderConfig,
    )
    cfg = config.model_copy(update={
        "messages": config.messages.model_copy(update={
            "channels": [
                *config.messages.channels,
                EmailChannelConfig(
                    type="email",
                    to=["a@example.com", "b@example.com"],
                    include_transcript=True,
                    include_recording_link=False,
                ),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {
                    "host": "smtp.example.com", "port": 587,
                    "username": "u", "password": "p", "use_tls": True,
                },
            },
            "triggers": {"on_message": False, "on_call_end": True},
        }),
    })
    lifecycle = CallLifecycle(config=cfg, call_id="r", caller_phone=None)
    # One email channel in messages.channels -> one cached EmailChannel instance.
    assert len(lifecycle._email_channels) == 1
    # Stored as a list, not rebuilt — identity holds across reads.
    assert lifecycle._email_channels is lifecycle._email_channels


def test_lifecycle_no_email_channels_when_email_disabled(config):
    """When the business has no email config, _email_channels is empty
    and the call-end fan-out is a no-op."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    assert lifecycle._email_channels == []


@pytest.mark.asyncio
async def test_lifecycle_on_call_ended_writes_transcript(tmp_path, config):
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
