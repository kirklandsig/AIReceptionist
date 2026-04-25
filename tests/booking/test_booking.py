# tests/booking/test_booking.py
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.booking.booking import (
    SlotNoLongerAvailableError, book_appointment,
)
from receptionist.booking.models import BookingResult, SlotProposal


def _slot(start_iso="2026-04-28T14:00:00-04:00", end_iso="2026-04-28T14:30:00-04:00") -> SlotProposal:
    return SlotProposal(start_iso=start_iso, end_iso=end_iso)


@pytest.mark.asyncio
async def test_book_appointment_happy_path():
    fake_client = MagicMock()
    fake_client.free_busy = AsyncMock(return_value=[])  # slot still free
    fake_client.create_event = AsyncMock(return_value={
        "id": "evt-new-999",
        "htmlLink": "https://calendar.google.com/event?eid=xyz",
    })

    result = await book_appointment(
        slot=_slot(),
        caller_name="Jane Doe",
        callback_number="+15551112222",
        call_id="playground-ABC",
        time_zone="America/New_York",
        client=fake_client,
        notes=None,
    )

    assert isinstance(result, BookingResult)
    assert result.event_id == "evt-new-999"
    assert result.html_link == "https://calendar.google.com/event?eid=xyz"
    assert result.start_iso == "2026-04-28T14:00:00-04:00"
    assert result.end_iso == "2026-04-28T14:30:00-04:00"

    # Verify the event body
    call_kwargs = fake_client.create_event.call_args.kwargs
    assert call_kwargs["summary"] == "Appointment: Jane Doe"
    description = call_kwargs["description"]
    assert "UNVERIFIED" in description
    assert "Jane Doe" in description
    assert "+15551112222" in description
    assert "playground-ABC" in description


@pytest.mark.asyncio
async def test_book_appointment_includes_notes_when_given():
    fake_client = MagicMock()
    fake_client.free_busy = AsyncMock(return_value=[])
    fake_client.create_event = AsyncMock(return_value={
        "id": "e", "htmlLink": "u",
    })

    await book_appointment(
        slot=_slot(),
        caller_name="Jane",
        callback_number="+1",
        call_id="c",
        time_zone="UTC",
        client=fake_client,
        notes="Follow-up after last visit",
    )

    description = fake_client.create_event.call_args.kwargs["description"]
    assert "Follow-up after last visit" in description


@pytest.mark.asyncio
async def test_book_appointment_detects_race_slot_now_busy():
    """Between check_availability and book_appointment, someone else booked the slot."""
    fake_client = MagicMock()
    # free_busy now returns the slot as busy
    fake_client.free_busy = AsyncMock(return_value=[
        (
            datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc),
        ),
    ])
    fake_client.create_event = AsyncMock()  # should NOT be called

    with pytest.raises(SlotNoLongerAvailableError):
        await book_appointment(
            slot=_slot("2026-04-28T14:00:00+00:00", "2026-04-28T14:30:00+00:00"),
            caller_name="Jane",
            callback_number="+1",
            call_id="c",
            time_zone="UTC",
            client=fake_client,
            notes=None,
        )

    fake_client.create_event.assert_not_called()


@pytest.mark.asyncio
async def test_book_appointment_no_notes_field_says_none():
    fake_client = MagicMock()
    fake_client.free_busy = AsyncMock(return_value=[])
    fake_client.create_event = AsyncMock(return_value={"id": "e", "htmlLink": "u"})

    await book_appointment(
        slot=_slot(),
        caller_name="Jane",
        callback_number="+1",
        call_id="c",
        time_zone="UTC",
        client=fake_client,
        notes=None,
    )
    description = fake_client.create_event.call_args.kwargs["description"]
    assert "Notes: (none)" in description


@pytest.mark.asyncio
async def test_book_appointment_description_includes_booked_timestamp():
    """The event description records WHEN it was booked, for audit/debug."""
    fake_client = MagicMock()
    fake_client.free_busy = AsyncMock(return_value=[])
    fake_client.create_event = AsyncMock(return_value={"id": "e", "htmlLink": "u"})

    await book_appointment(
        slot=_slot(),
        caller_name="Jane",
        callback_number="+1",
        call_id="c",
        time_zone="UTC",
        client=fake_client,
        notes=None,
    )
    description = fake_client.create_event.call_args.kwargs["description"]
    assert "Booked:" in description
