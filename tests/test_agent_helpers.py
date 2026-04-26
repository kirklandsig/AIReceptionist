# tests/test_agent_helpers.py
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from receptionist.agent import _resolve_relative_date


@pytest.fixture
def sun_apr_26_2026():
    """A Sunday for predictable weekday math in the resolver tests."""
    return datetime(2026, 4, 26, 10, 30, tzinfo=ZoneInfo("America/New_York"))


def test_resolve_today(sun_apr_26_2026):
    assert _resolve_relative_date("today", sun_apr_26_2026) == "April 26 2026"


def test_resolve_tonight_aliases_today(sun_apr_26_2026):
    assert _resolve_relative_date("tonight", sun_apr_26_2026) == "April 26 2026"


def test_resolve_tomorrow(sun_apr_26_2026):
    assert _resolve_relative_date("tomorrow", sun_apr_26_2026) == "April 27 2026"


def test_resolve_this_weekday_uses_soonest_occurrence(sun_apr_26_2026):
    """'This Friday' on a Sunday is the upcoming Friday (5 days out)."""
    assert _resolve_relative_date("this Friday", sun_apr_26_2026) == "May 01 2026"


def test_resolve_this_weekday_today_returns_today(sun_apr_26_2026):
    """'This Sunday' on a Sunday is today."""
    assert _resolve_relative_date("this Sunday", sun_apr_26_2026) == "April 26 2026"


def test_resolve_next_weekday_jumps_a_week(sun_apr_26_2026):
    """'Next Monday' is at least 7 days out — never tomorrow."""
    assert _resolve_relative_date("next Monday", sun_apr_26_2026) == "May 04 2026"


def test_resolve_next_weekday_when_today_is_target(sun_apr_26_2026):
    """'Next Sunday' on a Sunday means 7 days from now, not today."""
    assert _resolve_relative_date("next Sunday", sun_apr_26_2026) == "May 03 2026"


def test_resolve_passthrough_for_absolute_dates(sun_apr_26_2026):
    """Absolute dates fall through unchanged for dateutil to parse."""
    assert _resolve_relative_date("April 28", sun_apr_26_2026) == "April 28"


def test_resolve_passthrough_for_bare_weekday(sun_apr_26_2026):
    """Bare weekday names fall through — dateutil handles them."""
    assert _resolve_relative_date("Monday", sun_apr_26_2026) == "Monday"


def test_resolve_case_insensitive(sun_apr_26_2026):
    assert _resolve_relative_date("TOMORROW", sun_apr_26_2026) == "April 27 2026"
    assert _resolve_relative_date("Next Monday", sun_apr_26_2026) == "May 04 2026"
