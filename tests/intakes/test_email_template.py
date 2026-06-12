# tests/intakes/test_email_template.py
from __future__ import annotations

from receptionist.email.templates import build_intake_email
from receptionist.intakes.models import IntakeAnswer, IntakeSubmission
from receptionist.messaging.models import DispatchContext


def _submission(language: str = "en", **kwargs) -> IntakeSubmission:
    return IntakeSubmission(
        case_type="example_intake",
        business_name="Acme Law",
        call_id="room-1",
        caller_name="Jane Doe",
        callback_number="+15551112222",
        answers=[
            IntakeAnswer(
                question_key="legal_name",
                prompt="State your full legal name.",
                spoken_text="Jane Doe",
                language=language,
                english_summary="Jane Doe",
            ),
            IntakeAnswer(
                question_key="employer",
                prompt="Who was your employer?",
                spoken_text="Acme Construction Co.",
                language=language,
                english_summary="Acme Construction (a construction firm)",
            ),
        ],
        language=language,
        english_overview="New WC intake for Jane Doe, injured while working at Acme Construction.",
        status=kwargs.pop("status", "final"),
        started_at="2026-05-19T01:00:00+00:00",
        completed_at="2026-05-19T01:15:00+00:00",
    )


def test_intake_email_subject_uses_display_name():
    subject, _, _ = build_intake_email(
        _submission(), DispatchContext(), case_type_display="Workers' Compensation",
    )
    assert "Intake:" in subject
    assert "Workers' Compensation" in subject
    assert "Jane Doe" in subject
    assert "Acme Law" in subject


def test_intake_email_subject_marks_partial_status():
    subject, _, _ = build_intake_email(
        _submission(status="partial"), DispatchContext(),
        case_type_display="Workers' Compensation",
    )
    assert "[PARTIAL]" in subject


def test_intake_email_subject_falls_back_to_raw_key_when_display_missing():
    subject, _, _ = build_intake_email(_submission(), DispatchContext())
    assert "example_intake" in subject


def test_intake_email_body_contains_all_answers():
    _, body_text, _ = build_intake_email(
        _submission(), DispatchContext(),
        case_type_display="Workers' Compensation",
    )
    assert "Jane Doe" in body_text
    assert "+15551112222" in body_text
    assert "Acme Construction Co." in body_text
    assert "Acme Construction (a construction firm)" in body_text
    assert "State your full legal name." in body_text
    assert "Who was your employer?" in body_text


def test_intake_email_spanish_call_shows_both_spoken_and_english():
    sub = IntakeSubmission(
        case_type="example",
        business_name="Acme",
        call_id="room-1",
        caller_name="Juan García",
        callback_number="+15551112222",
        answers=[
            IntakeAnswer(
                question_key="employer",
                prompt="¿Quién era su empleador?",
                spoken_text="Constructora Hernández",
                language="es",
                english_summary="Hernández Construction",
            ),
        ],
        language="es",
        english_overview="Spanish-speaking caller from Hernández Construction.",
        status="final",
    )
    _, body_text, body_html = build_intake_email(sub, DispatchContext())
    assert "Constructora Hernández" in body_text
    assert "Hernández Construction" in body_text
    # English summary is rendered when distinct from spoken_text
    assert "English:" in body_text
    assert "Constructora Hern" in body_html
    assert "Hern&aacute;ndez Construction" in body_html or "Hernández Construction" in body_html


def test_intake_email_html_escapes_input():
    sub = _submission()
    sub.caller_name = "<script>alert('x')</script>"
    _, _, body_html = build_intake_email(
        sub, DispatchContext(), case_type_display="Workers' Compensation",
    )
    assert "<script>" not in body_html
    assert "&lt;script&gt;" in body_html


def test_intake_email_omits_transcript_when_disabled(tmp_path):
    transcript = tmp_path / "transcript.md"
    transcript.write_text("**Agent:** sensitive content", encoding="utf-8")
    sub = _submission()
    _, body_text, _ = build_intake_email(
        sub,
        DispatchContext(transcript_markdown_path=str(transcript)),
        include_transcript=False,
    )
    assert "sensitive content" not in body_text


def test_intake_email_notes_attachment_when_enabled(tmp_path):
    transcript = tmp_path / "transcript.md"
    transcript.write_text("**Agent:** Hi Jane.\n**Caller:** Hi.\n", encoding="utf-8")
    sub = _submission()
    _, body_text, _ = build_intake_email(
        sub,
        DispatchContext(transcript_markdown_path=str(transcript), call_id="room-1"),
        include_transcript=True,
    )
    assert "Hi Jane." not in body_text
    assert "--- Transcript ---" not in body_text
    assert "Transcript attached: transcript_room-1.txt" in body_text
    assert "Transcript path: " in body_text
