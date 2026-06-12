# tests/test_lifecycle.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.config import BusinessConfig
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


def test_lifecycle_set_caller_phone_when_missing(config):
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone=None)
    lifecycle.set_caller_phone("+15551112222")
    assert lifecycle.metadata.caller_phone == "+15551112222"


def test_lifecycle_set_caller_phone_does_not_overwrite_existing(config):
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone="+15550000000")
    lifecycle.set_caller_phone("+15551112222")
    assert lifecycle.metadata.caller_phone == "+15550000000"


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


def test_lifecycle_record_agent_ended_adds_outcome_and_reason(config):
    """Issue #10: the agent-initiated hangup records the outcome AND the
    short reason label so call summaries can show 'why' the agent ended."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_agent_ended("caller_goodbye")
    assert "agent_ended" in lifecycle.metadata.outcomes
    assert lifecycle.metadata.agent_end_reason == "caller_goodbye"


def test_lifecycle_record_agent_ended_first_reason_wins(config):
    """If silence-timeout fires after the goodbye path has already started,
    the first reason wins so the most actionable signal survives."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_agent_ended("caller_goodbye")
    lifecycle.record_agent_ended("silence_timeout")
    assert lifecycle.metadata.agent_end_reason == "caller_goodbye"
    # Outcome stays a single-membership flag regardless of how many times fired
    assert lifecycle.metadata.outcomes == {"agent_ended"}


def test_lifecycle_records_info_packet_success(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_info_packet_sent(
        packet_key="firm_overview",
        packet_display_name="Firm Overview",
        channel="email",
        destination="claimant@example.com",
    )
    record = lifecycle.metadata.info_packet_sends[0]
    assert record.status == "sent"
    assert record.packet_key == "firm_overview"


def test_lifecycle_records_info_packet_failure(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_info_packet_failed(
        packet_key="firm_overview",
        packet_display_name="Firm Overview",
        channel="email",
        destination="claimant@example.com",
        error="transport_failed",
    )
    record = lifecycle.metadata.info_packet_sends[0]
    assert record.status == "failed"
    assert record.error == "transport_failed"


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


@pytest.mark.asyncio
async def test_lifecycle_queues_message_email_and_fires_at_call_end(
    tmp_path, config, mocker,
):
    """The take_message tool defers the email portion to call-end by
    enqueueing on the lifecycle. At on_call_ended, the lifecycle fires the
    queued message email(s) AFTER the transcript file has been written, so
    the email's DispatchContext carries the real transcript path and the
    template can embed the full conversation."""
    from receptionist.config import (
        EmailChannel as EmailChannelConfig, EmailConfig, EmailTriggers,
        SMTPConfig, EmailSenderConfig, TranscriptsConfig, TranscriptStorageConfig,
    )
    from receptionist.messaging.models import Message
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel

    config = config.model_copy(update={
        "messages": config.messages.model_copy(update={
            "channels": [
                *config.messages.channels,
                EmailChannelConfig(
                    type="email", to=["owner@acme.com"], include_transcript=True,
                ),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {"host": "h", "port": 587, "username": "u", "password": "p", "use_tls": True},
            },
            "triggers": {"on_message": True, "on_call_end": False},
        }),
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path)),
            formats=["json", "markdown"],
        ),
    })

    deliver_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver", deliver_mock)

    lifecycle = CallLifecycle(config=config, call_id="room-x", caller_phone="+15551112222")
    msg = Message("Jane", "+15551112222", "Tell Alex I called", "Test Dental")

    # Mid-call: take_message tool enqueues the email instead of firing it
    lifecycle.enqueue_message_email(msg)
    deliver_mock.assert_not_called()  # not yet — call still in progress

    # Call ends: transcript gets written, then queued message emails fire
    await lifecycle.on_call_ended()

    deliver_mock.assert_called_once()
    fired_msg, fired_ctx = deliver_mock.call_args.args
    assert fired_msg is msg
    # The context passed to deliver carries the transcript path so the
    # template can read it and embed the conversation.
    assert fired_ctx.transcript_markdown_path is not None
    assert fired_ctx.transcript_markdown_path.endswith(".md")
    assert lifecycle._pending_message_emails == []


