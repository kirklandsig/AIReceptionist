# receptionist/agent.py
from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from livekit import agents, api, rtc
from livekit.agents import (
    AgentServer, AgentSession, Agent, RunContext,
    function_tool, room_io, get_job_context,
)
from livekit.plugins import openai, noise_cancellation

from receptionist.config import BusinessConfig, load_config
from receptionist.lifecycle import CallLifecycle
from receptionist.messaging.dispatcher import Dispatcher
from receptionist.messaging.models import DispatchContext, Message
from receptionist.prompts import build_system_prompt

load_dotenv(".env.local")
load_dotenv(".env")

logger = logging.getLogger("receptionist")

DEFAULT_CONFIG_DIR = Path("config/businesses")


def _format_friendly_date(dt) -> str:
    """Cross-platform 'Monday, April 28 at 2:00 PM'."""
    if platform.system() == "Windows":
        return dt.strftime("%A, %B %#d at %#I:%M %p")
    return dt.strftime("%A, %B %-d at %-I:%M %p")


def load_business_config(ctx: agents.JobContext) -> BusinessConfig:
    """Load business config based on job metadata or default to first config found."""
    metadata = {}
    if ctx.job.metadata:
        try:
            metadata = json.loads(ctx.job.metadata)
        except json.JSONDecodeError:
            logger.warning("Failed to parse job metadata as JSON")

    config_name = metadata.get("config", None)

    if config_name:
        if not re.match(r"^[a-zA-Z0-9_-]+$", config_name):
            raise ValueError(f"Invalid config name in job metadata: {config_name!r}")
        config_path = DEFAULT_CONFIG_DIR / f"{config_name}.yaml"
    else:
        yaml_files = sorted(DEFAULT_CONFIG_DIR.glob("*.yaml"))
        if not yaml_files:
            raise FileNotFoundError(f"No config files found in {DEFAULT_CONFIG_DIR}")
        config_path = yaml_files[0]
        logger.info(f"No config specified, using: {config_path.name}")

    return load_config(config_path)


def _get_caller_identity(ctx: agents.JobContext) -> str:
    """Get the SIP caller's participant identity from the room."""
    for participant in ctx.room.remote_participants.values():
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            return participant.identity
    logger.warning("No SIP participant found in room %s", ctx.room.name)
    return ""


def _get_caller_phone(ctx: agents.JobContext) -> str | None:
    """Best-effort extract caller phone number from SIP participant attributes.

    LiveKit SIP participants expose `sip.phoneNumber` in their attributes
    dict. If absent (older LiveKit versions or non-standard trunk
    configurations), returns None — caller phone appears as "Unknown"
    in call-end emails. Not a hard failure.
    """
    for participant in ctx.room.remote_participants.values():
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            attrs = getattr(participant, "attributes", {}) or {}
            phone = attrs.get("sip.phoneNumber")
            if phone:
                return phone
    return None


