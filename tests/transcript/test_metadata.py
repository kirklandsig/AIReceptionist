# tests/transcript/test_metadata.py
from __future__ import annotations

from receptionist.transcript.metadata import CallMetadata, VALID_OUTCOMES


def test_metadata_defaults():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    assert md.start_ts
    assert md.end_ts is None
    assert md.outcomes == set()
    assert md.appointment_booked is False
    assert md.appointment_details is None
    assert md.faqs_answered == []
    assert md.languages_detected == set()


def test_metadata_finalize_sets_end_and_hung_up():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.mark_finalized()
    assert md.end_ts is not None
    assert md.outcomes == {"hung_up"}
    assert md.duration_seconds is not None
    assert md.duration_seconds >= 0


def test_metadata_finalize_preserves_existing_outcomes():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.outcomes.add("transferred")
    md.mark_finalized()
    assert md.outcomes == {"transferred"}  # hung_up NOT added when outcomes non-empty


def test_metadata_multi_outcome():
    """A call can be both transferred AND have an appointment booked."""
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.outcomes.add("transferred")
    md.outcomes.add("appointment_booked")
    md.mark_finalized()
    assert md.outcomes == {"transferred", "appointment_booked"}


def test_metadata_duration_computed_from_iso_timestamps():
    md = CallMetadata(
        call_id="room-1", business_name="Acme",
        start_ts="2026-04-23T14:30:00+00:00",
        end_ts="2026-04-23T14:32:30+00:00",
    )
    md.mark_finalized()
    assert md.duration_seconds == 150.0


def test_metadata_to_dict_outcomes_sorted_list():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.outcomes.add("transferred")
    md.outcomes.add("appointment_booked")
    d = md.to_dict()
    assert d["outcomes"] == ["appointment_booked", "transferred"]  # alphabetically sorted


def test_metadata_to_dict_sorts_languages():
    md = CallMetadata(
        call_id="room-1", business_name="Acme",
        languages_detected={"es", "en"},
        faqs_answered=["Where are you located?"],
    )
    d = md.to_dict()
    assert d["languages_detected"] == ["en", "es"]
    assert d["faqs_answered"] == ["Where are you located?"]
    assert d["call_id"] == "room-1"


def test_metadata_to_dict_includes_new_fields():
    md = CallMetadata(
        call_id="room-1", business_name="Acme",
        appointment_booked=True,
        appointment_details={"event_id": "abc", "start_iso": "2026-04-24T14:00:00-04:00"},
    )
    d = md.to_dict()
    assert d["appointment_booked"] is True
    assert d["appointment_details"]["event_id"] == "abc"


def test_valid_outcomes_is_expected_set():
    """Regression: ensure the allowed outcome vocabulary matches the design spec."""
    assert VALID_OUTCOMES == {
        "hung_up", "message_taken", "transferred",
        "appointment_booked", "agent_ended",
    }


def test_metadata_to_dict_includes_agent_end_reason():
    """Issue #10: the agent_end_reason must round-trip through to_dict so
    transcript JSON exporters and webhooks see the reason value."""
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.outcomes.add("agent_ended")
    md.agent_end_reason = "silence_timeout"
    md.mark_finalized()
    d = md.to_dict()
    assert d["agent_end_reason"] == "silence_timeout"
    assert "agent_ended" in d["outcomes"]


def test_metadata_default_agent_end_reason_is_none():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    assert md.agent_end_reason is None
    d = md.to_dict()
    assert d["agent_end_reason"] is None
