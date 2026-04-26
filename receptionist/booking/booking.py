# receptionist/booking/booking.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from receptionist.booking.client import GoogleCalendarClient
from receptionist.booking.models import BookingResult, SlotProposal

logger = logging.getLogger("receptionist")


class SlotNoLongerAvailableError(Exception):
    """Raised when the proposed slot was free at check_availability time but is now busy.

    The caller (tool handler) should catch this, run availability again, and
    offer the caller new alternatives.
    """


async def book_appointment(
    *,
    slot: SlotProposal,
    caller_name: str,
    callback_number: str,
    call_id: str,
    time_zone: str,
    client: GoogleCalendarClient,
    notes: str | None,
    caller_email: str | None = None,
) -> BookingResult:
    """Book the given slot on the calendar.

    Performs a last-second free/busy check for the exact slot to detect races
    between check_availability and this call. On race, raises
    SlotNoLongerAvailableError; the tool handler turns that into an LLM-facing
    message offering alternatives.

    When caller_email is given, the caller is added as an OPTIONAL attendee
    and Google sends them the standard calendar invitation. Optional attendees
    do not affect the organizer's free/busy if they decline.
    """
    start = datetime.fromisoformat(slot.start_iso)
    end = datetime.fromisoformat(slot.end_iso)

    # Race detection: re-query free/busy for JUST this slot
    busy_now = await client.free_busy(start, end)
    if busy_now:
        logger.info(
            "Slot taken between check_availability and book_appointment: %s",
            slot.start_iso,
            extra={"call_id": call_id, "component": "booking.booking"},
        )
        raise SlotNoLongerAvailableError(slot.start_iso)

    # Build the event description. UNVERIFIED tag is permanent and intentional —
    # staff viewing the event need to see that the AI took this booking without
    # identity verification.
    booked_at = datetime.now(timezone.utc).isoformat()
    description_lines = [
        "[via AI receptionist / UNVERIFIED]",
        f"Caller: {caller_name}",
        f"Callback: {callback_number}",
        f"Email: {caller_email or '(none)'}",
        f"Booked: {booked_at}",
        f"Call ID: {call_id}",
        f"Notes: {notes or '(none)'}",
    ]
    description = "\n".join(description_lines)

    summary = f"Appointment: {caller_name}"

    result = await client.create_event(
        start=start,
        end=end,
        summary=summary,
        description=description,
        time_zone=time_zone,
        attendee_email=caller_email,
    )

    logger.info(
        "Appointment booked: event_id=%s for %s at %s",
        result["id"], caller_name, slot.start_iso,
        extra={"call_id": call_id, "component": "booking.booking"},
    )

    return BookingResult(
        event_id=result["id"],
        start_iso=slot.start_iso,
        end_iso=slot.end_iso,
        html_link=result["htmlLink"],
    )
