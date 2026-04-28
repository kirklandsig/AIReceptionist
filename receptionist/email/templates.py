# receptionist/email/templates.py
from __future__ import annotations

import html

from receptionist.messaging.models import Message, DispatchContext
from receptionist.transcript.metadata import CallMetadata


# Human-readable display labels for outcome values. Keep in sync with
# VALID_OUTCOMES in receptionist/transcript/metadata.py.
_OUTCOME_LABELS = {
    "hung_up": "Hung up",
    "message_taken": "Message taken",
    "transferred": "Transferred",
    "appointment_booked": "Appointment booked",
}


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


def build_message_email(
    message: Message, context: DispatchContext
) -> tuple[str, str, str]:
    """Return (subject, body_text, body_html)."""
    subject = f"New message from {message.caller_name} — {message.business_name}"

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
    if context.recording_url:
        body_text += f"\nRecording: {context.recording_url}\n"
    if context.transcript_markdown_path:
        body_text += f"Transcript: {context.transcript_markdown_path}\n"

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
    if context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"
    if context.transcript_markdown_path:
        body_html += f"<p><strong>Transcript:</strong> {e(context.transcript_markdown_path)}</p>"

    return subject, body_text, body_html


def build_call_end_email(
    metadata: CallMetadata, context: DispatchContext
) -> tuple[str, str, str]:
    outcomes_str = _outcomes_display(metadata.outcomes)
    subject_outcomes = _outcomes_display(
        metadata.outcomes, transfer_target=metadata.transfer_target,
    )
    subject = f"Call from {metadata.caller_phone or 'Unknown'} — {subject_outcomes} [{metadata.business_name}]"

    duration_str = _format_duration(metadata.duration_seconds)

    body_text = (
        f"Call summary for {metadata.business_name}.\n"
        f"\n"
        f"Caller: {metadata.caller_phone or 'Unknown'}\n"
        f"Start: {metadata.start_ts}\n"
        f"End: {metadata.end_ts or '(in progress)'}\n"
        f"Duration: {duration_str}\n"
        f"Outcomes: {outcomes_str}\n"
    )
    if metadata.transfer_target:
        body_text += f"Transferred to: {metadata.transfer_target}\n"
    if metadata.appointment_details:
        body_text += (
            f"Appointment: {metadata.appointment_details.get('start_iso', '?')}\n"
            f"  {metadata.appointment_details.get('html_link', '')}\n"
        )
    if metadata.faqs_answered:
        body_text += f"FAQs answered: {', '.join(metadata.faqs_answered)}\n"
    if metadata.languages_detected:
        body_text += f"Languages: {', '.join(sorted(metadata.languages_detected))}\n"
    if metadata.recording_failed:
        body_text += f"\nRecording: failed\n"
    elif context.recording_url:
        body_text += f"\nRecording: {context.recording_url}\n"
    if context.transcript_markdown_path:
        body_text += f"Transcript: {context.transcript_markdown_path}\n"

    def e(s: object) -> str:
        return html.escape(str(s) if s is not None else "", quote=True)

    body_html = (
        f"<h2>Call summary — {e(metadata.business_name)}</h2>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Caller</strong></td><td>{e(metadata.caller_phone or 'Unknown')}</td></tr>"
        f"<tr><td><strong>Start</strong></td><td>{e(metadata.start_ts)}</td></tr>"
        f"<tr><td><strong>End</strong></td><td>{e(metadata.end_ts or '(in progress)')}</td></tr>"
        f"<tr><td><strong>Duration</strong></td><td>{e(duration_str)}</td></tr>"
        f"<tr><td><strong>Outcomes</strong></td><td>{e(outcomes_str)}</td></tr>"
    )
    if metadata.transfer_target:
        body_html += f"<tr><td><strong>Transferred to</strong></td><td>{e(metadata.transfer_target)}</td></tr>"
    if metadata.appointment_details:
        start_iso = metadata.appointment_details.get("start_iso", "?")
        html_link = metadata.appointment_details.get("html_link", "")
        appointment = e(start_iso)
        if html_link:
            appointment += f"<br><a href='{e(html_link)}'>{e(html_link)}</a>"
        body_html += f"<tr><td><strong>Appointment</strong></td><td>{appointment}</td></tr>"
    if metadata.faqs_answered:
        body_html += f"<tr><td><strong>FAQs answered</strong></td><td>{e(', '.join(metadata.faqs_answered))}</td></tr>"
    if metadata.languages_detected:
        body_html += f"<tr><td><strong>Languages</strong></td><td>{e(', '.join(sorted(metadata.languages_detected)))}</td></tr>"
    body_html += f"</table>"
    if metadata.recording_failed:
        body_html += f"<p><strong>Recording:</strong> failed</p>"
    elif context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"
    if context.transcript_markdown_path:
        body_html += f"<p><strong>Transcript:</strong> {e(context.transcript_markdown_path)}</p>"

    return subject, body_text, body_html


def build_booking_email(
    metadata: CallMetadata, context: DispatchContext
) -> tuple[str, str, str]:
    """Build email fired by the on_booking trigger. Requires metadata.appointment_details."""
    details = metadata.appointment_details or {}
    start_iso = details.get("start_iso", "?")
    html_link = details.get("html_link", "")
    caller = metadata.caller_phone or "Unknown"

    subject = f"New appointment booked: {caller} — {start_iso} [{metadata.business_name}]"

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
        body_text += f"\nCall transcript: {context.transcript_markdown_path}\n"
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
        body_html += f"<p><strong>Transcript:</strong> {e(context.transcript_markdown_path)}</p>"
    if context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"

    return subject, body_text, body_html


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
