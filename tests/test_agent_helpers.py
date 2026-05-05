# tests/test_agent_helpers.py
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from livekit import rtc

from receptionist.agent import (
    _capture_caller_phone_from_participant,
    _get_caller_identity,
    _get_caller_phone,
    _get_sip_participant_phone,
    _resolve_relative_date,
)
from receptionist.lifecycle import CallLifecycle


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


def _participant(kind, attrs=None, identity=""):
    return SimpleNamespace(kind=kind, attributes=attrs or {}, identity=identity)


def test_get_sip_participant_phone_reads_sip_attribute():
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        {"sip.phoneNumber": "+15551112222"},
    )
    assert _get_sip_participant_phone(participant) == "+15551112222"


def test_get_sip_participant_phone_uses_attribute_regardless_of_kind():
    """BYOC/Asterisk trunks may emit the SIP participant with a non-SIP kind.

    The kind gate was removed in 2026-05; the helper now relies on attributes
    and the `sip_<digits>` identity regex, both of which are specific enough
    that false positives from non-SIP participants are not a real risk.
    """
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        {"sip.phoneNumber": "+15551112222"},
    )
    assert _get_sip_participant_phone(participant) == "+15551112222"


def test_get_sip_participant_phone_uses_identity_regardless_of_kind():
    """Issue #9 regression: a STANDARD-kind participant whose identity is
    `sip_<digits>` (Asterisk BYOC pattern) must still resolve to a phone."""
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        identity="sip_17135550038",
    )
    assert _get_sip_participant_phone(participant) == "+17135550038"


def test_get_sip_participant_phone_prefers_explicit_sip_attribute():
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        {"sip.phoneNumber": "+15551112222"},
        "sip_17135550038",
    )
    assert _get_sip_participant_phone(participant) == "+15551112222"


def test_get_sip_participant_phone_reads_sip_from_user():
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        {"sip.fromUser": "17135550038"},
    )
    assert _get_sip_participant_phone(participant) == "+17135550038"


def test_get_sip_participant_phone_reads_sip_from_uri():
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        {"sip.from": "sip:+17135550038@pbx.example.com"},
    )
    assert _get_sip_participant_phone(participant) == "+17135550038"


def test_get_sip_participant_phone_reads_sip_from_header_uri():
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        {"sip.from": '"Keith" <sip:+17135550038@pbx.example.com>;tag=abc'},
    )
    assert _get_sip_participant_phone(participant) == "+17135550038"


def test_get_sip_participant_phone_reads_sip_identity_fallback():
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        identity="sip_17135550038",
    )
    assert _get_sip_participant_phone(participant) == "+17135550038"


def test_get_sip_participant_phone_ignores_non_phone_identity():
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        identity="sip_agent_smith",
    )
    assert _get_sip_participant_phone(participant) is None


def test_get_sip_participant_phone_returns_none_for_irrelevant_participant():
    """A non-SIP participant with no sip.* attributes and a non-SIP identity
    must not produce a phone (no false positives from the relaxed kind gate)."""
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        attrs={"agent.state": "listening"},
        identity="agent-12345",
    )
    assert _get_sip_participant_phone(participant) is None


def test_capture_caller_phone_from_connected_sip_participant(v2_yaml):
    from receptionist.config import BusinessConfig
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone=None)
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        {"sip.phoneNumber": "+15551112222"},
    )
    _capture_caller_phone_from_participant(lifecycle, participant)
    assert lifecycle.metadata.caller_phone == "+15551112222"


def test_capture_caller_phone_from_sip_participant_without_phone_is_noop(v2_yaml):
    from receptionist.config import BusinessConfig
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone=None)
    participant = _participant(rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
    _capture_caller_phone_from_participant(lifecycle, participant)
    assert lifecycle.metadata.caller_phone is None


def test_capture_caller_phone_from_byoc_identity_only_participant(v2_yaml):
    """Issue #9 regression: an Asterisk/BYOC participant with kind=STANDARD
    and identity `sip_<digits>` must have its phone captured. The kind gate
    was the silent-Unknown trap reported by @trinicomcom."""
    from receptionist.config import BusinessConfig
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone=None)
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        identity="sip_17135550038",
    )
    _capture_caller_phone_from_participant(lifecycle, participant)
    assert lifecycle.metadata.caller_phone == "+17135550038"


def test_capture_caller_phone_logs_negative_result_at_info(caplog, v2_yaml):
    """Issue #9: operators need a clear INFO log when CallerID can't be
    resolved, so they can see what attributes/identity the SIP trunk
    actually published without flipping debug flags."""
    import logging

    from receptionist.config import BusinessConfig
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone=None)
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        attrs={"sip.callId": "abc-123"},
        identity="sip_agent_smith",
    )
    with caplog.at_level(logging.INFO, logger="receptionist"):
        _capture_caller_phone_from_participant(lifecycle, participant)
    matched = [
        r for r in caplog.records
        if getattr(r, "component", None) == "agent.callerid"
    ]
    assert matched, "expected an agent.callerid INFO log record"
    msg = matched[0].getMessage()
    assert "no phone resolvable" in msg
    assert "sip_agent_smith" in msg
    # And the structured `extra` carries source/identity for log shippers
    record = matched[0]
    assert record.source == "snapshot"
    assert record.participant_identity == "sip_agent_smith"


def test_capture_caller_phone_logs_positive_result_at_info(caplog, v2_yaml):
    import logging

    from receptionist.config import BusinessConfig
    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone=None)
    participant = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        identity="sip_17135550038",
    )
    with caplog.at_level(logging.INFO, logger="receptionist"):
        _capture_caller_phone_from_participant(
            lifecycle, participant, source="participant_attributes_changed",
        )
    matched = [
        r for r in caplog.records
        if getattr(r, "component", None) == "agent.callerid"
        and "captured caller phone" in r.getMessage()
    ]
    assert matched, "expected a successful capture INFO log record"
    assert matched[0].source == "participant_attributes_changed"


