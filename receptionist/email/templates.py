# receptionist/email/templates.py
from __future__ import annotations

import html

from receptionist.messaging.models import Message, DispatchContext
from receptionist.transcript.metadata import CallMetadata


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
    outcome_display = {
        "transferred": "Transferred",
        "message_taken": "Message taken",
        "hung_up": "Hung up",
    }.get(metadata.outcome or "hung_up", metadata.outcome or "unknown")

    subject = f"Call from {metadata.caller_phone or 'Unknown'} — {outcome_display} [{metadata.business_name}]"

    duration_str = _format_duration(metadata.duration_seconds)

    body_text = (
        f"Call summary for {metadata.business_name}.\n"
        f"\n"
        f"Caller: {metadata.caller_phone or 'Unknown'}\n"
        f"Start: {metadata.start_ts}\n"
        f"End: {metadata.end_ts or '(in progress)'}\n"
        f"Duration: {duration_str}\n"
        f"Outcome: {outcome_display}\n"
    )
    if metadata.transfer_target:
        body_text += f"Transferred to: {metadata.transfer_target}\n"
    if metadata.faqs_answered:
        body_text += f"FAQs answered: {', '.join(metadata.faqs_answered)}\n"
    if metadata.languages_detected:
        body_text += f"Languages: {', '.join(sorted(metadata.languages_detected))}\n"
    if context.recording_url:
        body_text += f"\nRecording: {context.recording_url}\n"
    if context.transcript_markdown_path:
        body_text += f"Transcript: {context.transcript_markdown_path}\n"

    def e(s) -> str:
        return html.escape(str(s) if s is not None else "", quote=True)

    body_html = (
        f"<h2>Call summary — {e(metadata.business_name)}</h2>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Caller</strong></td><td>{e(metadata.caller_phone or 'Unknown')}</td></tr>"
        f"<tr><td><strong>Start</strong></td><td>{e(metadata.start_ts)}</td></tr>"
        f"<tr><td><strong>End</strong></td><td>{e(metadata.end_ts or '(in progress)')}</td></tr>"
        f"<tr><td><strong>Duration</strong></td><td>{e(duration_str)}</td></tr>"
        f"<tr><td><strong>Outcome</strong></td><td>{e(outcome_display)}</td></tr>"
        f"</table>"
    )
    if context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"

    return subject, body_text, body_html


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