@pytest.mark.asyncio
async def test_on_call_ended_passes_pending_messages_to_call_end_email(v2_yaml, mocker):
    from receptionist.config import (
        BusinessConfig, EmailChannel as EmailChannelConfig, EmailConfig,
        EmailSenderConfig, EmailTriggers, SMTPConfig,
    )
    from receptionist.messaging.channels.email import EmailChannel
    from receptionist.messaging.models import Message

    base = BusinessConfig.from_yaml_string(v2_yaml)
    config = base.model_copy(update={
        "messages": base.messages.model_copy(update={
            "channels": [
                *base.messages.channels,
                EmailChannelConfig(type="email", to=["owner@example.com"]),
            ],
        }),
        "email": EmailConfig(
            **{"from": "ai@example.com"},
            sender=EmailSenderConfig(
                type="smtp",
                smtp=SMTPConfig(host="h", port=587, username="u", password="p", use_tls=True),
            ),
            triggers=EmailTriggers(on_message=False, on_call_end=True, on_booking=False),
        ),
    })
    deliver_call_end = mocker.patch.object(EmailChannel, "deliver_call_end", autospec=True)
    mocker.patch("receptionist.lifecycle.generate_call_summary", AsyncMock(return_value=None))
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone="+15551112222")
    msg = Message("Jane Doe", "+15551112222", "Please call me back.", config.business.name)
    lifecycle.enqueue_message_email(msg)

    await lifecycle.on_call_ended()

    assert deliver_call_end.called
    kwargs = deliver_call_end.call_args.kwargs
    assert kwargs["captured_messages"] == [msg]
    assert lifecycle._pending_message_emails == []


@pytest.mark.asyncio
async def test_lifecycle_transcript_failure_still_fires_deferred_message_email(
    tmp_path, config, mocker,
):
    from receptionist.config import (
        EmailChannel as EmailChannelConfig, EmailConfig,
        TranscriptsConfig, TranscriptStorageConfig,
    )
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.messaging.models import Message

    config = config.model_copy(update={
        "messages": config.messages.model_copy(update={
            "channels": [
                *config.messages.channels,
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {"host": "h", "port": 587, "username": "u", "password": "p", "use_tls": True},
            },
            "triggers": {"on_message": True, "on_call_end": False},
        }),
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path)),
            formats=["json", "markdown"],
        ),
    })
    deliver_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver", deliver_mock)
    mocker.patch(
        "receptionist.lifecycle.write_transcript_files",
        AsyncMock(side_effect=OSError("cannot create transcript dir")),
    )

    lifecycle = CallLifecycle(config=config, call_id="room-x", caller_phone=None)
    msg = Message("Jane", "+15551112222", "Please call", "Test Dental")
    lifecycle.enqueue_message_email(msg)

    await lifecycle.on_call_ended()

    deliver_mock.assert_called_once()
    fired_msg, fired_ctx = deliver_mock.call_args.args
    assert fired_msg is msg
    assert fired_ctx.transcript_markdown_path is None
    assert lifecycle._pending_message_emails == []


@pytest.mark.asyncio
async def test_lifecycle_message_queue_empty_means_no_deferred_emails(config, mocker):
    """No message taken = no deferred message emails fired at call end."""
    from receptionist.config import (
        EmailChannel as EmailChannelConfig, EmailConfig, EmailTriggers,
        SMTPConfig, EmailSenderConfig,
    )
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel

    config = config.model_copy(update={
        "messages": config.messages.model_copy(update={
            "channels": [
                *config.messages.channels,
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {"host": "h", "port": 587, "username": "u", "password": "p", "use_tls": True},
            },
            # on_message must be True so the queue is even consulted; we want
            # to assert the queue is empty when no take_message ran.
            "triggers": {"on_message": True, "on_call_end": False},
        }),
    })

    deliver_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver", deliver_mock)

    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    await lifecycle.on_call_ended()
    deliver_mock.assert_not_called()


