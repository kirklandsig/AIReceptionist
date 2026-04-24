# receptionist/lifecycle.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from receptionist.config import BusinessConfig
from receptionist.messaging.models import DispatchContext
from receptionist.recording.egress import (
    RecordingArtifact, RecordingHandle, start_recording, stop_recording,
)
from receptionist.transcript.capture import TranscriptCapture
from receptionist.transcript.metadata import CallMetadata
from receptionist.transcript.writer import (
    TranscriptWriteResult, write_transcript_files,
)

logger = logging.getLogger("receptionist")

# Outcome priority (higher wins). Used when a later event would otherwise
# overwrite a more informative earlier outcome.
_OUTCOME_PRIORITY = {
    None: 0,
    "hung_up": 1,
    "message_taken": 2,
    "transferred": 3,
}


class CallLifecycle:
    """Owns per-call state and the disconnect-time fan-out.

    Constructed at call-start. `Receptionist` and `TranscriptCapture` push
    events into this object; `on_call_ended` reads them, writes artifacts,
    and fires the call-end email trigger if configured.
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

    # --- tool-path recorders (called by Receptionist methods) ---

    def record_faq_answered(self, question: str) -> None:
        self.metadata.faqs_answered.append(question)

    def record_transfer(self, department_name: str) -> None:
        self.metadata.transfer_target = department_name
        self._set_outcome("transferred")

    def record_message_taken(self) -> None:
        self.metadata.message_taken = True
        self._set_outcome("message_taken")

    def _set_outcome(self, outcome: str) -> None:
        current_prio = _OUTCOME_PRIORITY.get(self.metadata.outcome, 0)
        new_prio = _OUTCOME_PRIORITY.get(outcome, 0)
        if new_prio > current_prio:
            self.metadata.outcome = outcome

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

        if self.config.email and self.config.email.triggers.on_call_end:
            await self._fire_call_end_email(artifact, transcript_result)

    async def _fire_call_end_email(
        self,
        artifact: RecordingArtifact | None,
        transcript_result: TranscriptWriteResult | None,
    ) -> None:
        """Call-end email goes only to EmailChannel targets (file/webhook ignored at this trigger)."""
        from receptionist.config import EmailChannel as EmailChannelConfig
        from receptionist.messaging.channels.email import EmailChannel

        email_channels = [c for c in self.config.messages.channels if isinstance(c, EmailChannelConfig)]
        if not email_channels or self.config.email is None:
            logger.info("on_call_end trigger configured but no email channel in messages.channels")
            return

        context = DispatchContext(
            transcript_json_path=str(transcript_result.json_path) if transcript_result and transcript_result.json_path else None,
            transcript_markdown_path=str(transcript_result.markdown_path) if transcript_result and transcript_result.markdown_path else None,
            recording_url=artifact.url if artifact else None,
            call_id=self.metadata.call_id,
            business_name=self.metadata.business_name,
        )

        for ch_cfg in email_channels:
            channel = EmailChannel(ch_cfg, self.config.email)
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
