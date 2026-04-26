# receptionist/booking/availability.py
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from receptionist.booking.models import SlotProposal
from receptionist.config import CalendarConfig, WeeklyHours


_SLOT_GRID_MINUTES = 15  # slots must align to 0, 15, 30, 45 past the hour
_MAX_SLOTS_RETURNED = 3


def find_slots(
    *,
    business_hours: WeeklyHours,
    business_timezone: str,
    calendar_config: CalendarConfig,
    preferred_dt: datetime,
    existing_busy: list[tuple[datetime, datetime]],
    earliest: datetime,
    latest: datetime,
    now: datetime,
) -> list[SlotProposal]:
    """Find available appointment slots near `preferred_dt`.

    Pure function — no I/O. Caller supplies the busy list (already fetched from
    Google) and the wall-clock constraints (earliest, latest, now). Returns up
    to 3 SlotProposals sorted by proximity to `preferred_dt`.
    """
    tz = ZoneInfo(business_timezone)
    duration = timedelta(minutes=calendar_config.appointment_duration_minutes)
    buffer_total = timedelta(minutes=calendar_config.buffer_minutes)
    placement = calendar_config.buffer_placement

    # Expand each existing busy interval by the configured buffer.
    # This is the inverse of "buffer around new bookings": equivalent to widening
    # existing bookings by the same amount, which is simpler to reason about.
    buffered_busy = [
        _apply_buffer(start, end, buffer_total, placement)
        for (start, end) in existing_busy
    ]

    # Enumerate candidate slots on the 15-minute grid within the window.
    candidates: list[SlotProposal] = []
    for candidate_start in _iter_grid_slots(earliest, latest, tz):
        candidate_end = candidate_start + duration

        # Must fit entirely within business hours on its day
        if not _fits_in_business_hours(candidate_start, candidate_end, business_hours, tz):
            continue

        # Must not overlap any buffered busy interval
        if any(_overlaps(candidate_start, candidate_end, bs, be) for (bs, be) in buffered_busy):
            continue

        candidates.append(SlotProposal(
            start_iso=candidate_start.isoformat(),
            end_iso=candidate_end.isoformat(),
        ))

    # Sort by proximity to preferred time, then take top N
    candidates.sort(key=lambda s: abs(
        (datetime.fromisoformat(s.start_iso) - preferred_dt).total_seconds()
    ))
    return candidates[:_MAX_SLOTS_RETURNED]


def _apply_buffer(
    start: datetime, end: datetime, buffer: timedelta, placement: str,
) -> tuple[datetime, datetime]:
    if placement == "before":
        return (start - buffer, end)
    if placement == "after":
        return (start, end + buffer)
    if placement == "both":
        half = buffer / 2
        return (start - half, end + half)
    raise ValueError(f"Unknown buffer_placement: {placement}")


def _iter_grid_slots(earliest: datetime, latest: datetime, tz: ZoneInfo):
    """Yield grid-aligned candidate start times in `tz` between earliest and latest.

    The grid is :00/:15/:30/:45. Start by rounding `earliest` UP to the next grid boundary.
    """
    # Convert to business timezone so the grid aligns with wall-clock minutes
    current = earliest.astimezone(tz)
    minute_mod = current.minute % _SLOT_GRID_MINUTES
    if minute_mod != 0 or current.second != 0 or current.microsecond != 0:
        current = current.replace(second=0, microsecond=0) + timedelta(
            minutes=_SLOT_GRID_MINUTES - minute_mod
        )

    step = timedelta(minutes=_SLOT_GRID_MINUTES)
    while current <= latest.astimezone(tz):
        yield current
        current = current + step


def _fits_in_business_hours(
    start: datetime, end: datetime, hours: WeeklyHours, tz: ZoneInfo,
) -> bool:
    """Check whether [start, end) fits entirely within the day's business hours."""
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)

    if local_start.date() != local_end.date():
        return False

    day_name = local_start.strftime("%A").lower()
    day_hours = getattr(hours, day_name, None)
    if day_hours is None:
        return False

    open_time = _parse_hhmm(day_hours.open)
    close_time = _parse_hhmm(day_hours.close)
    local_start_time = local_start.time().replace(second=0, microsecond=0)
    local_end_time = local_end.time().replace(second=0, microsecond=0)

    return open_time <= local_start_time and local_end_time <= close_time


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def _overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime,
) -> bool:
    """Standard half-open interval overlap check."""
    return a_start < b_end and b_start < a_end