@pytest.mark.asyncio
async def test_on_call_ended_is_idempotent(tmp_path, config, mocker):
    """on_call_ended must be safe to call more than once. The agent-initiated
    end-of-call path calls it explicitly BEFORE removing the SIP participant
    so emails fire while the asyncio executor is still healthy; the natural
    session-close handler later calls it again. The second invocation must
    be a no-op (no duplicate emails, no double transcript writes), or we'd
    deliver two copies of every email to the operator.

    With on_call_end=True the lifecycle runs in consolidated mode: the
    separate message email is suppressed (the call-end email carries the
    message), so `deliver` must never fire — only `deliver_call_end`, once."""
    from receptionist.config import (
        EmailChannel as EmailChannelConfig, EmailConfig, EmailTriggers,
        SMTPConfig, EmailSenderConfig, TranscriptsConfig, TranscriptStorageConfig,
    )
    from receptionist.messaging.models import Message
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel

    config = config.model_copy(update={
        "messages": config.messages.model_copy(update={
            "channels": [
                *config.messages.channels,
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {"host": "h", "port": 587, "username": "u", "password": "p", "use_tls": True},
            },
            "triggers": {"on_message": True, "on_call_end": True},
        }),
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path)),
            formats=["json", "markdown"],
        ),
    })

    deliver_mock = AsyncMock()
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver", deliver_mock)
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    summary_mock = AsyncMock(return_value=None)
    mocker.patch("receptionist.lifecycle.generate_call_summary", summary_mock)

    lifecycle = CallLifecycle(config=config, call_id="room-x", caller_phone="+15551112222")
    lifecycle.enqueue_message_email(Message("Jane", "+15551112222", "msg", "Test Dental"))

    # First call: full pipeline runs, ONE consolidated call-end email fires.
    await lifecycle.on_call_ended()
    assert deliver_mock.call_count == 0  # consolidated: no separate message email
    assert deliver_call_end_mock.call_count == 1
    transcripts_after_first = len(list(tmp_path.glob("*.md")))
    assert transcripts_after_first == 1

    # Second call (e.g. from session-close handler after agent-initiated end):
    # must NOT fire emails or rewrite transcripts.
    await lifecycle.on_call_ended()
    assert deliver_mock.call_count == 0, "consolidated: no separate message email"
    assert deliver_call_end_mock.call_count == 1, "duplicate call-end email after idempotent re-call"
    assert len(list(tmp_path.glob("*.md"))) == transcripts_after_first, \
        "transcript file count changed after idempotent re-call"
    summary_mock.assert_called_once()


def test_record_dtmf_event_appends_with_pending_status(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)

    lifecycle.record_dtmf_event(
        digit="1", action="transfer", target="Front Desk", status="pending",
    )
    events = lifecycle.metadata.dtmf_events
    assert len(events) == 1
    assert events[0].digit == "1"
    assert events[0].status == "pending"


def test_update_dtmf_event_status_changes_status_and_error(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)

    eid = lifecycle.record_dtmf_event(
        digit="2", action="transfer", target="Billing", status="pending",
    )
    lifecycle.update_dtmf_event_status(eid, status="failed", error="sip_api_failed")

    rec = lifecycle.metadata.dtmf_events[0]
    assert rec.status == "failed"
    assert rec.error == "sip_api_failed"


def test_record_dtmf_event_handles_unmapped_with_no_action_or_target(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)

    lifecycle.record_dtmf_event(
        digit="5", action=None, target=None, status="unmapped",
    )
    rec = lifecycle.metadata.dtmf_events[0]
    assert rec.digit == "5"
    assert rec.action is None
    assert rec.target is None
    assert rec.status == "unmapped"


def test_update_dtmf_event_status_logs_warning_on_invalid_event_id(v2_yaml, caplog):
    """Stale or out-of-range event_id must not raise (a live call should not
    crash on a metrics-tracking miss) but must emit a warning so the silent
    failure is observable."""
    import logging

    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    lifecycle.record_dtmf_event(
        digit="1", action="transfer", target="Front Desk", status="pending",
    )
    events_before = list(lifecycle.metadata.dtmf_events)

    with caplog.at_level(logging.WARNING, logger="receptionist"):
        lifecycle.update_dtmf_event_status(999, status="executed")

    # The event list is unchanged: no append, no in-place mutation.
    assert lifecycle.metadata.dtmf_events == events_before
    assert any(
        "update_dtmf_event_status" in rec.message and "out of range" in rec.message
        for rec in caplog.records
    ), f"expected an out-of-range warning, got: {[r.message for r in caplog.records]}"


