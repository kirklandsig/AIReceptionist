# receptionist/lifecycle.py
from __future__ import annotations

import logging
from typing import Any

from receptionist.config import BusinessConfig
from receptionist.messaging.models import DispatchContext
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

    def record_faq_answered(self, question: str) -> None:
        self.metadata.faqs_answered.append(question)

    def record_transfer(self, department_name: str) -> None:
        self.metadata.transfer_target = department_name
        self._add_outcome("transferred")

    def record_message_taken(self) -> None:
        self.metadata.message_taken = True
        self._add_outcome("message_taken")

    def record_appointment_booked(self, details: dict) -> None:
        """Called by the book_appointment tool after a successful event.insert.

        `details` must contain: event_id, start_iso, end_iso, html_link.
        """
        self.metadata.appointment_booked = True
        self.metadata.appointment_details = details
        self._add_outcome("appointment_booked")

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
        self.metadata.mark_finalized()

        artifact: RecordingArtifact | None = None
        if self.recording_handle is not None:
            artifact = await stop_recording(self.recording_handle)
            if artifact is not None:
                self.metadata.recording_artifact = artifact.url

        transcript_result: TranscriptWriteResult | None = None
        segments = self.transcript_capture.segments if self.transcript_capture else []
        if self.config.transcripts is not None:
            transcript_result = await write_transcript_files(
                self.config.transcripts, self.metadata, segments
            )

        # Fan out email triggers
        if self.config.email:
            if self.config.email.triggers.on_call_end:
                await self._fire_call_end_email(artifact, transcript_result)
            if self.config.email.triggers.on_booking and self.metadata.appointment_booked:
                await self._fire_booking_email(artifact, transcript_result)

    async def _fire_call_end_email(
        self,
        artifact: RecordingArtifact | None,
        transcript_result: TranscriptWriteResult | None,
    ) -> None:
        """Call-end email goes to every EmailChannel target in messages.channels."""
        if not self._email_channels:
            logger.info("on_call_end trigger configured but no email channel in messages.channels")
            return
        context = self._build_dispatch_context(artifact, transcript_result)
        for channel in self._email_channels:
            try:
                await channel.deliver_call_end(self.metadata, context)
            except Exception as e:
                logger.error(
                    "Call-end email failed: %s", e,
                    extra={
                        "call_id": self.metadata.call_id,
                        "business_name": self.metadata.business_name,
                        "component": "lifecycle.call_end_email",
                    },
                )

    async def _fire_booking_email(
        self,
        artifact: RecordingArtifact | None,
        transcript_result: TranscriptWriteResult | None,
    ) -> None:
        """Booking email — fires only when metadata.appointment_booked is true."""
        if not self._email_channels:
            logger.info("on_booking trigger configured but no email channel in messages.channels")
            return
        context = self._build_dispatch_context(artifact, transcript_result)
        for channel in self._email_channels:
            try:
                await channel.deliver_booking(self.metadata, context)
            except Exception as e:
                logger.error(
                    "Booking email failed: %s", e,
                    extra={
                        "call_id": self.metadata.call_id,
                        "business_name": self.metadata.business_name,
                        "component": "lifecycle.booking_email",
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