class Receptionist(Agent):
    def __init__(self, config: BusinessConfig, lifecycle: CallLifecycle) -> None:
        super().__init__(instructions=build_system_prompt(config))
        self.config = config
        self.lifecycle = lifecycle
        # Session-scoped cache of slot ISO strings offered to the caller via
        # check_availability. book_appointment rejects any proposed_start_iso
        # that isn't in this set — prevents the LLM from hallucinating times.
        self._offered_slots: set[str] = set()
        # Lazily-constructed on first calendar tool call; reused for the rest
        # of the call so we don't pay Google's auth cost per tool invocation.
        self._calendar_client = None

    def _get_calendar_client(self):
        """Lazily construct and cache the Google Calendar client for this call."""
        if self._calendar_client is None:
            if self.config.calendar is None or not self.config.calendar.enabled:
                raise RuntimeError(
                    "Calendar tools were called but config.calendar is not enabled."
                )
            from receptionist.booking.auth import build_credentials
            from receptionist.booking.client import GoogleCalendarClient
            creds = build_credentials(self.config.calendar.auth)
            self._calendar_client = GoogleCalendarClient(
                creds, calendar_id=self.config.calendar.calendar_id,
            )
        return self._calendar_client

    async def on_enter(self) -> None:
        # If recording is enabled with a consent preamble, speak the preamble
        # FIRST so the caller is notified before the greeting (design §4.2 —
        # two-party consent jurisdictions).
        recording = self.config.recording
        if (
            recording is not None
            and recording.enabled
            and recording.consent_preamble.enabled
        ):
            # Use triple quotes so apostrophes/quotes inside the preamble
            # text don't break the surrounding f-string delimiter.
            preamble_text = recording.consent_preamble.text
            await self.session.generate_reply(
                instructions=f"""Say exactly this, verbatim, before anything else:
{preamble_text}"""
            )

        greeting_text = self.config.greeting
        await self.session.generate_reply(
            instructions=f"""Greet the caller with:
{greeting_text}"""
        )

    @function_tool()
    async def lookup_faq(self, ctx: RunContext, question: str) -> str:
        """Look up the answer to a frequently asked question about the business."""
        for faq in self.config.faqs:
            if question.lower() in faq.question.lower() or faq.question.lower() in question.lower():
                self.lifecycle.record_faq_answered(faq.question)
                return faq.answer
        return "No exact FAQ match found. Use your knowledge from the system prompt to answer."

    @function_tool()
    async def transfer_call(self, ctx: RunContext, department: str) -> str:
        """Transfer the caller to a specific department or person."""
        target = None
        for entry in self.config.routing:
            if entry.name.lower() == department.lower():
                target = entry
                break

        if target is None:
            available = ", ".join(e.name for e in self.config.routing)
            return f"Department '{department}' not found. Available departments: {available}"

        await ctx.session.generate_reply(
            instructions=f"Tell the caller you're transferring them to {target.name} now."
        )

        job_ctx = get_job_context()
        try:
            await job_ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job_ctx.room.name,
                    participant_identity=_get_caller_identity(job_ctx),
                    transfer_to=f"tel:{target.number}",
                )
            )
            self.lifecycle.record_transfer(target.name)
            return f"Call transferred to {target.name}"
        except Exception as e:
            logger.error(f"Failed to transfer call to {target.name}: {e}")
            return f"Sorry, I wasn't able to transfer the call to {target.name}. Please ask the caller to try calling directly."

    @function_tool()
    async def take_message(
        self, ctx: RunContext, caller_name: str, message: str, callback_number: str
    ) -> str:
        """Take a message from the caller."""
        msg = Message(
            caller_name=caller_name,
            callback_number=callback_number,
            message=message,
            business_name=self.config.business.name,
        )
        dispatcher = Dispatcher(
            channels=self.config.messages.channels,
            business_name=self.config.business.name,
            email_config=self.config.email,
        )
        try:
            await dispatcher.dispatch_message(
                msg, DispatchContext(
                    business_name=self.config.business.name,
                    call_id=self.lifecycle.metadata.call_id,
                ),
            )
        except Exception as e:
            logger.error("take_message: synchronous dispatch failed: %s", e)
            return "I'm having trouble saving messages right now. Would you like me to transfer you to someone instead?"

        self.lifecycle.record_message_taken()
        return f"Message saved from {caller_name}. Let them know their message has been recorded and someone will get back to them."

    @function_tool()
    async def get_business_hours(self, ctx: RunContext) -> str:
        """Check the current business hours and whether the business is open right now."""
        tz = ZoneInfo(self.config.business.timezone)
        now = datetime.now(tz)
        day_name = now.strftime("%A").lower()
        day_hours = getattr(self.config.hours, day_name)

        if day_hours is None:
            return f"The business is closed today ({now.strftime('%A')}). {self.config.after_hours_message}"

        current_time = now.strftime("%H:%M")
        if day_hours.open <= current_time <= day_hours.close:
            return f"The business is currently open. Today's hours are {day_hours.open} to {day_hours.close}."
        return f"The business is currently closed. Today's hours are {day_hours.open} to {day_hours.close}. {self.config.after_hours_message}"

    @function_tool()
    async def check_availability(
        self,
        ctx: RunContext,
        preferred_date: str,
        preferred_time: str,
    ) -> str:
        """Check the calendar for available appointment slots near a caller-requested time.

        Args:
            preferred_date: a natural-language date like "Tuesday", "April 28",
                "tomorrow", "next Monday", etc.
            preferred_time: a natural-language time like "2pm", "14:00", "afternoon".
        """
        from datetime import timedelta
        from dateutil import parser as dateparser

        from receptionist.booking.availability import find_slots
        from receptionist.booking.auth import CalendarAuthError

        if self.config.calendar is None or not self.config.calendar.enabled:
            return (
                "I'm sorry, we don't have online booking set up. I can take a "
                "message about your preferred time and have someone call you back."
            )

        tz = ZoneInfo(self.config.business.timezone)
        now = datetime.now(tz)

        # Parse caller's natural-language date + time into a tz-aware datetime
        try:
            combined = f"{preferred_date} {preferred_time}"
            parsed = dateparser.parse(combined, default=now.replace(
                second=0, microsecond=0,
            ))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
        except (ValueError, TypeError) as e:
            logger.info("check_availability: could not parse %r %r: %s", preferred_date, preferred_time, e)
            return (
                "I had trouble understanding that date and time. Could you say it "
                "differently — for example, 'Tuesday April 28 at 2 PM'?"
            )

        earliest = now + timedelta(hours=self.config.calendar.earliest_booking_hours_ahead)
        latest = now + timedelta(days=self.config.calendar.booking_window_days)

        # Hard constraint checks (before hitting Google)
        if parsed < earliest:
            return (
                f"I can only book appointments at least "
                f"{self.config.calendar.earliest_booking_hours_ahead} hours from now. "
                f"The earliest I can offer is {_format_friendly_date(earliest)}."
            )
        if parsed > latest:
            return (
                f"I can only book up to {self.config.calendar.booking_window_days} "
                f"days out. Would you like a time sooner than "
                f"{latest.strftime('%A, %B %d')}?"
            )

        try:
            client = self._get_calendar_client()
            busy = await client.free_busy(earliest, latest)
        except CalendarAuthError:
            logger.exception("check_availability: auth error")
            return (
                "I'm having trouble accessing our calendar right now. Can I take "
                "a message about your preferred time and have someone call you back?"
            )
        except Exception:
            logger.exception("check_availability: client error")
            return (
                "I can't check availability at the moment. Can I take a message "
                "about the time you wanted?"
            )

        slots = find_slots(
            business_hours=self.config.hours,
            business_timezone=self.config.business.timezone,
            calendar_config=self.config.calendar,
            preferred_dt=parsed,
            existing_busy=busy,
            earliest=earliest,
            latest=latest,
            now=now,
        )

        if not slots:
            return (
                f"I don't see any openings near {_format_friendly_date(parsed)}. "
                f"Would you like me to take a message so someone can offer alternatives?"
            )

        # Cache the ISO strings so book_appointment can validate them
        for slot in slots:
            self._offered_slots.add(slot.start_iso)

        # Format a caller-friendly response. The LLM takes this and speaks it.
        formatted = []
        for i, slot in enumerate(slots, start=1):
            dt = datetime.fromisoformat(slot.start_iso)
            human = _format_friendly_date(dt)
            # Also include the ISO string so the LLM can pass it back to book_appointment
            formatted.append(f"{i}. {human}  [iso={slot.start_iso}]")

        return (
            f"I found these available times near your preferred slot. "
            f"Confirm the one the caller chose, then call book_appointment with "
            f"the exact iso= string shown.\n" + "\n".join(formatted)
        )

    @function_tool()
    async def book_appointment(
        self,
        ctx: RunContext,
        caller_name: str,
        callback_number: str,
        proposed_start_iso: str,
        notes: str | None = None,
    ) -> str:
        """Book an appointment at a previously-offered time.

        Args:
            caller_name: the caller's full name
            callback_number: the caller's phone number
            proposed_start_iso: the exact ISO 8601 start datetime offered by
                a prior check_availability call. Copy from that response.
            notes: optional free-form note to include in the event description.
        """
        from datetime import timedelta

        from receptionist.booking.booking import (
            SlotNoLongerAvailableError, book_appointment as _book,
        )
        from receptionist.booking.models import SlotProposal
        from receptionist.booking.availability import find_slots

        if self.config.calendar is None or not self.config.calendar.enabled:
            return "Calendar booking is not enabled for this business."

        # Enforce "must check before book" — slot must have been offered
        if proposed_start_iso not in self._offered_slots:
            return (
                "I need to verify that time is still available. Let me check "
                "first — please call check_availability before booking."
            )

        # Reconstruct the matching SlotProposal. We trust start_iso and compute
        # the end from appointment_duration_minutes (slots have uniform duration).
        start = datetime.fromisoformat(proposed_start_iso)
        duration = timedelta(minutes=self.config.calendar.appointment_duration_minutes)
        slot = SlotProposal(
            start_iso=proposed_start_iso,
            end_iso=(start + duration).isoformat(),
        )

        try:
            client = self._get_calendar_client()
            result = await _book(
                slot=slot,
                caller_name=caller_name,
                callback_number=callback_number,
                call_id=self.lifecycle.metadata.call_id,
                time_zone=self.config.business.timezone,
                client=client,
                notes=notes,
            )
        except SlotNoLongerAvailableError:
            # Slot just got taken. Find fresh alternatives.
            tz = ZoneInfo(self.config.business.timezone)
            now = datetime.now(tz)
            earliest = now + timedelta(hours=self.config.calendar.earliest_booking_hours_ahead)
            latest = now + timedelta(days=self.config.calendar.booking_window_days)
            try:
                busy = await client.free_busy(earliest, latest)
                alternates = find_slots(
                    business_hours=self.config.hours,
                    business_timezone=self.config.business.timezone,
                    calendar_config=self.config.calendar,
                    preferred_dt=start,
                    existing_busy=busy,
                    earliest=earliest,
                    latest=latest,
                    now=now,
                )
            except Exception:
                logger.exception("book_appointment: failed to find alternates after race")
                alternates = []

            # Reset cache to the new set
            self._offered_slots = {s.start_iso for s in alternates}
            if alternates:
                formatted = "\n".join(
                    f"- {_format_friendly_date(datetime.fromisoformat(s.start_iso))}  [iso={s.start_iso}]"
                    for s in alternates
                )
                return (
                    f"Unfortunately that slot just got taken. Here are the "
                    f"nearest alternatives:\n{formatted}"
                )
            return (
                "Unfortunately that slot just got taken, and I can't find "
                "nearby alternatives right now. Would you like me to take a "
                "message so someone can call you back with options?"
            )
        except Exception:
            logger.exception("book_appointment: unexpected error")
            return (
                "I had trouble booking that time. Can I take a message with "
                "the time you wanted, and someone will confirm with you?"
            )

        # Success — record on lifecycle, return confirmation
        self.lifecycle.record_appointment_booked({
            "event_id": result.event_id,
            "start_iso": result.start_iso,
            "end_iso": result.end_iso,
            "html_link": result.html_link,
        })

        confirmed = datetime.fromisoformat(result.start_iso)
        return (
            f"You're all set for {_format_friendly_date(confirmed)}. "
            f"Someone will contact you at {callback_number} if we need to confirm."
        )