def test_record_dtmf_event_rejects_unknown_status(v2_yaml):
    """Status whitelist mirrors VALID_OUTCOMES: a typo must raise rather
    than land silently in transcripts."""
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)

    with pytest.raises(ValueError, match="sucess"):
        lifecycle.record_dtmf_event(
            digit="1", action="transfer", target="Front Desk", status="sucess",
        )


@pytest.mark.asyncio
async def test_lifecycle_message_queue_does_not_fire_when_on_message_disabled(
    config, mocker,
):
    """If a business has on_message=False, the lifecycle should NOT fire
    deferred message emails even if the queue has entries (defensive: the
    operator opted out of email notifications for caller messages)."""
    from receptionist.config import (
        EmailChannel as EmailChannelConfig, EmailConfig, EmailTriggers,
        SMTPConfig, EmailSenderConfig,
    )
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.messaging.models import Message

    config = config.model_copy(update={
        "messages": config.messages.model_copy(update={
            "channels": [
                *config.messages.channels,
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {"host": "h", "port": 587, "username": "u", "password": "p", "use_tls": True},
            },
            # on_call_end stays False so this exercises the LEGACY path's
            # on_message gate; with on_call_end=True the consolidated mode
            # would suppress `deliver` regardless of on_message.
            "triggers": {"on_message": False, "on_call_end": False},
        }),
    })

    deliver_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver", deliver_mock)

    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.enqueue_message_email(Message("Jane", "+1", "msg", "Test Dental"))
    await lifecycle.on_call_ended()
    deliver_mock.assert_not_called()


def _consolidated_config(config, tmp_path):
    from receptionist.config import (
        EmailChannel as EmailChannelConfig, EmailConfig,
        TranscriptsConfig, TranscriptStorageConfig,
    )
    return config.model_copy(update={
        "messages": config.messages.model_copy(update={
            "channels": [
                *config.messages.channels,
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {"host": "h", "port": 587, "username": "u", "password": "p", "use_tls": True},
            },
            "triggers": {"on_message": True, "on_call_end": True, "on_booking": True},
        }),
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path)),
            formats=["json", "markdown"],
        ),
    })


@pytest.mark.asyncio
async def test_consolidation_suppresses_separate_message_email(tmp_path, config, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.messaging.models import Message

    cfg = _consolidated_config(config, tmp_path)
    deliver_mock = AsyncMock()
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver", deliver_mock)
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    mocker.patch("receptionist.lifecycle.generate_call_summary", AsyncMock(return_value=None))

    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone="+15551112222")
    msg = Message("Jane", "+15551112222", "msg", "Test Dental")
    lifecycle.enqueue_message_email(msg)
    await lifecycle.on_call_ended()

    deliver_mock.assert_not_called()
    deliver_call_end_mock.assert_called_once()
    assert deliver_call_end_mock.call_args.kwargs["captured_messages"] == [msg]


@pytest.mark.asyncio
async def test_consolidation_suppresses_separate_intake_email(tmp_path, config, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.intakes.models import IntakeAnswer, IntakeSubmission

    cfg = _consolidated_config(config, tmp_path)
    deliver_intake_mock = AsyncMock()
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_intake", deliver_intake_mock)
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    mocker.patch("receptionist.lifecycle.generate_call_summary", AsyncMock(return_value=None))

    submission = IntakeSubmission(
        case_type="workers_comp", business_name="Test Dental", call_id="room-x",
        caller_name="Jane", callback_number="+13475550000",
        answers=[IntakeAnswer(question_key="k", prompt="P?", spoken_text="A")],
        status="final",
    )
    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone="+15551112222")
    lifecycle.enqueue_intake_submission(submission, case_type_display="Workers' Comp")
    await lifecycle.on_call_ended()

    deliver_intake_mock.assert_not_called()
    kwargs = deliver_call_end_mock.call_args.kwargs
    assert kwargs["intake_submission"] is submission
    assert kwargs["case_type_display"] == "Workers' Comp"
    assert lifecycle._pending_intake_submission is None


