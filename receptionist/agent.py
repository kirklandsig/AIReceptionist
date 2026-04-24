# receptionist/agent.py
from __future__ import annotations

import asyncio
import json
import logging
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

    async def on_enter(self) -> None:
        # Consent preamble (when enabled) is added in Phase 8. For now, just
        # speak the greeting.
        await self.session.generate_reply(
            instructions=f"Greet the caller with: '{self.config.greeting}'"
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
    # plain callables), so we schedule the async work via create_task — but
    # we must AWAIT that task before handle_call returns, otherwise the
    # worker may tear down the event loop while transcript writes and
    # call-end emails are still in flight. The `close_work_done` future is
    # resolved once the async work completes (success or failure), and we
    # await it at the end of handle_call.
    close_work_done: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    def _handle_close(_event) -> None:
        async def _run() -> None:
            try:
                await lifecycle.on_call_ended()
            except Exception:
                logger.exception("lifecycle.on_call_ended raised")
            finally:
                if not close_work_done.done():
                    close_work_done.set_result(None)
        asyncio.create_task(_run())

    session.on("close", _handle_close)

    # Start recording before greeting. Phase 8 moves the consent preamble
    # to fire before the greeting; the recording is already live so the
    # preamble is on the record, which is correct.
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

    # session.start returns when the session ends. Wait for the close
    # handler's async work to complete before letting handle_call return.
    # Cap the wait at 30s so a hung disconnect doesn't stall the worker.
    try:
        await asyncio.wait_for(close_work_done, timeout=30.0)
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out waiting for on_call_ended to complete (30s) — "
            "artifacts may not have been written",
            extra={"call_id": ctx.room.name, "component": "agent.handle_call"},
        )


if __name__ == "__main__":
    agents.cli.run_app(server)
