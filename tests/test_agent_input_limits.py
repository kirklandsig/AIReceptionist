# tests/test_agent_input_limits.py
"""Coverage for the _cap helper that truncates overlong caller-supplied text.

The agent passes caller utterances into tool methods unmodified. Without a
length cap, a chatty caller can stuff thousands of characters into "message"
or "notes" and bloat storage / hit Google's 8KB event description ceiling.
The agent caps each free-text field before persistence and logs when it
truncates, so staff can find the original on the server if needed.
"""
from __future__ import annotations

import logging

import pytest

from receptionist.agent import _TRUNCATE_LIMITS, _cap


@pytest.mark.parametrize("field,limit", list(_TRUNCATE_LIMITS.items()))
def test_cap_returns_short_input_unchanged(field, limit):
    short = "a" * (limit - 1)
    assert _cap(field, short) == short


@pytest.mark.parametrize("field,limit", list(_TRUNCATE_LIMITS.items()))
def test_cap_returns_input_at_exactly_limit_unchanged(field, limit):
    """Boundary: exactly == limit must NOT truncate (truncation is len > limit)."""
    exact = "a" * limit
    assert _cap(field, exact) == exact


@pytest.mark.parametrize("field,limit", list(_TRUNCATE_LIMITS.items()))
def test_cap_truncates_overlong_input(field, limit):
    too_long = "a" * (limit + 100)
    capped = _cap(field, too_long)
    assert capped is not None
    assert len(capped) == limit
    assert capped == "a" * limit


def test_cap_passes_none_through():
    """None inputs (optional fields like notes/caller_email) stay None."""
    assert _cap("notes", None) is None
    assert _cap("caller_email", None) is None


@pytest.mark.parametrize("field,limit", list(_TRUNCATE_LIMITS.items()))
def test_cap_logs_truncation_at_info(field, limit, caplog):
    """Truncation events are logged so staff can recover the full text from logs."""
    too_long = "a" * (limit + 50)
    with caplog.at_level(logging.INFO, logger="receptionist"):
        _cap(field, too_long, call_id="test-call-1")
    truncation_records = [r for r in caplog.records if "Truncated overlong" in r.message]
    assert len(truncation_records) == 1
    msg = truncation_records[0].message
    assert field in msg
    assert str(limit + 50) in msg
    assert str(limit) in msg


def test_cap_does_not_log_when_no_truncation_needed(caplog):
    """No log noise for the common case where input is already within bounds."""
    with caplog.at_level(logging.INFO, logger="receptionist"):
        _cap("message", "ok", call_id="c")
    truncation_records = [r for r in caplog.records if "Truncated overlong" in r.message]
    assert truncation_records == []


def test_cap_email_limit_is_rfc_5321():
    """Email cap should match RFC 5321 (254 chars)."""
    assert _TRUNCATE_LIMITS["caller_email"] == 254


def test_cap_unknown_field_raises():
    """Calling _cap with a field not in the limits dict is a programmer error."""
    with pytest.raises(KeyError):
        _cap("unknown_field", "x")