@pytest.mark.asyncio
async def test_consolidation_suppresses_separate_booking_email(tmp_path, config, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel

    cfg = _consolidated_config(config, tmp_path)
    deliver_booking_mock = AsyncMock()
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_booking", deliver_booking_mock)
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    mocker.patch("receptionist.lifecycle.generate_call_summary", AsyncMock(return_value=None))

    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone=None)
    lifecycle.record_appointment_booked({
        "event_id": "e", "start_iso": "2026-06-12T10:00:00-04:00",
        "end_iso": "2026-06-12T10:30:00-04:00", "html_link": "https://cal",
    })
    await lifecycle.on_call_ended()

    deliver_booking_mock.assert_not_called()
    deliver_call_end_mock.assert_called_once()


@pytest.mark.asyncio
async def test_consolidation_passes_ai_summary(tmp_path, config, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.messaging.models import Message

    cfg = _consolidated_config(config, tmp_path)
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    summary_mock = AsyncMock(return_value="Caller asked about hours.")
    mocker.patch("receptionist.lifecycle.generate_call_summary", summary_mock)

    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone=None)
    lifecycle.enqueue_message_email(Message("J", "+15551110000", "m", "Test Dental"))
    await lifecycle.on_call_ended()

    summary_mock.assert_called_once()
    assert deliver_call_end_mock.call_args.kwargs["ai_summary"] == "Caller asked about hours."


@pytest.mark.asyncio
async def test_consolidation_summary_failure_still_sends_email(tmp_path, config, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.messaging.models import Message

    cfg = _consolidated_config(config, tmp_path)
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    summary_mock = AsyncMock(side_effect=RuntimeError("unexpected"))
    mocker.patch("receptionist.lifecycle.generate_call_summary", summary_mock)

    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone=None)
    lifecycle.enqueue_message_email(Message("J", "+15551110000", "m", "Test Dental"))
    await lifecycle.on_call_ended()

    summary_mock.assert_called_once()
    deliver_call_end_mock.assert_called_once()
    assert deliver_call_end_mock.call_args.kwargs["ai_summary"] is None


@pytest.mark.asyncio
async def test_no_summary_generated_when_disabled(tmp_path, config, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.messaging.models import Message

    cfg = _consolidated_config(config, tmp_path)
    cfg = cfg.model_copy(update={
        "email": cfg.email.model_copy(update={
            "summary": cfg.email.summary.model_copy(update={"enabled": False}),
        }),
    })
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    summary_mock = AsyncMock(return_value="should not be called")
    mocker.patch("receptionist.lifecycle.generate_call_summary", summary_mock)

    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone=None)
    # Content present (so the empty-call gate passes) — the summary must
    # still be skipped because summary.enabled is False.
    lifecycle.enqueue_message_email(Message("J", "+15551110000", "m", "Test Dental"))
    await lifecycle.on_call_ended()

    summary_mock.assert_not_called()
    assert deliver_call_end_mock.call_args.kwargs["ai_summary"] is None


@pytest.mark.asyncio
async def test_legacy_path_unchanged_when_on_call_end_false(tmp_path, config, mocker):
    """on_call_end=False keeps the separate message email (existing tenants)."""
    # This is already covered by test_lifecycle_queues_message_email_and_fires_at_call_end;
    # add a summarizer assertion: it must NOT be called on the legacy path.
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.config import EmailChannel as EmailChannelConfig, EmailConfig
    from receptionist.messaging.models import Message

    cfg = config.model_copy(update={
        "messages": config.messages.model_copy(update={
            "channels": [
                *config.messages.channels,
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {"host": "h", "port": 587, "username": "u", "password": "p", "use_tls": True},
            },
            "triggers": {"on_message": True, "on_call_end": False},
        }),
    })
    deliver_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver", deliver_mock)
    summary_mock = AsyncMock(return_value="nope")
    mocker.patch("receptionist.lifecycle.generate_call_summary", summary_mock)

    lifecycle = CallLifecycle(config=cfg, call_id="r", caller_phone=None)
    lifecycle.enqueue_message_email(Message("J", "+1", "m", "Test Dental"))
    await lifecycle.on_call_ended()

    deliver_mock.assert_called_once()
    summary_mock.assert_not_called()


