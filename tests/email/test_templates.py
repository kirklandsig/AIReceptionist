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
        outcome="message_taken",
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
