# tests/transcript/test_metadata.py
from __future__ import annotations

from receptionist.transcript.metadata import CallMetadata


def test_metadata_defaults():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    assert md.start_ts
    assert md.end_ts is None
    assert md.outcome is None
    assert md.faqs_answered == []
    assert md.languages_detected == set()


def test_metadata_finalize_sets_end_and_hung_up():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.mark_finalized()
    assert md.end_ts is not None
    assert md.outcome == "hung_up"
    assert md.duration_seconds is not None
    assert md.duration_seconds >= 0


def test_metadata_finalize_preserves_existing_outcome():
    md = CallMetadata(call_id="room-1", business_name="Acme", outcome="transferred")
    md.mark_finalized()
    assert md.outcome == "transferred"


def test_metadata_duration_computed_from_iso_timestamps():
    md = CallMetadata(
        call_id="room-1", business_name="Acme",
        start_ts="2026-04-23T14:30:00+00:00",
        end_ts="2026-04-23T14:32:30+00:00",
    )
    md.mark_finalized()
    assert md.duration_seconds == 150.0


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
