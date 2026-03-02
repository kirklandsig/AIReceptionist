from __future__ import annotations

import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from livekit import agents, api, rtc
from livekit.agents import AgentServer, AgentSession, Agent, RunContext, function_tool, room_io, get_job_context
from livekit.plugins import openai, noise_cancellation

from receptionist.config import BusinessConfig, load_config
from receptionist.messages import Message, save_message
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
        config_path = DEFAULT_CONFIG_DIR / f"{config_name}.yaml"
    else:
        # Fall back to first YAML file in config directory
        yaml_files = sorted(DEFAULT_CONFIG_DIR.glob("*.yaml"))
        if not yaml_files:
            raise FileNotFoundError(f"No config files found in {DEFAULT_CONFIG_DIR}")
        config_path = yaml_files[0]
        logger.info(f"No config specified, using: {config_path.name}")

    return load_config(config_path)


class Receptionist(Agent):
    def __init__(self, config: BusinessConfig) -> None:
        super().__init__(instructions=build_system_prompt(config))
        self.config = config

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions=f"Greet the caller with: '{self.config.greeting}'"
        )

    @function_tool()
    async def lookup_faq(self, ctx: RunContext, question: str) -> str:
        """Look up the answer to a frequently asked question about the business."""
        for faq in self.config.faqs:
            if question.lower() in faq.question.lower() or faq.question.lower() in question.lower():
                return faq.answer
        return "I don't have a specific answer for that question. I can take a message or transfer you to someone who can help."

    @function_tool()
    async def transfer_call(self, ctx: RunContext, department: str) -> str:
        """Transfer the caller to a specific department or person. Use the department name from the routing list."""
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
            return f"Call transferred to {target.name}"
        except Exception as e:
            logger.error(f"Failed to transfer call: {e}")
            return f"Sorry, I wasn't able to transfer the call. Error: {e}"

    @function_tool()
    async def take_message(self, ctx: RunContext, caller_name: str, message: str, callback_number: str) -> str:
        """Take a message from the caller. Collect their name, message, and callback number."""
        msg = Message(
            caller_name=caller_name,
            callback_number=callback_number,
            message=message,
            business_name=self.config.business.name,
        )
        save_message(
            msg,
            delivery=self.config.messages.delivery.value,
            file_path=self.config.messages.file_path,
            webhook_url=self.config.messages.webhook_url,
        )
        return f"Message saved from {caller_name}. Let them know their message has been recorded and someone will get back to them."

    @function_tool()
    async def get_business_hours(self, ctx: RunContext) -> str:
        """Check the current business hours and whether the business is open right now."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(self.config.business.timezone)
        now = datetime.now(tz)
        day_name = now.strftime("%A").lower()
        day_hours = getattr(self.config.hours, day_name)

        if day_hours is None:
            return f"The business is closed today ({now.strftime('%A')}). {self.config.after_hours_message}"

        current_time = now.strftime("%H:%M")
        if day_hours.open <= current_time <= day_hours.close:
            return f"The business is currently open. Today's hours are {day_hours.open} to {day_hours.close}."
        else:
            return f"The business is currently closed. Today's hours are {day_hours.open} to {day_hours.close}. {self.config.after_hours_message}"


def _get_caller_identity(ctx: agents.JobContext) -> str:
    """Get the SIP caller's participant identity from the room."""
    for participant in ctx.room.remote_participants.values():
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            return participant.identity
    return ""


server = AgentServer()


@server.rtc_session(agent_name="receptionist")
async def handle_call(ctx: agents.JobContext):
    config = load_business_config(ctx)

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(voice=config.voice.voice_id),
    )

    await session.start(
        room=ctx.room,
        agent=Receptionist(config),
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
