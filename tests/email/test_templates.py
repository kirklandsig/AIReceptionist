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


def test_message_email_subject_normalizes_control_characters():
    msg = Message("Jane\r\nInjected", "+1", "msg", "Acme\nDental")
    subject, _, _ = build_message_email(msg, DispatchContext())
    assert "\r" not in subject
    assert "\n" not in subject
    assert "Jane Injected" in subject


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


def test_call_end_email_includes_agent_end_reason():
    """Issue #10: when the agent itself hangs up, the call summary must
    show the reason in both the text and HTML email bodies so staff can
    distinguish a polite goodbye from a silence-timeout."""
    md = CallMetadata(
        call_id="r", business_name="Acme", caller_phone="+15551112222",
        start_ts="2026-04-23T14:30:00+00:00",
        end_ts="2026-04-23T14:30:30+00:00",
        duration_seconds=30.0,
        outcomes={"agent_ended"},
        agent_end_reason="silence_timeout",
    )
    subject, body_text, body_html = build_call_end_email(md, DispatchContext())
    assert "Agent ended" in subject
    assert "Agent end reason: silence_timeout" in body_text
    assert "Agent end reason" in body_html
    assert "silence_timeout" in body_html


def test_call_end_email_omits_agent_end_reason_when_unset():
    """When the caller hung up first (no agent end), the reason row stays out
    of the body so the layout doesn't grow unused fields."""
    md = CallMetadata(
        call_id="r", business_name="Acme", caller_phone="+15551112222",
        start_ts="2026-04-23T14:30:00+00:00",
        outcomes={"hung_up"},
    )
    _, body_text, body_html = build_call_end_email(md, DispatchContext())
    assert "Agent end reason" not in body_text
    assert "Agent end reason" not in body_html


def test_call_end_email_embeds_transcript_content_when_include_transcript_true(tmp_path):
    """include_transcript=True embeds the actual transcript content into the
    email body, not just the file path. Operators reading the call summary
    should see the conversation without opening another file or another link.
    """
    transcript_md = tmp_path / "transcript.md"
    transcript_md.write_text(
        "# Call transcript — Acme Dental\n\n"
        "**Agent:** Thanks for calling Acme Dental.\n\n"
        "**Caller:** I need to reschedule my Tuesday appointment.\n",
        encoding="utf-8",
    )
    md = _metadata()
    context = DispatchContext(transcript_markdown_path=str(transcript_md))

    subject, body_text, body_html = build_call_end_email(
        md, context, include_transcript=True,
    )

    # Whole transcript appears verbatim in plain-text body
    assert "Thanks for calling Acme Dental." in body_text
    assert "I need to reschedule my Tuesday appointment." in body_text
    # And in the HTML body (escaped where appropriate)
    assert "Thanks for calling Acme Dental." in body_html
    assert "I need to reschedule my Tuesday appointment." in body_html


def test_call_end_email_omits_transcript_when_include_transcript_false(tmp_path):
    """include_transcript=False keeps the transcript path off the email
    entirely so operators relying on the YAML knob get exactly what they
    asked for."""
    transcript_md = tmp_path / "transcript.md"
    transcript_md.write_text("**Agent:** sensitive content\n", encoding="utf-8")
    md = _metadata()
    context = DispatchContext(transcript_markdown_path=str(transcript_md))

    subject, body_text, body_html = build_call_end_email(
        md, context, include_transcript=False,
    )

    assert "sensitive content" not in body_text
    assert "sensitive content" not in body_html
    assert "Transcript:" not in body_text
    assert "Transcript" not in body_html


def test_call_end_email_falls_back_to_path_when_transcript_file_missing(tmp_path):
    """If the markdown file is missing for some reason, the email should still
    send and include the path so the operator can find the JSON copy. Do not
    crash the call-end flow over an unreadable transcript."""
    missing = tmp_path / "does-not-exist.md"
    md = _metadata()
    context = DispatchContext(transcript_markdown_path=str(missing))

    subject, body_text, body_html = build_call_end_email(
        md, context, include_transcript=True,
    )

    assert str(missing) in body_text
    assert "transcript_unavailable" in body_text.lower() or "could not read" in body_text.lower()


def test_message_email_embeds_transcript_content_when_include_transcript_true(tmp_path):
    """When a caller leaves a message, the message email should carry the
    same conversational context the call-end email gets, so the recipient
    can see what was discussed before the take_message tool fired."""
    transcript_md = tmp_path / "t.md"
    transcript_md.write_text(
        "**Agent:** Thanks for calling.\n"
        "**Caller:** I need to leave a message for Alex.\n"
        "**Agent:** Got it, what would you like me to tell them?\n",
        encoding="utf-8",
    )
    msg = _message()
    ctx = DispatchContext(transcript_markdown_path=str(transcript_md))

    subject, body_text, body_html = build_message_email(
        msg, ctx, include_transcript=True,
    )

    assert "I need to leave a message for Alex." in body_text
    assert "I need to leave a message for Alex." in body_html


def test_message_email_omits_transcript_when_include_transcript_false(tmp_path):
    transcript_md = tmp_path / "t.md"
    transcript_md.write_text("**Caller:** confidential aside\n", encoding="utf-8")
    msg = _message()
    ctx = DispatchContext(transcript_markdown_path=str(transcript_md))

    subject, body_text, body_html = build_message_email(
        msg, ctx, include_transcript=False,
    )

    assert "confidential aside" not in body_text
    assert "confidential aside" not in body_html


def test_message_email_omits_recording_link_when_include_recording_link_false():
    msg = _message()
    ctx = DispatchContext(recording_url="https://example.com/r/m.mp3")
    _, body_text, body_html = build_message_email(
        msg, ctx, include_recording_link=False,
    )
    assert "example.com/r/m.mp3" not in body_text
    assert "example.com/r/m.mp3" not in body_html


def test_call_end_email_omits_recording_link_when_include_recording_link_false():
    """include_recording_link=False suppresses the recording URL row even if
    LiveKit produced one. Useful when the operator doesn't want links to a
    private bucket leaking into mail."""
    md = _metadata()
    context = DispatchContext(recording_url="https://example.com/r/123.mp3")

    _, body_text, body_html = build_call_end_email(
        md, context, include_recording_link=False,
    )

    assert "example.com/r/123.mp3" not in body_text
    assert "example.com/r/123.mp3" not in body_html
