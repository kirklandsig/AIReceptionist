# tests/booking/test_availability.py
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from receptionist.booking.availability import find_slots
from receptionist.booking.models import SlotProposal
from receptionist.config import (
    CalendarConfig, DayHours, ServiceAccountAuth, WeeklyHours,
)


NY = ZoneInfo("America/New_York")


def _cal_cfg(
    duration=30, buffer=15, placement="after",
    window_days=30, earliest_hours=2,
) -> CalendarConfig:
    return CalendarConfig(
        enabled=False,  # disable file-existence check
        calendar_id="primary",
        auth=ServiceAccountAuth(type="service_account", service_account_file="/tmp/fake.json"),
        appointment_duration_minutes=duration,
        buffer_minutes=buffer,
        buffer_placement=placement,
        booking_window_days=window_days,
        earliest_booking_hours_ahead=earliest_hours,
    )


def _weekly_9_to_5() -> WeeklyHours:
    """Mon-Fri 9-5, weekends closed."""
    return WeeklyHours(
        monday=DayHours(open="09:00", close="17:00"),
        tuesday=DayHours(open="09:00", close="17:00"),
        wednesday=DayHours(open="09:00", close="17:00"),
        thursday=DayHours(open="09:00", close="17:00"),
        friday=DayHours(open="09:00", close="17:00"),
        saturday=None,
        sunday=None,
    )


def test_finds_slots_in_business_hours_no_existing_busy():
    """Simple case: empty calendar, Monday morning, caller wants 10am."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)  # Mon 8am NY
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)  # Mon 10am
    earliest = now + timedelta(hours=2)  # 10am
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    assert len(slots) >= 1
    first_start = datetime.fromisoformat(slots[0].start_iso)
    assert first_start.hour in (10,)
    assert first_start.minute == 0


def test_slots_respect_business_hours_closed_day():
    """Saturday requested — business closed — should skip to Monday."""
    now = datetime(2026, 4, 24, 8, 0, tzinfo=NY)  # Fri 8am
    preferred = datetime(2026, 4, 25, 10, 0, tzinfo=NY)  # Sat 10am
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        assert dt.weekday() < 5, f"Slot {slot.start_iso} falls on weekend"


def test_slots_avoid_existing_busy_with_after_buffer():
    """Existing 10:00-10:30 with buffer=15 after: next slot must start >= 10:45."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    existing_busy = [
        (datetime(2026, 4, 27, 10, 0, tzinfo=NY), datetime(2026, 4, 27, 10, 30, tzinfo=NY)),
    ]

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(buffer=15, placement="after"),
        preferred_dt=preferred,
        existing_busy=existing_busy,
        earliest=earliest,
        latest=latest,
        now=now,
    )

    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        if dt.date() == datetime(2026, 4, 27).date():
            assert not (
                datetime(2026, 4, 27, 10, 0, tzinfo=NY)
                <= dt
                < datetime(2026, 4, 27, 10, 45, tzinfo=NY)
            ), f"Slot {slot.start_iso} overlaps busy or buffer"


def test_slots_avoid_existing_busy_with_before_buffer():
    """Existing 11:00-11:30 with buffer=15 before: no slot should end >= 10:45."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    existing_busy = [
        (datetime(2026, 4, 27, 11, 0, tzinfo=NY), datetime(2026, 4, 27, 11, 30, tzinfo=NY)),
    ]

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(buffer=15, placement="before"),
        preferred_dt=preferred,
        existing_busy=existing_busy,
        earliest=earliest,
        latest=latest,
        now=now,
    )

    for slot in slots:
        end = datetime.fromisoformat(slot.end_iso)
        if end.date() == datetime(2026, 4, 27).date():
            assert end <= datetime(2026, 4, 27, 10, 45, tzinfo=NY) or end >= datetime(2026, 4, 27, 11, 30, tzinfo=NY), \
                f"Slot ending {slot.end_iso} violates pre-buffer"


def test_slots_avoid_existing_busy_with_both_buffer():
    """buffer=15, placement=both: 7.5m pre + 7.5m post. Fractional math still works."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    existing_busy = [
        (datetime(2026, 4, 27, 10, 0, tzinfo=NY), datetime(2026, 4, 27, 10, 30, tzinfo=NY)),
    ]

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(buffer=15, placement="both"),
        preferred_dt=preferred,
        existing_busy=existing_busy,
        earliest=earliest,
        latest=latest,
        now=now,
    )

    for slot in slots:
        start = datetime.fromisoformat(slot.start_iso)
        end = datetime.fromisoformat(slot.end_iso)
        if start.date() == datetime(2026, 4, 27).date():
            overlaps_start = datetime(2026, 4, 27, 9, 52, 30, tzinfo=NY)
            overlaps_end = datetime(2026, 4, 27, 10, 37, 30, tzinfo=NY)
            assert not (start < overlaps_end and end > overlaps_start), \
                f"Slot {slot.start_iso}-{slot.end_iso} overlaps buffer-wrapped busy"


def test_slots_enforce_earliest_booking_hours_ahead():
    """Caller wants 30 minutes from now, config says 2hr minimum lead time."""
    now = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 30, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(earliest_hours=2),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        assert dt >= earliest, f"Slot {slot.start_iso} violates earliest_booking_hours_ahead"


def test_slots_enforce_booking_window():
    """Caller wants a time 40 days out, booking_window_days is 30."""
    now = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    preferred = datetime(2026, 6, 6, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(window_days=30),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        assert dt <= latest, f"Slot {slot.start_iso} exceeds booking window"


def test_slots_sorted_by_proximity_to_preferred():
    """Slots closer to the preferred time come first in the returned list."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 14, 0, tzinfo=NY)  # 2pm
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    assert len(slots) >= 2
    first_dist = abs(
        (datetime.fromisoformat(slots[0].start_iso) - preferred).total_seconds()
    )
    second_dist = abs(
        (datetime.fromisoformat(slots[1].start_iso) - preferred).total_seconds()
    )
    assert first_dist <= second_dist


def test_dst_crossover_spring_forward():
    """On March 8 2026, DST begins in NY. A call on March 7 asking for March 9 at 9am
    must produce a valid slot with correct UTC offset. Spring-forward means 2am -> 3am.
    """
    now = datetime(2026, 3, 7, 15, 0, tzinfo=NY)  # Sat Mar 7, still EST (-05:00)
    preferred = datetime(2026, 3, 9, 9, 0, tzinfo=NY)  # Mon Mar 9 9am, now EDT (-04:00)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    assert len(slots) >= 1
    first = datetime.fromisoformat(slots[0].start_iso)
    assert first.utcoffset() == timedelta(hours=-4), \
        f"Expected EDT (-04:00), got {first.utcoffset()}"
    assert first.hour == 9


def test_no_slots_returned_when_calendar_fully_booked():
    """If every slot in the window is busy or outside hours, return empty list."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=1)

    existing_busy = [
        (datetime(2026, 4, 27, 9, 0, tzinfo=NY), datetime(2026, 4, 27, 17, 0, tzinfo=NY)),
    ]

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(window_days=1),
        preferred_dt=preferred,
        existing_busy=existing_busy,
        earliest=earliest,
        latest=latest,
        now=now,
    )

    assert slots == []


def test_returns_max_3_slots():
    """API contract: up to 3 nearest slots returned."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 12, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )
    assert len(slots) <= 3


def test_slots_are_grid_aligned():
    """Slots should align to 15-minute grid boundaries (0, 15, 30, 45)."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )
    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        assert dt.minute in (0, 15, 30, 45)
        assert dt.second == 0
