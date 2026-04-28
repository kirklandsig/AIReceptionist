# tests/email/test_templates.py
from __future__ import annotations

from receptionist.email.templates import build_message_email, build_call_end_email
from receptionist.messaging.models import Message, DispatchContext
from receptionist.transcript.metadata import CallMetadata


def _message() -> Message:
    return Message(
        caller_name="Jane Doe",
        callback_number="+15551112222",
        message="Please call me back about my appointment.",
        business_name="Acme Dental",
        timestamp="2026-04-23T14:30:00+00:00",
    )


def _metadata() -> CallMetadata:
    return CallMetadata(
        call_id="room-1",
        business_name="Acme Dental",
        caller_phone="+15551112222",
        start_ts="2026-04-23T14:30:00+00:00",
        end_ts="2026-04-23T14:32:00+00:00",
        duration_seconds=120.0,
        outcomes={"message_taken"},
    )


def test_message_email_subject_includes_caller_and_business():
    subject, body_text, body_html = build_message_email(_message(), DispatchContext())
    assert "Jane Doe" in subject
    assert "Acme Dental" in subject


def test_message_email_body_contains_all_fields():
    subject, body_text, body_html = build_message_email(_message(), DispatchContext())
    assert "Jane Doe" in body_text
    assert "+15551112222" in body_text
    assert "Please call me back about my appointment." in body_text
    assert "2026-04-23" in body_text


def test_call_end_email_subject_includes_outcome():
    subject, body_text, body_html = build_call_end_email(_metadata(), DispatchContext())
    assert "message_taken" in subject or "Message taken" in subject


def test_call_end_email_body_has_duration():
    subject, body_text, body_html = build_call_end_email(_metadata(), DispatchContext())
    assert "2:00" in body_text or "120" in body_text


def test_html_body_is_present_and_escapes():
    msg = Message("Jane <admin>", "+1", "<script>", "Acme", "2026-01-01T00:00:00+00:00")
    subject, body_text, body_html = build_message_email(msg, DispatchContext())
    assert "<script>" not in body_html  # escaped
    assert "&lt;script&gt;" in body_html


def test_call_end_email_subject_multi_outcome():
    from receptionist.email.templates import build_call_end_email
    from receptionist.messaging.models import DispatchContext
    md = CallMetadata(
        call_id="r", business_name="Acme", caller_phone="+1",
        start_ts="2026-04-23T14:30:00+00:00",
        end_ts="2026-04-23T14:32:00+00:00",
        duration_seconds=120.0,
        outcomes={"transferred", "appointment_booked"},
    )
    subject, body_text, _ = build_call_end_email(md, DispatchContext())
    # Rendered alphabetically: appointment_booked first, then transferred
    assert "Appointment booked + Transferred" in subject


def test_call_end_email_subject_includes_transfer_target():
    md = CallMetadata(
        call_id="r", business_name="Acme", caller_phone="+1",
        start_ts="2026-04-23T14:30:00+00:00",
        outcomes={"transferred"},
        transfer_target="Agent Smith",
    )
    subject, _, _ = build_call_end_email(md, DispatchContext())
    assert "Transferred to Agent Smith" in subject


def test_call_end_email_subject_multi_outcome_includes_transfer_target():
    md = CallMetadata(
        call_id="r", business_name="Acme", caller_phone="+1",
        start_ts="2026-04-23T14:30:00+00:00",
        outcomes={"transferred", "appointment_booked"},
        transfer_target="Agent Smith",
    )
    subject, _, _ = build_call_end_email(md, DispatchContext())
    assert "Appointment booked + Transferred to Agent Smith" in subject


def test_call_end_email_html_includes_transfer_target():
    md = _metadata()
    md.outcomes = {"transferred"}
    md.transfer_target = "Agent Smith"
    _, body_text, body_html = build_call_end_email(md, DispatchContext())
    assert "Transferred to: Agent Smith" in body_text
    assert "Transferred to" in body_html
    assert "Agent Smith" in body_html


def test_call_end_email_html_matches_text_summary_fields():
    md = _metadata()
    md.appointment_details = {
        "event_id": "evt1",
        "start_iso": "2026-04-28T14:00:00-04:00",
        "end_iso": "2026-04-28T14:30:00-04:00",
        "html_link": "https://calendar.google.com/event?eid=abc",
    }
    md.faqs_answered = ["Where are you located?", "Do you take Cigna?"]
    md.languages_detected = {"es", "en"}
    context = DispatchContext(transcript_markdown_path="transcripts/room-1.md")
    _, body_text, body_html = build_call_end_email(md, context)
    assert "Appointment:" in body_text
    assert "FAQs answered:" in body_text
    assert "Languages: en, es" in body_text
    assert "Transcript: transcripts/room-1.md" in body_text
    assert "Appointment" in body_html
    assert "calendar.google.com" in body_html
    assert "FAQs answered" in body_html
    assert "Where are you located?, Do you take Cigna?" in body_html
    assert "Languages" in body_html
    assert "en, es" in body_html
    assert "Transcript" in body_html
    assert "transcripts/room-1.md" in body_html


def test_call_end_email_marks_recording_failed():
    md = _metadata()
    md.recording_failed = True
    _, body_text, body_html = build_call_end_email(
        md, DispatchContext(recording_url="recordings/room-1.mp3"),
    )
    assert "Recording: failed" in body_text
    assert "Recording:</strong> failed" in body_html
    assert "recordings/room-1.mp3" not in body_text
    assert "recordings/room-1.mp3" not in body_html


def test_build_booking_email_includes_event_link():
    from receptionist.email.templates import build_booking_email
    from receptionist.messaging.models import DispatchContext
    md = CallMetadata(
        call_id="r", business_name="Acme", caller_phone="+15551112222",
        appointment_booked=True,
        appointment_details={
            "event_id": "evt1",
            "start_iso": "2026-04-28T14:00:00-04:00",
            "end_iso": "2026-04-28T14:30:00-04:00",
            "html_link": "https://calendar.google.com/event?eid=abc",
        },
    )
    subject, body_text, body_html = build_booking_email(md, DispatchContext())
    assert "appointment booked" in subject.lower()
    assert "+15551112222" in subject
    assert "https://calendar.google.com/event?eid=abc" in body_text
    assert "was NOT verified" in body_text
    assert "calendar.google.com" in body_html


def test_outcome_labels_cover_all_valid_outcomes():
    """Regression: _OUTCOME_LABELS must be kept in sync with VALID_OUTCOMES.

    If a future maintainer adds an outcome to VALID_OUTCOMES but forgets
    _OUTCOME_LABELS, _outcomes_display silently falls back to the raw
    outcome string. This test makes that omission a test failure instead.
    """
    from receptionist.email.templates import _OUTCOME_LABELS
    from receptionist.transcript.metadata import VALID_OUTCOMES
    assert set(_OUTCOME_LABELS.keys()) == VALID_OUTCOMES, (
        "_OUTCOME_LABELS keys must match VALID_OUTCOMES exactly. "
        "If you added a new outcome, update both."
    )
