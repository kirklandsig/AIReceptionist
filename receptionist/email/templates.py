# receptionist/email/templates.py
from __future__ import annotations

import html
import re

from receptionist.config import InfoPacket
from receptionist.intakes.models import IntakeSubmission
from receptionist.messaging.models import Message, DispatchContext
from receptionist.transcript.metadata import CallMetadata


# Human-readable display labels for outcome values. Keep in sync with
# VALID_OUTCOMES in receptionist/transcript/metadata.py.
_OUTCOME_LABELS = {
    "hung_up": "Hung up",
    "message_taken": "Message taken",
    "transferred": "Transferred",
    "appointment_booked": "Appointment booked",
    "agent_ended": "Agent ended",
    "intake_submitted": "Intake submitted",
}


def _subject_safe(value: str | None) -> str:
    return " ".join((value or "").replace("\r", " ").replace("\n", " ").replace("\x00", " ").split())


_NON_DIGITS_RE = re.compile(r"\D+")


def _pretty_phone(value: str | None) -> str:
    """Format NANP (US/Canada) numbers as +1 (XXX) XXX-XXXX; else verbatim."""
    if not value:
        return "Unknown"
    digits = _NON_DIGITS_RE.sub("", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+1 ({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
    return value


def _same_phone(a: str | None, b: str | None) -> bool:
    """True when two phone strings refer to the same number (last 10 digits).

    Different country codes sharing the same 10-digit national number
    compare equal — accepted trade-off.
    """
    da = _NON_DIGITS_RE.sub("", a or "")
    db = _NON_DIGITS_RE.sub("", b or "")
    if not da or not db:
        return False
    return da[-10:] == db[-10:]


def transcript_filename(call_id: str | None) -> str:
    """Attachment filename for the transcript .txt — mirrors the on-disk
    sanitization in transcript/writer.py so the names correlate."""
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", call_id or "unknown")
    return f"transcript_{safe}.txt"


def _outcomes_display(
    outcomes: set[str] | list[str], *, transfer_target: str | None = None,
) -> str:
    """Render a set of outcomes as a sorted human-readable string.

    Example: {"transferred", "appointment_booked"} -> "Appointment booked + Transferred"
    """
    if not outcomes:
        return "Unknown"
    labels = []
    for outcome in sorted(outcomes):
        if outcome == "transferred" and transfer_target:
            labels.append(f"Transferred to {transfer_target}")
        else:
            labels.append(_OUTCOME_LABELS.get(outcome, outcome))
    return " + ".join(labels)


def _caller_display_name(
    submission: IntakeSubmission | None, captured_messages: list[Message],
) -> str | None:
    if submission is not None and submission.caller_name.strip():
        return submission.caller_name.strip()
    for msg in captured_messages:
        if msg.caller_name.strip():
            return msg.caller_name.strip()
    return None


def _distinct_callback_number(
    metadata: CallMetadata,
    submission: IntakeSubmission | None,
    captured_messages: list[Message],
) -> str | None:
    candidates: list[str] = []
    if submission is not None:
        candidates.append(submission.callback_number)
    candidates.extend(m.callback_number for m in captured_messages)
    for cand in candidates:
        cand = (cand or "").strip()
        if cand and not _same_phone(cand, metadata.caller_phone):
            return cand
    return None


def _call_context_label(
    metadata: CallMetadata,
    submission: IntakeSubmission | None,
    case_type_display: str | None,
    captured_messages: list[Message],
) -> str:
    if submission is not None:
        label = case_type_display or submission.case_type
        marker = "" if submission.status == "final" else " [PARTIAL]"
        return f"Intake{marker}: {label}"
    if captured_messages:
        return "Message taken"
    return _outcomes_display(metadata.outcomes, transfer_target=metadata.transfer_target)


def _intake_answers_text(submission: IntakeSubmission) -> str:
    answer_lines: list[str] = []
    for ans in submission.answers:
        spoken = ans.spoken_text.strip() or "(no answer)"
        summary = ans.english_summary.strip()
        if summary and summary != spoken:
            answer_lines.append(
                f"  {ans.prompt}\n"
                f"    Answer ({ans.language}): {spoken}\n"
                f"    English: {summary}"
            )
        else:
            answer_lines.append(f"  {ans.prompt}\n    Answer: {spoken}")
    return "\n\n".join(answer_lines) if answer_lines else "  (no answers captured)"


def _intake_answers_html_table(submission: IntakeSubmission) -> str:
    def e(s: str | None) -> str:
        return html.escape(s or "", quote=True)

    rows_html: list[str] = []
    for ans in submission.answers:
        spoken = ans.spoken_text or "(no answer)"
        summary = ans.english_summary
        cells = (
            f"<td style='padding:4px;border:1px solid #ccc'>{e(ans.prompt)}</td>"
            f"<td style='padding:4px;border:1px solid #ccc'>{e(spoken)}</td>"
        )
        if summary and summary != spoken:
            cells += f"<td style='padding:4px;border:1px solid #ccc'>{e(summary)}</td>"
        else:
            cells += "<td style='padding:4px;border:1px solid #ccc'>&nbsp;</td>"
        rows_html.append(f"<tr>{cells}</tr>")
    rows_block = "\n".join(rows_html) if rows_html else (
        "<tr><td colspan='3' style='padding:4px;border:1px solid #ccc'>"
        "(no answers captured)</td></tr>"
    )
    return (
        f"<table cellpadding='0' style='border-collapse:collapse'>"
        f"<thead><tr>"
        f"<th style='padding:4px;border:1px solid #ccc;text-align:left'>Question</th>"
        f"<th style='padding:4px;border:1px solid #ccc;text-align:left'>Caller answer</th>"
        f"<th style='padding:4px;border:1px solid #ccc;text-align:left'>English summary</th>"
        f"</tr></thead>"
        f"<tbody>{rows_block}</tbody>"
        f"</table>"
    )


def build_message_email(
    message: Message,
    context: DispatchContext,
    *,
    include_transcript: bool = True,
    include_recording_link: bool = True,
    transcript_attached: bool = True,
) -> tuple[str, str, str]:
    """Return (subject, body_text, body_html).

    When `include_transcript=True` (the default) and a markdown transcript
    path exists in the dispatch context, the body notes the transcript
    attachment (filename + on-disk path); the channel layer attaches the
    actual content as a .txt file. The `take_message` flow defers email
    dispatch to call-end so the transcript file is on disk by the time the
    email is composed.
    """
    subject = f"New message from {_subject_safe(message.caller_name)} — {_subject_safe(message.business_name)}"

    body_text = (
        f"A caller left a message for {message.business_name}.\n"
        f"\n"
        f"Caller: {message.caller_name}\n"
        f"Callback: {message.callback_number}\n"
        f"Received: {message.timestamp}\n"
        f"\n"
        f"Message:\n"
        f"{message.message}\n"
    )
    if include_recording_link and context.recording_url:
        body_text += f"\nRecording: {context.recording_url}\n"
    if include_transcript and context.transcript_markdown_path:
        if transcript_attached:
            body_text += f"\nTranscript attached: {transcript_filename(context.call_id)}\n"
            body_text += f"Transcript path: {context.transcript_markdown_path}\n"
        else:
            body_text += f"\nTranscript unavailable — see path: {context.transcript_markdown_path}\n"

    def e(s: str | None) -> str:
        return html.escape(s or "", quote=True)

    body_html = (
        f"<p>A caller left a message for <strong>{e(message.business_name)}</strong>.</p>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Caller</strong></td><td>{e(message.caller_name)}</td></tr>"
        f"<tr><td><strong>Callback</strong></td><td>{e(message.callback_number)}</td></tr>"
        f"<tr><td><strong>Received</strong></td><td>{e(message.timestamp)}</td></tr>"
        f"</table>"
        f"<h3>Message</h3>"
        f"<blockquote>{e(message.message)}</blockquote>"
    )
    if include_recording_link and context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"
    if include_transcript and context.transcript_markdown_path:
        if transcript_attached:
            body_html += (
                f"<p><strong>Transcript attached:</strong> {e(transcript_filename(context.call_id))}"
                f"<br><small>Path: {e(context.transcript_markdown_path)}</small></p>"
            )
        else:
            body_html += (
                f"<p><strong>Transcript unavailable</strong> — see path: "
                f"{e(context.transcript_markdown_path)}</p>"
            )

    return subject, body_text, body_html


def build_info_packet_email(
    packet: InfoPacket, *, business_name: str, call_id: str,
) -> tuple[str, str, str]:
    subject = _subject_safe(packet.email_subject)
    body_text = f"{packet.email_body}\n"
    if packet.links:
        body_text += "\nLinks:\n"
        for link in packet.links:
            body_text += f"- {link.label}: {link.url}\n"
    body_text += f"\nCall ID: {call_id}\n"

    def e(s: object) -> str:
        return html.escape(str(s) if s is not None else "", quote=True)

    body_html = (
        f"<p>{e(packet.email_body).replace(chr(10), '<br>')}</p>"
    )
    if packet.links:
        body_html += "<h3>Links</h3><ul>"
        for link in packet.links:
            body_html += f"<li><a href='{e(link.url)}'>{e(link.label)}</a></li>"
        body_html += "</ul>"
    body_html += f"<p><small>{e(business_name)} call ID: {e(call_id)}</small></p>"
    return subject, body_text, body_html


def build_call_end_email(
    metadata: CallMetadata,
    context: DispatchContext,
    *,
    captured_messages: list[Message] | tuple[Message, ...] | None = None,
    intake_submission: IntakeSubmission | None = None,
    case_type_display: str | None = None,
    ai_summary: str | None = None,
    include_transcript: bool = True,
    include_recording_link: bool = True,
    transcript_attached: bool = True,
) -> tuple[str, str, str]:
    captured_messages = list(captured_messages or [])
    outcomes_str = _outcomes_display(metadata.outcomes)
    caller_pretty = _pretty_phone(metadata.caller_phone)
    caller_name = _caller_display_name(intake_submission, captured_messages)
    callback = _distinct_callback_number(metadata, intake_submission, captured_messages)
    context_label = _call_context_label(
        metadata, intake_submission, case_type_display, captured_messages,
    )
    intake_label: str | None = None
    intake_marker = ""
    if intake_submission is not None:
        intake_label = case_type_display or intake_submission.case_type
        intake_marker = "" if intake_submission.status == "final" else " [PARTIAL]"
    name_part = f" ({_subject_safe(caller_name)})" if caller_name else ""
    subject = (
        f"Call from {_subject_safe(caller_pretty)}{name_part} — "
        f"{_subject_safe(context_label)} [{_subject_safe(metadata.business_name)}]"
    )

    duration_str = _format_duration(metadata.duration_seconds)

    body_text = f"Caller: {caller_pretty}\n"
    if caller_name:
        body_text += f"Caller name: {caller_name}\n"
    if callback:
        body_text += (
            f"Callback number (different from calling number): {_pretty_phone(callback)}\n"
        )
    body_text += (
        f"\n"
        f"Business: {metadata.business_name}\n"
        f"Start: {metadata.start_ts}\n"
        f"Duration: {duration_str}\n"
        f"Outcomes: {outcomes_str}\n"
    )
    if metadata.transfer_target:
        body_text += f"Transferred to: {metadata.transfer_target}\n"
    if metadata.agent_end_reason:
        body_text += f"Agent end reason: {metadata.agent_end_reason}\n"
    if ai_summary:
        body_text += f"\nSummary:\n{ai_summary}\n"
    if intake_submission is not None:
        body_text += (
            f"\nIntake{intake_marker}: {intake_label}\n"
            f"Intake caller: {intake_submission.caller_name}\n"
            f"Intake callback: {_pretty_phone(intake_submission.callback_number)}\n"
            f"Language: {intake_submission.language}\n"
        )
        if intake_submission.english_overview:
            body_text += f"Overview:\n  {intake_submission.english_overview}\n"
        body_text += f"Answers:\n{_intake_answers_text(intake_submission)}\n"
    # Blank line between a Summary/Intake block and the details run below.
    if (ai_summary or intake_submission is not None) and (
        metadata.appointment_details
        or metadata.faqs_answered
        or metadata.languages_detected
        or metadata.info_packet_sends
        or metadata.dtmf_events
    ):
        body_text += "\n"
    if metadata.appointment_details:
        body_text += (
            f"Appointment: {metadata.appointment_details.get('start_iso', '?')}\n"
            f"  {metadata.appointment_details.get('html_link', '')}\n"
        )
    if metadata.faqs_answered:
        body_text += f"FAQs answered: {', '.join(metadata.faqs_answered)}\n"
    if metadata.languages_detected:
        body_text += f"Languages: {', '.join(sorted(metadata.languages_detected))}\n"
    if metadata.info_packet_sends:
        body_text += "Info packets:\n"
        for record in metadata.info_packet_sends:
            status = (
                record.status if record.error is None
                else f"{record.status} ({record.error})"
            )
            body_text += (
                f"- {record.packet_display_name} via {record.channel} "
                f"to {record.destination}: {status}\n"
            )
    if metadata.dtmf_events:
        body_text += "Keypad actions:\n"
        for record in metadata.dtmf_events:
            status = (
                record.status if record.error is None
                else f"{record.status} ({record.error})"
            )
            target = f" -> {record.target}" if record.target else ""
            action = record.action or "-"
            body_text += f"- {record.digit}: {action}{target} [{status}]\n"
    if captured_messages:
        body_text += "\nCaptured Content:\n"
        for idx, msg in enumerate(captured_messages, start=1):
            body_text += (
                f"\n{idx}. Message\n"
                f"Caller: {msg.caller_name}\n"
                f"Callback: {msg.callback_number}\n"
                f"Received: {msg.timestamp}\n"
                f"Message:\n{msg.message}\n"
            )
    if include_recording_link:
        if metadata.recording_failed:
            body_text += f"\nRecording: failed\n"
        elif context.recording_url:
            body_text += f"\nRecording: {context.recording_url}\n"
    if include_transcript and context.transcript_markdown_path:
        if transcript_attached:
            body_text += f"\nTranscript attached: {transcript_filename(context.call_id)}\n"
            body_text += f"Transcript path: {context.transcript_markdown_path}\n"
        else:
            body_text += f"\nTranscript unavailable — see path: {context.transcript_markdown_path}\n"

    def e(s: object) -> str:
        return html.escape(str(s) if s is not None else "", quote=True)

    body_html = (
        f"<h2>Call from {e(caller_pretty)}</h2>"
        f"<table cellpadding='4'>"
    )
    if caller_name:
        body_html += f"<tr><td><strong>Caller name</strong></td><td>{e(caller_name)}</td></tr>"
    if callback:
        body_html += (
            f"<tr><td><strong>Callback number (different from calling number)</strong></td>"
            f"<td>{e(_pretty_phone(callback))}</td></tr>"
        )
    body_html += (
        f"<tr><td><strong>Business</strong></td><td>{e(metadata.business_name)}</td></tr>"
        f"<tr><td><strong>Start</strong></td><td>{e(metadata.start_ts)}</td></tr>"
        f"<tr><td><strong>Duration</strong></td><td>{e(duration_str)}</td></tr>"
        f"<tr><td><strong>Outcomes</strong></td><td>{e(outcomes_str)}</td></tr>"
    )
    if metadata.transfer_target:
        body_html += f"<tr><td><strong>Transferred to</strong></td><td>{e(metadata.transfer_target)}</td></tr>"
    if metadata.agent_end_reason:
        body_html += f"<tr><td><strong>Agent end reason</strong></td><td>{e(metadata.agent_end_reason)}</td></tr>"
    body_html += f"</table>"
    if ai_summary:
        body_html += f"<h3>Summary</h3><p>{e(ai_summary)}</p>"
    if intake_submission is not None:
        body_html += (
            f"<h3>Intake{intake_marker} — {e(intake_label)}</h3>"
            f"<table cellpadding='4'>"
            f"<tr><td><strong>Intake caller</strong></td><td>{e(intake_submission.caller_name)}</td></tr>"
            f"<tr><td><strong>Intake callback</strong></td><td>{e(_pretty_phone(intake_submission.callback_number))}</td></tr>"
            f"<tr><td><strong>Language</strong></td><td>{e(intake_submission.language)}</td></tr>"
            f"</table>"
        )
        if intake_submission.english_overview:
            body_html += (
                f"<p><strong>Overview</strong></p>"
                f"<blockquote>{e(intake_submission.english_overview)}</blockquote>"
            )
        body_html += _intake_answers_html_table(intake_submission)
    details_rows = ""
    if metadata.appointment_details:
        start_iso = metadata.appointment_details.get("start_iso", "?")
        html_link = metadata.appointment_details.get("html_link", "")
        appointment = e(start_iso)
        if html_link:
            appointment += f"<br><a href='{e(html_link)}'>{e(html_link)}</a>"
        details_rows += f"<tr><td><strong>Appointment</strong></td><td>{appointment}</td></tr>"
    if metadata.faqs_answered:
        details_rows += f"<tr><td><strong>FAQs answered</strong></td><td>{e(', '.join(metadata.faqs_answered))}</td></tr>"
    if metadata.languages_detected:
        details_rows += f"<tr><td><strong>Languages</strong></td><td>{e(', '.join(sorted(metadata.languages_detected)))}</td></tr>"
    if details_rows:
        body_html += f"<table cellpadding='4'>{details_rows}</table>"
    if metadata.info_packet_sends:
        rows = []
        for record in metadata.info_packet_sends:
            status = (
                record.status if record.error is None
                else f"{record.status} ({record.error})"
            )
            rows.append(
                "<tr>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(record.packet_display_name)}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(record.channel)}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(record.destination)}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(status)}</td>"
                "</tr>"
            )
        body_html += (
            "<h3>Info packets</h3>"
            "<table cellpadding='0' style='border-collapse:collapse'>"
            "<thead><tr>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Packet</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Channel</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Destination</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Status</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    if metadata.dtmf_events:
        rows = []
        for record in metadata.dtmf_events:
            status = (
                record.status if record.error is None
                else f"{record.status} ({record.error})"
            )
            rows.append(
                "<tr>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(record.digit)}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(record.action or '-')}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(record.target or '-')}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(status)}</td>"
                "</tr>"
            )
        body_html += (
            "<h3>Keypad actions</h3>"
            "<table cellpadding='0' style='border-collapse:collapse'>"
            "<thead><tr>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Digit</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Action</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Target</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Status</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    if captured_messages:
        rows = []
        for msg in captured_messages:
            rows.append(
                "<tr>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(msg.caller_name)}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(msg.callback_number)}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(msg.timestamp)}</td>"
                f"<td style='padding:4px;border:1px solid #ccc'>{e(msg.message)}</td>"
                "</tr>"
            )
        body_html += (
            "<h3>Captured Content</h3>"
            "<table cellpadding='0' style='border-collapse:collapse'>"
            "<thead><tr>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Caller</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Callback</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Received</th>"
            "<th style='padding:4px;border:1px solid #ccc;text-align:left'>Message</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    if include_recording_link:
        if metadata.recording_failed:
            body_html += f"<p><strong>Recording:</strong> failed</p>"
        elif context.recording_url:
            body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"
    if include_transcript and context.transcript_markdown_path:
        if transcript_attached:
            body_html += (
                f"<p><strong>Transcript attached:</strong> {e(transcript_filename(context.call_id))}"
                f"<br><small>Path: {e(context.transcript_markdown_path)}</small></p>"
            )
        else:
            body_html += (
                f"<p><strong>Transcript unavailable</strong> — see path: "
                f"{e(context.transcript_markdown_path)}</p>"
            )

    return subject, body_text, body_html


def build_booking_email(
    metadata: CallMetadata,
    context: DispatchContext,
    *,
    transcript_attached: bool = True,
) -> tuple[str, str, str]:
    """Build email fired by the on_booking trigger. Requires metadata.appointment_details."""
    details = metadata.appointment_details or {}
    start_iso = details.get("start_iso", "?")
    html_link = details.get("html_link", "")
    caller = metadata.caller_phone or "Unknown"

    subject = f"New appointment booked: {_subject_safe(caller)} — {_subject_safe(start_iso)} [{_subject_safe(metadata.business_name)}]"

    body_text = (
        f"A new appointment has been booked for {metadata.business_name}.\n"
        f"\n"
        f"Caller: {caller}\n"
        f"Start: {start_iso}\n"
        f"End: {details.get('end_iso', '?')}\n"
        f"Event: {html_link}\n"
        f"Call ID: {metadata.call_id}\n"
        f"\n"
        f"Note: The caller's identity was NOT verified. Please confirm by calling "
        f"back at {caller} before relying on this booking.\n"
    )
    if context.transcript_markdown_path:
        if transcript_attached:
            body_text += f"\nTranscript attached: {transcript_filename(context.call_id)}\n"
            body_text += f"Transcript path: {context.transcript_markdown_path}\n"
        else:
            body_text += f"\nTranscript unavailable — see path: {context.transcript_markdown_path}\n"
    if context.recording_url:
        body_text += f"Recording: {context.recording_url}\n"

    def e(s: object) -> str:
        return html.escape(str(s) if s is not None else "", quote=True)

    body_html = (
        f"<h2>New appointment booked — {e(metadata.business_name)}</h2>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Caller</strong></td><td>{e(caller)}</td></tr>"
        f"<tr><td><strong>Start</strong></td><td>{e(start_iso)}</td></tr>"
        f"<tr><td><strong>End</strong></td><td>{e(details.get('end_iso', '?'))}</td></tr>"
        f"<tr><td><strong>Call ID</strong></td><td>{e(metadata.call_id)}</td></tr>"
        f"</table>"
    )
    if html_link:
        body_html += f"<p><a href='{e(html_link)}'>Open in Google Calendar</a></p>"
    body_html += (
        f"<p><em>The caller's identity was NOT verified. Please confirm by calling back "
        f"at {e(caller)} before relying on this booking.</em></p>"
    )
    if context.transcript_markdown_path:
        if transcript_attached:
            body_html += (
                f"<p><strong>Transcript attached:</strong> {e(transcript_filename(context.call_id))}"
                f"<br><small>Path: {e(context.transcript_markdown_path)}</small></p>"
            )
        else:
            body_html += (
                f"<p><strong>Transcript unavailable</strong> — see path: "
                f"{e(context.transcript_markdown_path)}</p>"
            )
    if context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"

    return subject, body_text, body_html


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def build_intake_email(
    submission: IntakeSubmission,
    context: DispatchContext,
    *,
    case_type_display: str | None = None,
    include_transcript: bool = True,
    include_recording_link: bool = True,
    transcript_attached: bool = True,
) -> tuple[str, str, str]:
    """Render the email sent at call-end for a completed intake.

    `submission` is a `receptionist.intakes.models.IntakeSubmission`.
    `case_type_display` is the human-readable case type label (e.g.
    "Workers' Compensation"). When omitted, the raw `case_type` key is
    used — operators always see something, even if the YAML hasn't been
    updated with a display_name.
    """
    label = case_type_display or submission.case_type
    status_marker = "" if submission.status == "final" else " [PARTIAL]"
    subject = (
        f"Intake{status_marker}: {label} — {_subject_safe(submission.caller_name)} "
        f"[{_subject_safe(submission.business_name)}]"
    )

    body_text = (
        f"A new-client intake has been completed for {submission.business_name}.\n"
        f"\n"
        f"Case type: {label}\n"
        f"Status: {submission.status}\n"
        f"Caller: {submission.caller_name}\n"
        f"Callback: {submission.callback_number}\n"
        f"Language: {submission.language}\n"
        f"Started: {submission.started_at}\n"
        f"Completed: {submission.completed_at or '(in progress)'}\n"
        f"\n"
    )
    if submission.english_overview:
        body_text += f"Overview:\n  {submission.english_overview}\n\n"
    body_text += f"Answers:\n{_intake_answers_text(submission)}\n"

    if include_recording_link and context.recording_url:
        body_text += f"\nRecording: {context.recording_url}\n"
    if include_transcript and context.transcript_markdown_path:
        if transcript_attached:
            body_text += f"\nTranscript attached: {transcript_filename(context.call_id)}\n"
            body_text += f"Transcript path: {context.transcript_markdown_path}\n"
        else:
            body_text += f"\nTranscript unavailable — see path: {context.transcript_markdown_path}\n"

    def e(s: str | None) -> str:
        return html.escape(s or "", quote=True)

    body_html = (
        f"<h2>New-client intake{e(status_marker)}</h2>"
        f"<p><strong>Business:</strong> {e(submission.business_name)}</p>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Case type</strong></td><td>{e(label)}</td></tr>"
        f"<tr><td><strong>Status</strong></td><td>{e(submission.status)}</td></tr>"
        f"<tr><td><strong>Caller</strong></td><td>{e(submission.caller_name)}</td></tr>"
        f"<tr><td><strong>Callback</strong></td><td>{e(submission.callback_number)}</td></tr>"
        f"<tr><td><strong>Language</strong></td><td>{e(submission.language)}</td></tr>"
        f"<tr><td><strong>Started</strong></td><td>{e(submission.started_at)}</td></tr>"
        f"<tr><td><strong>Completed</strong></td>"
        f"<td>{e(submission.completed_at or '(in progress)')}</td></tr>"
        f"</table>"
    )
    if submission.english_overview:
        body_html += (
            f"<h3>Overview</h3>"
            f"<blockquote>{e(submission.english_overview)}</blockquote>"
        )
    body_html += f"<h3>Answers</h3>{_intake_answers_html_table(submission)}"
    if include_recording_link and context.recording_url:
        body_html += (
            f"<p><strong>Recording:</strong> "
            f"<a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"
        )
    if include_transcript and context.transcript_markdown_path:
        if transcript_attached:
            body_html += (
                f"<p><strong>Transcript attached:</strong> {e(transcript_filename(context.call_id))}"
                f"<br><small>Path: {e(context.transcript_markdown_path)}</small></p>"
            )
        else:
            body_html += (
                f"<p><strong>Transcript unavailable</strong> — see path: "
                f"{e(context.transcript_markdown_path)}</p>"
            )

    return subject, body_text, body_html