# ---- _get_caller_identity / _get_caller_phone room-level tests ----


def _ctx(*participants):
    """Minimal JobContext stand-in: just exposes ctx.room.remote_participants."""
    room = SimpleNamespace(
        name="test-room",
        remote_participants={p.identity or f"id-{i}": p for i, p in enumerate(participants)},
    )
    return SimpleNamespace(room=room)


def test_get_caller_identity_prefers_sip_kind():
    sip_p = _participant(rtc.ParticipantKind.PARTICIPANT_KIND_SIP, identity="sip_17135550038")
    standard_p = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, identity="sip_19998887777",
    )
    assert _get_caller_identity(_ctx(standard_p, sip_p)) == "sip_17135550038"


def test_get_caller_identity_falls_back_to_byoc_identity_when_no_sip_kind():
    """Issue #9: BYOC trunks may publish the SIP participant with a non-SIP kind.
    Identity-based fallback keeps caller-identity resolution working."""
    standard_p = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, identity="sip_17135550038",
    )
    assert _get_caller_identity(_ctx(standard_p)) == "sip_17135550038"


def test_get_caller_identity_returns_empty_when_no_sip_like_participant(caplog):
    """Issue #9: the warning is preserved when nothing looks SIP-like; caller
    identity becomes the empty string and downstream code knows to skip
    SIP-specific operations."""
    import logging

    standard_p = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, identity="agent-12345",
    )
    with caplog.at_level(logging.WARNING):
        assert _get_caller_identity(_ctx(standard_p)) == ""
    assert any("No SIP participant" in r.getMessage() for r in caplog.records)


def test_get_caller_phone_uses_byoc_identity_when_attributes_missing():
    """Issue #9 regression: phone resolves from a STANDARD-kind participant
    whose identity is `sip_<digits>` (Asterisk/BYOC pattern)."""
    standard_p = _participant(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, identity="sip_17135550038",
    )
    assert _get_caller_phone(_ctx(standard_p)) == "+17135550038"


# ---- _offered_slot_batches eviction tests (memory cap) ----

def _bare_receptionist():
    """Construct a Receptionist with the minimum scaffolding to exercise the
    slot-cache helpers. Avoids the LiveKit Agent superclass init by
    instantiating the helpers off a SimpleNamespace stand-in.
    """
    from collections import deque
    from types import SimpleNamespace
    from receptionist.agent import Receptionist
    obj = SimpleNamespace()
    obj._offered_slot_batches = deque(maxlen=3)
    # Bind the methods to the namespace so we can call them directly
    obj._record_offered_slots = Receptionist._record_offered_slots.__get__(obj)
    obj._slot_was_offered = Receptionist._slot_was_offered.__get__(obj)
    obj._reset_offered_slots = Receptionist._reset_offered_slots.__get__(obj)
    return obj


def test_offered_slots_basic_record_and_lookup():
    r = _bare_receptionist()
    r._record_offered_slots(["2026-04-28T10:00:00-04:00", "2026-04-28T11:00:00-04:00"])
    assert r._slot_was_offered("2026-04-28T10:00:00-04:00")
    assert r._slot_was_offered("2026-04-28T11:00:00-04:00")
    assert not r._slot_was_offered("2026-04-28T15:00:00-04:00")


def test_offered_slots_evicts_oldest_batch_after_three_check_availability_calls():
    """deque(maxlen=3): the 4th batch evicts the 1st. Slots from the 1st
    batch are no longer recognized; book_appointment would refuse them."""
    r = _bare_receptionist()
    r._record_offered_slots(["batch1-a", "batch1-b"])
    r._record_offered_slots(["batch2-a", "batch2-b"])
    r._record_offered_slots(["batch3-a"])
    # 3 batches in cache, all still recognized
    assert r._slot_was_offered("batch1-a")
    assert r._slot_was_offered("batch2-a")
    assert r._slot_was_offered("batch3-a")
    # 4th batch evicts batch1
    r._record_offered_slots(["batch4-a"])
    assert not r._slot_was_offered("batch1-a")
    assert not r._slot_was_offered("batch1-b")
    assert r._slot_was_offered("batch2-a")  # still around
    assert r._slot_was_offered("batch4-a")


def test_offered_slots_reset_clears_and_seeds():
    """After race recovery: reset wipes prior batches and seeds with the
    fresh alternates only — old slots, even recent ones, are gone."""
    r = _bare_receptionist()
    r._record_offered_slots(["pre-1", "pre-2"])
    r._record_offered_slots(["pre-3"])
    r._reset_offered_slots(["fresh-a", "fresh-b"])
    assert not r._slot_was_offered("pre-1")
    assert not r._slot_was_offered("pre-3")
    assert r._slot_was_offered("fresh-a")
    assert r._slot_was_offered("fresh-b")


def test_offered_slots_size_bounded_under_long_call():
    """Memory cap regression: 100 batches must not grow the cache past 3."""
    r = _bare_receptionist()
    for i in range(100):
        r._record_offered_slots([f"slot-{i}-{j}" for j in range(3)])
    assert len(r._offered_slot_batches) == 3
    # Only the last 3 batches are still queryable
    assert r._slot_was_offered("slot-99-0")
    assert r._slot_was_offered("slot-97-2")
    assert not r._slot_was_offered("slot-50-0")
    assert not r._slot_was_offered("slot-0-0")
