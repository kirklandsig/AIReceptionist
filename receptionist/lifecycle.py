# receptionist/lifecycle.py
from __future__ import annotations

import logging
from typing import Any

from receptionist.config import BusinessConfig
from receptionist.messaging.models import DispatchContext, Message
from receptionist.recording.egress import (
    RecordingArtifact, RecordingHandle, start_recording, stop_recording,
)
from receptionist.transcript.capture import TranscriptCapture
from receptionist.transcript.metadata import CallMetadata, VALID_OUTCOMES
from receptionist.transcript.writer import (
    TranscriptWriteResult, write_transcript_files,
)

logger = logging.getLogger("receptionist")


class CallLifecycle:
    """Owns per-call state and the disconnect-time fan-out.

    Multi-outcome capable: a call that both transfers AND books an appointment
    records both in metadata.outcomes. No priority-based "winner" selection.
    """

    def __init__(
        self,
        *,
        config: BusinessConfig,
        call_id: str,
        caller_phone: str | None,
    ) -> None:
        self.config = config
        self.metadata = CallMetadata(
            call_id=call_id,
            business_name=config.business.name,
            caller_phone=caller_phone,
        )
        self.transcript_capture: TranscriptCapture | None = None
        self.recording_handle: RecordingHandle | None = None
        # Pre-build email channel instances if any email triggers are enabled,
        # so the call-end fan-out doesn't reconstruct them per fire.
        self._email_channels = self._build_email_channels()
        # take_message defers its email portion to call-end time so the full
        # transcript can be embedded. Each enqueued Message is fired once via
        # every configured EmailChannel during on_call_ended, AFTER the
        # transcript files have been written.
        self._pending_message_emails: list[Message] = []
        # Guard against double-firing the end-of-call fan-out. The
        # agent-initiated end_call path explicitly invokes on_call_ended
        # before removing the SIP participant (so emails fire while the
        # asyncio executor is still healthy); the LiveKit session-close
        # handler then invokes it again on natural disconnect. The second
        # call must be a no-op or operators receive duplicate emails.
        self._finalized: bool = False

    def _build_email_channels(self) -> list:
        """Pre-construct EmailChannel instances when email triggers will need them.

        Returns [] when there are no email channels in messages.channels or no
        top-level email config (the cross-section validator in config.py
        guarantees those go together when triggers are on).
        """
        if self.config.email is None:
            return []
        from receptionist.config import EmailChannel as EmailChannelConfig
        from receptionist.messaging.channels.email import EmailChannel
        ch_cfgs = [
            c for c in self.config.messages.channels
            if isinstance(c, EmailChannelConfig)
        ]
        return [EmailChannel(c, self.config.email) for c in ch_cfgs]

    # --- tool-path recorders (called by Receptionist methods) ---

    def set_caller_phone(self, phone: str) -> None:
        if phone and self.metadata.caller_phone is None:
            self.metadata.caller_phone = phone

    def record_faq_answered(self, question: str) -> None:
        self.metadata.faqs_answered.append(question)

    def record_transfer(self, department_name: str) -> None:
        self.metadata.transfer_target = department_name
        self._add_outcome("transferred")

    def record_message_taken(self) -> None:
        self.metadata.message_taken = True
        self._add_outcome("message_taken")

    def enqueue_message_email(self, message: Message) -> None:
        """Queue a Message for email dispatch at call-end.

        The file/webhook channels fire synchronously from the take_message
        tool path (so the caller hears immediate confirmation and the data
        is durable on disk). The email portion is queued here and drained
        in on_call_ended() with a DispatchContext that includes the real
        transcript path, so the email template can embed the full
        conversation. Without this deferral the email would fire mid-call
        and the transcript file would not yet exist.
        """
        self._pending_message_emails.append(message)

    def record_appointment_booked(self, details: dict) -> None:
        """Called by the book_appointment tool after a successful event.insert.

        `details` must contain: event_id, start_iso, end_iso, html_link.
        """
        self.metadata.appointment_booked = True
        self.metadata.appointment_details = details
        self._add_outcome("appointment_booked")

    def record_agent_ended(self, reason: str) -> None:
        """Called when the agent itself decides to end the call (issues #10/#11).

        `reason` is a short label such as `caller_goodbye`,
        `silence_timeout`, `max_duration_reached`, or
        `unproductive_turns_exhausted`. Stored on the
        metadata so call summaries, transcripts, and dashboards can
        distinguish *why* the agent hung up. The first reason wins so the
        most actionable signal is preserved if multiple end paths fire
        concurrently (e.g. silence timeout racing with a goodbye).
        """
        if self.metadata.agent_end_reason is None:
            self.metadata.agent_end_reason = reason
        self._add_outcome("agent_ended")

    def _add_outcome(self, outcome: str) -> None:
        # Explicit membership check prevents silent drops if a future outcome
        # is added without updating VALID_OUTCOMES.
        if outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"Unknown outcome {outcome!r}; add it to VALID_OUTCOMES in "
                f"receptionist/transcript/metadata.py"
            )
        self.metadata.outcomes.add(outcome)

    # --- artifact wiring ---

    def attach_transcript_capture(self, session: Any) -> None:
        if self.config.transcripts and self.config.transcripts.enabled:
            self.transcript_capture = TranscriptCapture(session, self.metadata)

    async def start_recording_if_enabled(self, room_name: str) -> None:
        if self.config.recording is None or not self.config.recording.enabled:
            return
        self.recording_handle = await start_recording(
            room_name=room_name,
            config=self.config.recording,
            call_id=self.metadata.call_id,
        )
        if self.recording_handle is None:
            self.metadata.recording_failed = True

    # --- disconnect ---

    async def on_call_ended(self) -> None:
        # Idempotent: agent-initiated end_call invokes this explicitly before
        # tearing down the SIP leg (so emails fire while the executor is
        # alive), and the LiveKit session-close handler will then call it
        # again on natural disconnect. The second invocation must do nothing.
        logger.info(
            "on_call_ended entered (finalized=%s, pending_emails=%d, channels=%d)",
            self._finalized,
            len(self._pending_message_emails),
            len(self._email_channels),
            extra={
                "call_id": self.metadata.call_id,
                "business_name": self.metadata.business_name,
                "component": "lifecycle.on_call_ended",
            },
        )
        if self._finalized:
            logger.info(
                "on_call_ended: already finalized, skipping",
                extra={
                    "call_id": self.metadata.call_id,
                    "business_name": self.metadata.business_name,
                    "component": "lifecycle.finalized",
                },
            )
            return
        self._finalized = True
        self.metadata.mark_finalized()

        artifact: RecordingArtifact | None = None
        if self.recording_handle is not None:
            try:
                artifact = await stop_recording(self.recording_handle)
                if artifact is not None:
                    self.metadata.recording_artifact = artifact.url
            except Exception:
                logger.exception(
                    "stop_recording failed during call finalization",
                    extra={
                        "call_id": self.metadata.call_id,
                        "business_name": self.metadata.business_name,
                        "component": "lifecycle.recording",
                    },
                )

        transcript_result: TranscriptWriteResult | None = None
        segments = self.transcript_capture.segments if self.transcript_capture else []
        if self.config.transcripts is not None:
            try:
                transcript_result = await write_transcript_files(
                    self.config.transcripts, self.metadata, segments
                )
            except Exception:
                logger.exception(
                    "write_transcript_files failed during call finalization",
                    extra={
                        "call_id": self.metadata.call_id,
                        "business_name": self.metadata.business_name,
                        "component": "lifecycle.transcript",
                    },
                )

        # Fan out email triggers
        if self.config.email:
            # Deferred message emails go first: they're a per-take_message
            # invocation, and we want them paired with the same transcript
            # context the call-end and booking emails get.
            if (
                self.config.email.triggers.on_message
                and self._pending_message_emails
                and self._email_channels
            ):
                context = self._build_dispatch_context(artifact, transcript_result)
                for msg in self._pending_message_emails:
                    for channel in self._email_channels:
                        try:
                            await channel.deliver(msg, context)
                            logger.info(
                                "Deferred message email sent",
                                extra={
                                    "call_id": self.metadata.call_id,
                                    "business_name": self.metadata.business_name,
                                    "component": "lifecycle.message_email",
                                },
                            )
                        except Exception as e:
                            logger.error(
                                "Deferred message email failed: %s", e,
                                extra={
                                    "call_id": self.metadata.call_id,
                                    "business_name": self.metadata.business_name,
                                    "component": "lifecycle.message_email",
                                },
                            )
            # Always clear the pending queue once finalization runs, even if
            # email is disabled or channels are missing — the lifecycle is
            # finalized exactly once, so a leftover queue can only mislead
            # operators reading lifecycle state in tests/diagnostics.
            self._pending_message_emails.clear()
            if self.config.email.triggers.on_call_end:
                await self._fire_email_trigger(
                    "call_end", lambda ch, ctx: ch.deliver_call_end(self.metadata, ctx),
                    artifact, transcript_result,
                )
            if self.config.email.triggers.on_booking and self.metadata.appointment_booked:
                await self._fire_email_trigger(
                    "booking", lambda ch, ctx: ch.deliver_booking(self.metadata, ctx),
                    artifact, transcript_result,
                )

    async def _fire_email_trigger(
        self,
        trigger_name: str,
        deliver: Any,  # callable: (EmailChannel, DispatchContext) -> Awaitable[None]
        artifact: RecordingArtifact | None,
        transcript_result: TranscriptWriteResult | None,
    ) -> None:
        """Fan out one trigger across the cached email channels.

        `trigger_name` is used in the no-channels log line and component label.
        `deliver` is the bound EmailChannel method to call (deliver_call_end
        or deliver_booking) — kept as a callable so this helper doesn't need
        to know which one fires.
        """
        if not self._email_channels:
            logger.info(
                "on_%s trigger configured but no email channel in messages.channels",
                trigger_name,
            )
            return
        context = self._build_dispatch_context(artifact, transcript_result)
        for channel in self._email_channels:
            try:
                await deliver(channel, context)
            except Exception as e:
                logger.error(
                    "%s email failed: %s", trigger_name.replace("_", "-").capitalize(), e,
                    extra={
                        "call_id": self.metadata.call_id,
                        "business_name": self.metadata.business_name,
                        "component": f"lifecycle.{trigger_name}_email",
                    },
                )

    def _build_dispatch_context(
        self,
        artifact: RecordingArtifact | None,
        transcript_result: TranscriptWriteResult | None,
    ) -> DispatchContext:
        return DispatchContext(
            transcript_json_path=str(transcript_result.json_path) if transcript_result and transcript_result.json_path else None,
            transcript_markdown_path=str(transcript_result.markdown_path) if transcript_result and transcript_result.markdown_path else None,
            recording_url=artifact.url if artifact else None,
            call_id=self.metadata.call_id,
            business_name=self.metadata.business_name,
        )