server = AgentServer()


@server.rtc_session()
async def handle_call(ctx: agents.JobContext):
    config = load_business_config(ctx)

    lifecycle = CallLifecycle(
        config=config,
        call_id=ctx.room.name,
        caller_phone=_get_caller_phone(ctx),
    )

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            model=config.voice.model,
            voice=config.voice.voice_id,
        ),
    )

    # Wire transcript capture BEFORE session starts so no events are missed.
    lifecycle.attach_transcript_capture(session)

    # Register the close handler. `close` fires when the session ends for any
    # reason. livekit's EventEmitter rejects coroutine handlers (it requires
    # plain callables), so we schedule the async work via `create_task`.
    #
    # Note on lifetime: `AgentSession.start()` below returns shortly after
    # the session is initialized, NOT after the call ends. The `@rtc_session`
    # framework keeps the job — and therefore the event loop — alive until
    # the underlying room actually closes, which is what gives the scheduled
    # task time to run. Validated manually 2026-04-24: transcript + email
    # artifacts land after disconnect even though handle_call returned
    # minutes earlier.
    def _handle_close(_event) -> None:
        async def _run() -> None:
            try:
                await lifecycle.on_call_ended()
            except Exception:
                logger.exception("lifecycle.on_call_ended raised")

        asyncio.create_task(_run())

    session.on("close", _handle_close)

    # Start recording before greeting. The consent preamble (Phase 8) fires
    # before the greeting; the recording is already live by that point, so
    # the preamble is captured — which is the correct proof-of-disclosure.
    await lifecycle.start_recording_if_enabled(ctx.room.name)

    await session.start(
        room=ctx.room,
        agent=Receptionist(config, lifecycle),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
