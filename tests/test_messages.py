# tests/test_messages.py
"""Legacy smoke tests — the full coverage lives in tests/messaging/test_file_channel.py."""
from __future__ import annotations

import pytest

from receptionist.messaging.models import Message


def test_message_timestamp_autofills():
    msg = Message("Jane", "+15551112222", "Call me", "Acme")
    assert msg.timestamp  # auto-populated ISO timestamp


def test_message_to_dict_roundtrip():
    msg = Message("Jane", "+15551112222", "Call me", "Acme", timestamp="2026-01-01T00:00:00+00:00")
    d = msg.to_dict()
    assert d == {
        "caller_name": "Jane",
        "callback_number": "+15551112222",
        "message": "Call me",
        "business_name": "Acme",
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
