# tests/integration/test_booking_flow.py
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from receptionist.config import (
    BusinessConfig, CalendarConfig, DayHours,
    EmailChannel as EmailChannelConfig, EmailConfig, EmailSenderConfig,
    EmailTriggers, FileChannel as FileChannelConfig, ServiceAccountAuth,
    SMTPConfig, TranscriptsConfig, TranscriptStorageConfig, WeeklyHours,
)
from receptionist.lifecycle import CallLifecycle


def _full_config(tmp_path, v2_yaml) -> BusinessConfig:
    """Config with calendar enabled + on_booking trigger + email channel."""
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")

    base = BusinessConfig.from_yaml_string(v2_yaml)
    return base.model_copy(update={
        "hours": WeeklyHours(
            monday=DayHours(open="09:00", close="17:00"),
            tuesday=DayHours(open="09:00", close="17:00"),
            wednesday=DayHours(open="09:00", close="17:00"),
            thursday=DayHours(open="09:00", close="17:00"),
            friday=DayHours(open="09:00", close="17:00"),
            saturday=None, sunday=None,
        ),
        "messages": base.messages.model_copy(update={
            "channels": [
                FileChannelConfig(type="file", file_path=str(tmp_path / "messages")),
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig(
            **{"from": "noreply@acme.com"},
            sender=EmailSenderConfig(
                type="smtp",
                smtp=SMTPConfig(host="h", port=587, username="u", password="p", use_tls=True),
            ),
            triggers=EmailTriggers(on_message=True, on_call_end=False, on_booking=True),
        ),
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path / "transcripts")),
            formats=["json", "markdown"],
        ),
        "calendar": CalendarConfig(
            enabled=True,
            calendar_id="primary",
            auth=ServiceAccountAuth(type="service_account", service_account_file=str(sa_file)),
            appointment_duration_minutes=30,
            buffer_minutes=15,
            buffer_placement="after",
            booking_window_days=30,
            earliest_booking_hours_ahead=2,
        ),
    })


async def _drain_pending_tasks() -> None:
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_booking_flow_records_outcome_and_fires_on_booking_email(tmp_path, v2_yaml, mocker):
    """Full path: record_appointment_booked -> on_call_ended -> on_booking email."""
    config = _full_config(tmp_path, v2_yaml)

    smtp_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", smtp_send)

    lifecycle = CallLifecycle(config=config, call_id="room-xyz", caller_phone="+15551112222")

    # Simulate the book_appointment tool having run successfully
    lifecycle.record_appointment_booked({
        "event_id": "evt-integration-1",
        "start_iso": "2026-04-28T14:00:00-04:00",
        "end_iso": "2026-04-28T14:30:00-04:00",
        "html_link": "https://calendar.google.com/event?eid=abc",
    })

    await lifecycle.on_call_ended()
    await _drain_pending_tasks()

    # Metadata records the booking
    assert lifecycle.metadata.appointment_booked is True
    assert "appointment_booked" in lifecycle.metadata.outcomes
    assert lifecycle.metadata.appointment_details["event_id"] == "evt-integration-1"

    # Booking email fired
    smtp_send.assert_called()
    booking_calls = [
        c for c in smtp_send.call_args_list
        if "appointment" in c.kwargs.get("subject", "").lower()
    ]
    assert len(booking_calls) >= 1
    body_text = booking_calls[0].kwargs["body_text"]
    assert "calendar.google.com" in body_text
    assert "was NOT verified" in body_text


@pytest.mark.asyncio
async def test_multi_outcome_transferred_and_booked(tmp_path, v2_yaml):
    """A call that both transfers AND books an appointment records both outcomes."""
    config = _full_config(tmp_path, v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)

    lifecycle.record_transfer("Front Desk")
    lifecycle.record_appointment_booked({
        "event_id": "e", "start_iso": "s", "end_iso": "e2", "html_link": "l",
    })

    await lifecycle.on_call_ended()

    assert lifecycle.metadata.outcomes == {"transferred", "appointment_booked"}


@pytest.mark.asyncio
async def test_on_booking_trigger_does_not_fire_when_no_booking(tmp_path, v2_yaml, mocker):
    """on_booking trigger is guarded by metadata.appointment_booked — no booking, no email."""
    config = _full_config(tmp_path, v2_yaml)
    smtp_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", smtp_send)

    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    # No record_appointment_booked — just a hang-up call
    await lifecycle.on_call_ended()
    await _drain_pending_tasks()

    booking_calls = [
        c for c in smtp_send.call_args_list
        if "appointment" in c.kwargs.get("subject", "").lower()
    ]
    assert len(booking_calls) == 0


@pytest.mark.asyncio
async def test_disabled_calendar_skips_calendar_block_in_prompt(tmp_path, v2_yaml):
    """Regression check: disabling calendar removes the CALENDAR prompt section."""
    from receptionist.prompts import build_system_prompt
    config_enabled = _full_config(tmp_path, v2_yaml)
    config_disabled = config_enabled.model_copy(update={
        "calendar": config_enabled.calendar.model_copy(update={"enabled": False}),
    })
    assert "CALENDAR" in build_system_prompt(config_enabled)
    assert "CALENDAR" not in build_system_prompt(config_disabled)
