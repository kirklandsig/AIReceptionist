# receptionist/booking/models.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SlotProposal:
    """A proposed time slot returned by availability.find_slots().

    start_iso / end_iso are RFC 3339 strings including timezone offset
    (e.g. "2026-04-28T14:00:00-04:00"). These are exactly what we hand to
    the LLM, hand back for booking validation, and send to Google as
    event.start.dateTime / end.dateTime.
    """

    start_iso: str
    end_iso: str


@dataclass
class BookingResult:
    """Returned by booking.book_appointment() after a successful event creation."""

    event_id: str
    start_iso: str
    end_iso: str
    html_link: str