@pytest.mark.asyncio
async def test_consolidation_full_matrix_one_email_carries_everything(tmp_path, config, mocker):
    """Message + intake + booking on one call: every per-trigger email is
    suppressed and the single call-end email carries all three payloads."""
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.intakes.models import IntakeAnswer, IntakeSubmission
    from receptionist.messaging.models import Message

    cfg = _consolidated_config(config, tmp_path)
    deliver_mock = AsyncMock()
    deliver_intake_mock = AsyncMock()
    deliver_booking_mock = AsyncMock()
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver", deliver_mock)
    mocker.patch.object(RuntimeEmailChannel, "deliver_intake", deliver_intake_mock)
    mocker.patch.object(RuntimeEmailChannel, "deliver_booking", deliver_booking_mock)
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    mocker.patch("receptionist.lifecycle.generate_call_summary", AsyncMock(return_value="S."))

    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone="+15551112222")
    msg = Message("Jane", "+15551112222", "msg", "Test Dental")
    lifecycle.enqueue_message_email(msg)
    submission = IntakeSubmission(
        case_type="workers_comp", business_name="Test Dental", call_id="room-x",
        caller_name="Jane", callback_number="+13475550000",
        answers=[IntakeAnswer(question_key="k", prompt="P?", spoken_text="A")],
        status="final",
    )
    lifecycle.enqueue_intake_submission(submission, case_type_display="WC")
    lifecycle.record_appointment_booked({
        "event_id": "e", "start_iso": "2026-06-12T10:00:00-04:00",
        "end_iso": "2026-06-12T10:30:00-04:00", "html_link": "https://cal",
    })

    await lifecycle.on_call_ended()

    deliver_mock.assert_not_called()
    deliver_intake_mock.assert_not_called()
    deliver_booking_mock.assert_not_called()
    deliver_call_end_mock.assert_called_once()
    kwargs = deliver_call_end_mock.call_args.kwargs
    assert kwargs["captured_messages"] == [msg]
    assert kwargs["intake_submission"] is submission
    assert kwargs["ai_summary"] == "S."


@pytest.mark.asyncio
async def test_consolidation_multi_channel_generates_summary_once(tmp_path, config, mocker):
    """Two email channels = two call-end deliveries but exactly ONE summary
    generation (the LLM call is per-call, not per-channel)."""
    from receptionist.config import EmailChannel as EmailChannelConfig
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel
    from receptionist.messaging.models import Message

    cfg = _consolidated_config(config, tmp_path)
    cfg = cfg.model_copy(update={
        "messages": cfg.messages.model_copy(update={
            "channels": [
                *cfg.messages.channels,
                EmailChannelConfig(type="email", to=["second@acme.com"]),
            ],
        }),
    })
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    summary_mock = AsyncMock(return_value="Once.")
    mocker.patch("receptionist.lifecycle.generate_call_summary", summary_mock)

    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone=None)
    lifecycle.enqueue_message_email(Message("J", "+15551110000", "m", "Test Dental"))
    await lifecycle.on_call_ended()

    assert deliver_call_end_mock.call_count == 2
    summary_mock.assert_called_once()


@pytest.mark.asyncio
async def test_no_summary_for_empty_call(tmp_path, config, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel

    cfg = _consolidated_config(config, tmp_path)
    deliver_call_end_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_call_end", deliver_call_end_mock)
    summary_mock = AsyncMock(return_value="nope")
    mocker.patch("receptionist.lifecycle.generate_call_summary", summary_mock)

    lifecycle = CallLifecycle(config=cfg, call_id="room-x", caller_phone=None)
    await lifecycle.on_call_ended()

    summary_mock.assert_not_called()
    deliver_call_end_mock.assert_called_once()
    assert deliver_call_end_mock.call_args.kwargs["ai_summary"] is None
