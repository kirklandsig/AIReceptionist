# receptionist/agent.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from dotenv import load_dotenv

from livekit import agents, api, rtc
from livekit.agents import (
    AgentServer, AgentSession, Agent, RunContext,
    function_tool, room_io, get_job_context,
)
from livekit.plugins import openai, noise_cancellation

from receptionist.booking.availability import find_slots
from receptionist.booking.models import SlotProposal
from receptionist.config import BusinessConfig, load_config
from receptionist.lifecycle import CallLifecycle
from receptionist.messaging.dispatcher import Dispatcher
from receptionist.messaging.models import DispatchContext, Message
from receptionist.prompts import build_system_prompt
from receptionist.voice_auth import resolve_voice_bearer_async

load_dotenv(".env.local")
load_dotenv(".env")

logger = logging.getLogger("receptionist")

DEFAULT_CONFIG_DIR = Path("config/businesses")


def _format_friendly_date(dt: datetime) -> str:
    """Cross-platform 'Monday, April 28 at 2:00 PM'.

    Callers must pass a tz-aware datetime — the rendered time has no
    timezone marker, so a naive datetime would silently lose offset info.
    `find_slots` produces tz-aware iso strings, so `datetime.fromisoformat`
    of those is safe.
    """
    if platform.system() == "Windows":
        return dt.strftime("%A, %B %#d at %#I:%M %p")
    return dt.strftime("%A, %B %-d at %-I:%M %p")


# Light email-shape regex — exists to catch obvious caller mishearings ("dot calm",
# missing @, missing TLD). Google rejects malformed emails server-side too, this
# is just for a friendlier in-call error message.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SIP_PHONE_RE = re.compile(r"^\+?\d{7,15}$")
_SIP_URI_PHONE_RE = re.compile(
    r"(?:^|[<\s])sip:(\+?\d{7,15})(?:@|[>;\s]|$)", re.IGNORECASE,
)
_SIP_IDENTITY_PHONE_RE = re.compile(r"^sip_(\+?\d{7,15})$", re.IGNORECASE)


# Caps on caller-supplied free-text fields. The LLM faithfully passes through
# whatever the caller said, so without these caps a 30-minute rant becomes a
# 30,000-character "message" — which bloats storage, slows email rendering,
# and (for calendar event descriptions) hits Google's 8KB limit. Truncate +
# log rather than reject: the call should keep flowing; staff can read the
# log if they need the full version.
# RFC 5321 caps email addresses at 254 chars. The other limits are operator-
# friendly: room for a long name or a verbose voicemail without being a vector.
_TRUNCATE_LIMITS = {
    "caller_name": 200,
    "callback_number": 50,
    "message": 4000,
    "notes": 1000,
    "caller_email": 254,
}


def _cap(field: str, value: str | None, *, call_id: str | None = None) -> str | None:
    """Truncate `value` to _TRUNCATE_LIMITS[field] chars, logging when it does.

    Returns None unchanged. Treats whitespace as content (the caller said it).
    """
    if value is None:
        return None
    limit = _TRUNCATE_LIMITS[field]
    if len(value) <= limit:
        return value
    extra = {"call_id": call_id, "component": "agent.input_caps"} if call_id else {}
    logger.info(
        "Truncated overlong %s: %d chars -> %d", field, len(value), limit,
        extra=extra,
    )
    return value[:limit]


_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _resolve_relative_date(preferred_date: str, now: datetime) -> str:
    """Convert relative-date phrases into absolute dates dateutil can parse.

    Handles: "today" / "tonight", "tomorrow", "next <weekday>", "this <weekday>".
    Falls through unchanged for absolute dates ("April 28") and bare weekday
    names ("Monday") — dateutil handles those.
    """
    s = preferred_date.strip().lower()
    if s in {"today", "tonight"}:
        return now.strftime("%B %d %Y")
    if s == "tomorrow":
        return (now + timedelta(days=1)).strftime("%B %d %Y")

    # "next Monday" → 7+ days out; "this Monday" → soonest occurrence (today counts)
    for prefix in ("next ", "this "):
        if s.startswith(prefix):
            wd = s[len(prefix):]
            if wd in _WEEKDAYS:
                target = _WEEKDAYS[wd]
                days_ahead = (target - now.weekday()) % 7
                if prefix == "next " and days_ahead < 7:
                    days_ahead += 7
                target_dt = now + timedelta(days=days_ahead)
                return target_dt.strftime("%B %d %Y")

    return preferred_date


def load_business_config(ctx: agents.JobContext) -> BusinessConfig:
    """Load business config based on job metadata or default to first config found."""
    metadata = {}
    if ctx.job.metadata:
        try:
            metadata = json.loads(ctx.job.metadata)
        except json.JSONDecodeError:
            logger.warning("Failed to parse job metadata as JSON")

    config_name = metadata.get("config", None) or os.environ.get("RECEPTIONIST_CONFIG")

    if config_name:
        if not re.match(r"^[a-zA-Z0-9_-]+$", config_name):
            raise ValueError(f"Invalid config name: {config_name!r}")
        config_path = DEFAULT_CONFIG_DIR / f"{config_name}.yaml"
    else:
        yaml_files = sorted(DEFAULT_CONFIG_DIR.glob("*.yaml"))
        if not yaml_files:
            raise FileNotFoundError(f"No config files found in {DEFAULT_CONFIG_DIR}")
        config_path = yaml_files[0]
        logger.info(f"No config specified, using: {config_path.name}")

    return load_config(config_path)


def _get_caller_identity(ctx: agents.JobContext) -> str:
    """Get the SIP caller's participant identity from the room.

    Prefers participants whose kind is `PARTICIPANT_KIND_SIP`, but falls back
    to any participant whose identity matches `sip_<digits>` so BYOC/Asterisk
    trunks that publish a different kind value still work.
    """
    fallback = ""
    for participant in ctx.room.remote_participants.values():
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            return participant.identity
        identity = getattr(participant, "identity", "")
        if identity and _SIP_IDENTITY_PHONE_RE.fullmatch(identity.strip()):
            fallback = fallback or identity
    if fallback:
        return fallback
    logger.warning("No SIP participant found in room %s", ctx.room.name)
    return ""


def _get_caller_phone(ctx: agents.JobContext) -> str | None:
    """Best-effort extract caller phone number from any room participant."""
    for participant in ctx.room.remote_participants.values():
        phone = _get_sip_participant_phone(participant)
        if phone:
            return phone
    return None


def _get_sip_participant_phone(participant: rtc.RemoteParticipant) -> str | None:
    """Resolve a phone number for `participant`, kind-agnostic.

    Order of attempts:
      1. SIP attribute `sip.phoneNumber` (LiveKit Cloud + most BYOC trunks)
      2. SIP attribute `sip.fromUser` (some Telnyx setups)
      3. SIP attribute `sip.from` URI / FROM-header value
      4. Participant identity matching `sip_<digits>` (Asterisk BYOC pattern)

    The kind gate was removed in 2026-05 because some BYOC/Asterisk trunks
    emit the SIP participant with a non-SIP kind value, but its identity
    still matches `sip_<digits>`. The identity regex is specific enough
    that false positives from non-SIP participants are not a real risk.
    """
    attrs = getattr(participant, "attributes", {}) or {}
    phone = attrs.get("sip.phoneNumber")
    if phone:
        return phone
    for attr_name in ("sip.fromUser", "sip.from"):
        phone = _normalize_sip_phone(attrs.get(attr_name))
        if phone:
            return phone
    return _get_sip_phone_from_identity(getattr(participant, "identity", ""))


def _normalize_sip_phone(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if _SIP_PHONE_RE.fullmatch(value):
        return value if value.startswith("+") else f"+{value}"
    match = _SIP_URI_PHONE_RE.search(value)
    if match:
        phone = match.group(1)
        return phone if phone.startswith("+") else f"+{phone}"
    return None


def _get_sip_phone_from_identity(identity: str) -> str | None:
    match = _SIP_IDENTITY_PHONE_RE.fullmatch(identity.strip())
    if not match:
        return None
    phone = match.group(1)
    return phone if phone.startswith("+") else f"+{phone}"


# Whitelist of reasons accepted by `end_call`. Keeps the agent-end reason
# field (CallMetadata.agent_end_reason) bounded to known causes so dashboards
# and call-summary email subjects stay consistent. New causes added here must
# also be reflected in documentation/function-tools-reference.md.
_AGENT_END_REASONS = frozenset(
    {
        "caller_goodbye",
        "silence_timeout",
        "unproductive_turns_exhausted",
        "max_duration_reached",
    }
)


# Default goodbye instructions per agent-end reason. The end_call tool can
# override these, but the silence/duration/unproductive paths use these so
# the caller hears something appropriate rather than a generic "bye".
_AGENT_END_INSTRUCTIONS = {
    "caller_goodbye": (
        "Say a very brief, friendly goodbye to the caller in one short "
        "sentence (e.g. \"Thanks for calling, have a great day!\"). Do not "
        "add follow-up questions; the call ends right after."
    ),
    "silence_timeout": (
        "The caller has gone quiet. Say a brief, friendly note that you "
        "are wrapping up because you haven't heard from them, and invite "
        "them to call back any time. One or two short sentences only."
    ),
    "unproductive_turns_exhausted": (
        "Politely close the call: acknowledge that you have not been able "
        "to help with this request, suggest the caller contact the office "
        "directly during business hours, and say goodbye. One or two short "
        "sentences only."
    ),
    "max_duration_reached": (
        "Politely note that the call has run long and you need to wrap up, "
        "invite the caller to call back any time, and say goodbye. One or "
        "two short sentences only."
    ),
}


def _extract_message_text(item) -> str:
    """Best-effort flatten an `llm.ChatMessage`-shaped item into a plain string.

    The realtime SDK exposes `item.content` as either a string or a list of
    content parts (each part has `.text` for text parts, `.transcript` for
    audio transcripts). We concatenate everything string-like and ignore the
    rest.
    """
    content = getattr(item, "content", None)
    if isinstance(content, str):
        return content
    if not content:
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
            continue
        text = getattr(part, "text", None)
        if isinstance(text, str):
            parts.append(text)
            continue
        transcript = getattr(part, "transcript", None)
        if isinstance(transcript, str):
            parts.append(transcript)
    return " ".join(parts).strip()


async def _speak_goodbye_and_terminate(
    session: AgentSession,
    lifecycle: CallLifecycle,
    job_ctx: agents.JobContext,
    *,
    reason: str,
) -> None:
    """Speak a brief goodbye then disconnect the SIP caller.

    Used by `Receptionist.end_call` (caller said goodbye) and the
    silence/duration/unproductive watchers in `handle_call`. Each call site
    is expected to have already called `lifecycle.record_agent_ended(reason)`
    synchronously, so the call summary reflects the agent end even if the
    natural-disconnect close event races this background task.

    The goodbye playout uses a hard 10s timeout so a stuck TTS never wedges
    the call open. Terminate then prefers SIP BYE via `remove_participant`
    and falls back to `delete_room` (see `_terminate_room`).
    """
    call_id = lifecycle.metadata.call_id
    log_extra = {"call_id": call_id, "component": "agent.end"}
    instructions = _AGENT_END_INSTRUCTIONS.get(
        reason, _AGENT_END_INSTRUCTIONS["caller_goodbye"],
    )

    if session is not None:
        try:
            handle = session.generate_reply(instructions=instructions)
            try:
                await asyncio.wait_for(handle.wait_for_playout(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "agent_end: goodbye playout timed out (reason=%s)",
                    reason, extra=log_extra,
                )
            except Exception:
                logger.exception(
                    "agent_end: error waiting for goodbye playout (reason=%s)",
                    reason, extra=log_extra,
                )
        except Exception:
            logger.exception(
                "agent_end: failed to speak goodbye (reason=%s); proceeding "
                "to terminate", reason, extra=log_extra,
            )

    caller_identity = _get_caller_identity(job_ctx)
    await _terminate_room(
        job_ctx, caller_identity, job_ctx.room.name, call_id=call_id,
    )


async def _terminate_room(
    job_ctx: agents.JobContext,
    caller_identity: str,
    room_name: str,
    *,
    call_id: str,
) -> None:
    """Disconnect the caller; prefer SIP BYE, fall back to full room delete.

    `remove_participant` is the right tool for SIP BYE: it asks LiveKit to
    drop the caller specifically (the agent stays in the room until the
    session close handler fires). If that call fails — typically because
    the agent token lacks `room_admin` for this room, or the participant
    has already disconnected — we fall back to `delete_room`, which closes
    the room for everyone and triggers the participant-disconnect close
    path. Either way, the close handler runs `lifecycle.on_call_ended`.
    """
    log_extra = {"call_id": call_id, "component": "agent.terminate"}
    if caller_identity:
        try:
            await job_ctx.api.room.remove_participant(
                api.RoomParticipantIdentity(
                    room=room_name, identity=caller_identity,
                )
            )
            logger.info(
                "end_call: removed participant %s from %s",
                caller_identity, room_name, extra=log_extra,
            )
            return
        except Exception:
            logger.warning(
                "end_call: remove_participant failed for %s in %s; "
                "falling back to delete_room",
                caller_identity, room_name, exc_info=True, extra=log_extra,
            )
    try:
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(room=room_name)
        )
        logger.info("end_call: deleted room %s", room_name, extra=log_extra)
    except Exception:
        logger.exception(
            "end_call: delete_room failed for %s; close event will fire on "
            "natural disconnect",
            room_name, extra=log_extra,
        )


def _capture_caller_phone_from_participant(
    lifecycle: CallLifecycle, participant: rtc.RemoteParticipant,
    *, source: str = "snapshot",
) -> None:
    """Set caller_phone from a participant if not yet known.

    Always-on INFO logs (component=`agent.callerid`) record both the
    successful capture path and the negative result so on-call operators
    can diagnose CallerID issues without flipping debug flags. The
    participant identity is logged so BYOC/Asterisk trunks emitting
    `sip_<digits>` are visible in production logs.
    """
    phone = _get_sip_participant_phone(participant)
    identity = getattr(participant, "identity", "") or ""
    kind = getattr(participant, "kind", None)
    extra = {
        "call_id": lifecycle.metadata.call_id,
        "component": "agent.callerid",
        "source": source,
        "participant_identity": identity,
        "participant_kind": int(kind) if kind is not None else None,
    }
    if phone:
        already_set = lifecycle.metadata.caller_phone is not None
        lifecycle.set_caller_phone(phone)
        if already_set:
            logger.info(
                "callerid: phone %s already captured; new candidate %s ignored",
                lifecycle.metadata.caller_phone, phone, extra=extra,
            )
        else:
            logger.info("callerid: captured caller phone %s", phone, extra=extra)
        return
    logger.info(
        "callerid: no phone resolvable from participant identity=%r attrs_keys=%s",
        identity,
        sorted((getattr(participant, "attributes", {}) or {}).keys()),
        extra=extra,
    )


class Receptionist(Agent):
    def __init__(self, config: BusinessConfig, lifecycle: CallLifecycle) -> None:
        super().__init__(instructions=build_system_prompt(config))
        self.config = config
        self.lifecycle = lifecycle
        # Session-scoped cache of slot ISO strings offered to the caller via
        # check_availability. book_appointment rejects any proposed_start_iso
        # that isn't in this set — prevents the LLM from hallucinating times.
        # Capped to the last N=3 check_availability calls so a long, chatty
        # call can't grow the set unbounded. 3 batches × ~3 slots = ~9 ISO
        # strings; the LLM only ever needs the most recent batch anyway.
        self._offered_slot_batches: deque[frozenset[str]] = deque(maxlen=3)
        # Lazily-constructed on first calendar tool call; reused for the rest
        # of the call so we don't pay Google's auth cost per tool invocation.
        self._calendar_client = None
        # Pre-build a single Dispatcher for the call. The constructor runs a
        # filesystem-walk in resolve_failures_dir(), so reusing it across
        # take_message invocations matters when callers leave several messages.
        self._dispatcher = Dispatcher(
            channels=self.config.messages.channels,
            business_name=self.config.business.name,
            email_config=self.config.email,
        )
        # Dict-backed routing lookup. transfer_call uses case-insensitive
        # exact match on the department name, so a dict is a clean fit.
        # NOTE: FAQ matching is bidirectional substring (caller "hours" can
        # match FAQ "What are your hours?" AND vice versa), which a single
        # dict can't represent — leave that as a linear scan.
        self._routing_by_name = {r.name.lower(): r for r in self.config.routing}
        # Issue #11 unproductive-turn counter state. See
        # _on_user_input_transcribed / _on_function_tools_executed /
        # _on_conversation_item_added for the full state machine.
        self._consecutive_unproductive_turns: int = 0
        self._current_turn_used_tool: bool = False
        self._current_turn_assistant_replied: bool = False
        self._unproductive_end_scheduled: bool = False

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

    def _record_offered_slots(self, iso_strings) -> None:
        """Add a batch of slot ISO strings to the bounded offer cache.

        Older batches age out automatically (deque maxlen=3).
        """
        self._offered_slot_batches.append(frozenset(iso_strings))

    def _slot_was_offered(self, iso: str) -> bool:
        """True if `iso` was offered in any of the last N batches."""
        return any(iso in batch for batch in self._offered_slot_batches)

    def _reset_offered_slots(self, iso_strings) -> None:
        """Clear the offer cache and seed it with this batch (used after race recovery)."""
        self._offered_slot_batches.clear()
        self._record_offered_slots(iso_strings)

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
        target = self._routing_by_name.get(department.lower())
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
                    transfer_to=self.config.sip.transfer_uri_template.format(number=target.number),
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
        call_id = self.lifecycle.metadata.call_id
        caller_name = _cap("caller_name", caller_name, call_id=call_id) or ""
        message = _cap("message", message, call_id=call_id) or ""
        callback_number = _cap("callback_number", callback_number, call_id=call_id) or ""
        msg = Message(
            caller_name=caller_name,
            callback_number=callback_number,
            message=message,
            business_name=self.config.business.name,
        )
        try:
            await self._dispatcher.dispatch_message(
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
    async def end_call(
        self, ctx: RunContext, reason: str = "caller_goodbye",
    ) -> str:
        """End the call after a brief goodbye.

        Use this when the caller has clearly finished the conversation —
        for example "goodbye", "thanks, bye", "that's all I needed", or when
        you've told the caller you have no further help to offer and they
        have nothing else to ask. Do NOT use this just because the caller
        is quiet for a moment, mid-question, or asking for something you
        haven't tried yet.

        Args:
            reason: short label for *why* the agent ended the call. Stored
                on the call summary so staff can audit agent-initiated
                hangups. Allowed values: `caller_goodbye` (default),
                `silence_timeout`, `unproductive_turns_exhausted`,
                `max_duration_reached`. Any other value is replaced with
                `caller_goodbye`.
        """
        safe_reason = reason if reason in _AGENT_END_REASONS else "caller_goodbye"
        # Record the outcome synchronously so even if the background hangup
        # task races a caller-initiated close, the call summary already
        # shows agent-ended with this reason.
        self.lifecycle.record_agent_ended(safe_reason)

        # Schedule the actual hangup in the background so the tool can return
        # immediately (the LLM gets the tool response right away; the caller
        # hears the goodbye and disconnects via the background task).
        job_ctx = get_job_context()
        session = ctx.session
        lifecycle = self.lifecycle

        async def _run_end() -> None:
            await _speak_goodbye_and_terminate(
                session, lifecycle, job_ctx, reason=safe_reason,
            )

        asyncio.create_task(_run_end())
        return f"Agent ending the call (reason={safe_reason})."

    # ------------------------------------------------------------------
    # Issue #11 unproductive-turn counter
    # ------------------------------------------------------------------

    def _on_user_input_transcribed(self, ev) -> None:
        """Reset per-turn flags whenever a final user transcript arrives.

        Listener is attached in `handle_call` after the session is built.
        The agent's `conversation_item_added` event for the matching
        assistant reply later in the same turn checks this flag.
        """
        if not getattr(ev, "is_final", False):
            return
        self._current_turn_used_tool = False
        self._current_turn_assistant_replied = False

    def _on_function_tools_executed(self, _ev) -> None:
        """A function tool ran => this turn is productive => reset counter."""
        self._current_turn_used_tool = True
        if self._consecutive_unproductive_turns:
            logger.debug(
                "unproductive_turns: tool fired, resetting counter from %d to 0",
                self._consecutive_unproductive_turns,
                extra={"call_id": self.lifecycle.metadata.call_id, "component": "agent.unproductive"},
            )
        self._consecutive_unproductive_turns = 0

    def _on_conversation_item_added(self, ev) -> None:
        """Score the agent's reply for unproductiveness and trigger end_call
        when the threshold is reached.
        """
        if self._current_turn_assistant_replied:
            # The assistant added a follow-up message in the same turn (rare).
            # Only score the first reply per user turn to avoid double-counting.
            return
        item = getattr(ev, "item", None)
        if item is None or getattr(item, "role", None) != "assistant":
            return
        self._current_turn_assistant_replied = True

        idle_cfg = self.config.voice.idle
        if not idle_cfg.unproductive_hangup_enabled:
            return
        if self._current_turn_used_tool:
            self._consecutive_unproductive_turns = 0
            return

        text = _extract_message_text(item)
        if not text:
            return

        text_lower = text.lower()
        is_unproductive = any(
            phrase in text_lower for phrase in idle_cfg.unproductive_phrases
        )
        if not is_unproductive:
            self._consecutive_unproductive_turns = 0
            return

        self._consecutive_unproductive_turns += 1
        log_extra = {
            "call_id": self.lifecycle.metadata.call_id,
            "component": "agent.unproductive",
            "count": self._consecutive_unproductive_turns,
            "threshold": idle_cfg.unproductive_turn_threshold,
        }
        logger.info(
            "unproductive_turns: count=%d threshold=%d",
            self._consecutive_unproductive_turns,
            idle_cfg.unproductive_turn_threshold,
            extra=log_extra,
        )
        if self._consecutive_unproductive_turns < idle_cfg.unproductive_turn_threshold:
            return

        # Threshold reached — schedule the agent-initiated end. Guard with a
        # one-shot flag so we don't double-fire if more replies come in
        # between scheduling and termination.
        if self._unproductive_end_scheduled:
            return
        self._unproductive_end_scheduled = True
        logger.warning(
            "unproductive_turns: threshold reached, ending call",
            extra=log_extra,
        )

        try:
            job_ctx = get_job_context()
        except RuntimeError:
            logger.exception(
                "unproductive_turns: no job context; cannot end call",
                extra=log_extra,
            )
            return
        session = self.session
        lifecycle = self.lifecycle
        lifecycle.record_agent_ended("unproductive_turns_exhausted")

        async def _run() -> None:
            await _speak_goodbye_and_terminate(
                session, lifecycle, job_ctx,
                reason="unproductive_turns_exhausted",
            )

        asyncio.create_task(_run())

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
        # CalendarAuthError lives in booking/auth.py which transitively imports
        # google-auth — keep it lazy so calendar-disabled businesses don't pay
        # the import cost.
        from receptionist.booking.auth import CalendarAuthError

        if self.config.calendar is None or not self.config.calendar.enabled:
            return (
                "I'm sorry, we don't have online booking set up. I can take a "
                "message about your preferred time and have someone call you back."
            )

        tz = ZoneInfo(self.config.business.timezone)
        now = datetime.now(tz)

        # Resolve relative-date words ("today", "tomorrow", "next Monday") that
        # dateutil.parser doesn't understand on its own. Bare weekday names ("Monday")
        # and absolute dates ("April 28") fall through to the parser unchanged.
        preferred_date = _resolve_relative_date(preferred_date, now)

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

        # Cache the ISO strings so book_appointment can validate them.
        # Bounded to last 3 batches (deque maxlen=3) — older batches age out.
        self._record_offered_slots(s.start_iso for s in slots)

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
        caller_email: str | None = None,
    ) -> str:
        """Book an appointment at a previously-offered time.

        Args:
            caller_name: the caller's full name
            callback_number: the caller's phone number
            proposed_start_iso: the exact ISO 8601 start datetime offered by
                a prior check_availability call. Copy from that response.
            notes: optional free-form note to include in the event description.
            caller_email: optional email address to send a calendar invite to.
                When provided, the caller is added as an OPTIONAL attendee and
                Google sends them the standard invite email with .ics file and
                accept/decline. Leave None if the caller didn't volunteer an
                email — never make one up.
        """
        # booking.booking imports booking.client which pulls google-api-
        # python-client at module load (~50MB). Keep it lazy so businesses
        # with calendar disabled don't pay that import cost. Aliased to
        # _book to avoid shadowing this method's own name.
        from receptionist.booking.booking import (
            SlotNoLongerAvailableError, book_appointment as _book,
        )

        if self.config.calendar is None or not self.config.calendar.enabled:
            return "Calendar booking is not enabled for this business."

        # Enforce "must check before book" — slot must have been offered
        if not self._slot_was_offered(proposed_start_iso):
            return (
                "I need to verify that time is still available. Let me check "
                "first — please call check_availability before booking."
            )

        # Cap caller free-text fields to avoid bloating the calendar event
        # description and email body. Long input is truncated, not rejected,
        # so the booking still flows; the truncation is logged.
        call_id = self.lifecycle.metadata.call_id
        caller_name = _cap("caller_name", caller_name, call_id=call_id) or ""
        callback_number = _cap("callback_number", callback_number, call_id=call_id) or ""
        notes = _cap("notes", notes, call_id=call_id)
        caller_email = _cap("caller_email", caller_email, call_id=call_id)

        # Light email-shape validation. Google rejects malformed emails too,
        # but catching obvious mishearings here gives a friendlier error.
        if caller_email is not None:
            caller_email = caller_email.strip()
            if not _EMAIL_RE.match(caller_email):
                logger.info("book_appointment: invalid caller_email %r", caller_email)
                return (
                    "That email address didn't sound quite right. Could you "
                    "spell it out for me, or should I proceed without sending "
                    "an email invite?"
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
                caller_email=caller_email,
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

            # Reset cache to ONLY the new set. We deliberately discard the
            # previously-offered slots (some of which may still be free), to
            # force the LLM through a fresh check_availability if it wants
            # one of those — the previously-cached slots are stale (>=1
            # extra round-trip ago) and the safer path is "always re-check
            # when in doubt." Trade-off: one extra tool call vs. risk of
            # offering a now-also-stale slot.
            self._reset_offered_slots(s.start_iso for s in alternates)
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
        invite_msg = (
            f" I've also emailed a calendar invite to {caller_email}."
            if caller_email else ""
        )
        return (
            f"You're all set for {_format_friendly_date(confirmed)}.{invite_msg} "
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

    logger.info(
        "callerid: handle_call snapshot caller_phone=%s room=%s",
        lifecycle.metadata.caller_phone, ctx.room.name,
        extra={
            "call_id": lifecycle.metadata.call_id,
            "component": "agent.callerid",
            "source": "handle_call_snapshot",
            "remote_participants": [
                {
                    "identity": getattr(p, "identity", ""),
                    "kind": int(getattr(p, "kind", 0) or 0),
                    "attrs": sorted((getattr(p, "attributes", {}) or {}).keys()),
                }
                for p in ctx.room.remote_participants.values()
            ],
        },
    )

    def _handle_participant_connected(participant: rtc.RemoteParticipant) -> None:
        _capture_caller_phone_from_participant(
            lifecycle, participant, source="participant_connected",
        )

    def _handle_participant_attributes_changed(
        changed_attributes: dict[str, str], participant: rtc.RemoteParticipant,
    ) -> None:
        # SIP trunks sometimes publish caller-id attributes after the participant
        # has already joined the room (e.g. Telnyx INVITE → PRACK delay, Asterisk
        # diversion-header late update). Re-run capture if any sip.* attribute
        # changed and we don't have a phone yet.
        if lifecycle.metadata.caller_phone is not None:
            return
        if not any(k.startswith("sip.") for k in (changed_attributes or {})):
            return
        _capture_caller_phone_from_participant(
            lifecycle, participant, source="participant_attributes_changed",
        )

    ctx.room.on("participant_connected", _handle_participant_connected)
    ctx.room.on(
        "participant_attributes_changed", _handle_participant_attributes_changed,
    )
    for participant in ctx.room.remote_participants.values():
        _capture_caller_phone_from_participant(
            lifecycle, participant, source="initial_scan",
        )

    idle_cfg = config.voice.idle
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            model=config.voice.model,
            voice=config.voice.voice_id,
            api_key=await resolve_voice_bearer_async(config.voice.auth),
        ),
        # Issue #11: feed the silence-hangup `away_seconds` into LiveKit's
        # built-in user-state machine. When the caller falls silent for this
        # long, `user_state` flips to "away" and we start the grace timer.
        user_away_timeout=idle_cfg.away_seconds,
    )

    # Wire transcript capture BEFORE session starts so no events are missed.
    lifecycle.attach_transcript_capture(session)

    # Build the Receptionist BEFORE wiring its event listeners so we can
    # also subscribe to session events the agent needs (issue #11).
    receptionist = Receptionist(config, lifecycle)
    session.on("user_input_transcribed", receptionist._on_user_input_transcribed)
    session.on("function_tools_executed", receptionist._on_function_tools_executed)
    session.on("conversation_item_added", receptionist._on_conversation_item_added)

    # Issue #11 silence-timeout watcher. Holds a single TimerHandle that
    # the user_state_changed listener resets as the caller goes
    # away/listening/speaking. The closure captures `session` and
    # `lifecycle` so it doesn't need to walk through Receptionist.
    silence_state = {"timer": None, "scheduled": False}

    def _cancel_silence_timer() -> None:
        timer = silence_state["timer"]
        if timer is not None:
            timer.cancel()
            silence_state["timer"] = None

    def _on_silence_grace_expired() -> None:
        # Re-check user_state at fire time; the user may have come back.
        if session.user_state != "away":
            return
        if silence_state["scheduled"]:
            return
        silence_state["scheduled"] = True
        lifecycle.record_agent_ended("silence_timeout")

        async def _run() -> None:
            await _speak_goodbye_and_terminate(
                session, lifecycle, ctx, reason="silence_timeout",
            )

        asyncio.create_task(_run())

    def _on_user_state_changed(ev) -> None:
        if not idle_cfg.silence_hangup_enabled:
            return
        new_state = getattr(ev, "new_state", None)
        if new_state == "away":
            _cancel_silence_timer()
            loop = asyncio.get_event_loop()
            silence_state["timer"] = loop.call_later(
                idle_cfg.silence_grace_seconds, _on_silence_grace_expired,
            )
            logger.info(
                "silence_timeout: caller went away, hanging up in %.1fs unless they return",
                idle_cfg.silence_grace_seconds,
                extra={
                    "call_id": lifecycle.metadata.call_id,
                    "component": "agent.silence",
                    "grace_seconds": idle_cfg.silence_grace_seconds,
                },
            )
        else:
            _cancel_silence_timer()

    session.on("user_state_changed", _on_user_state_changed)

    # Issue #11 max-duration cap. Single one-shot timer scheduled at
    # session start; cancelled by the close handler so a normal hangup
    # doesn't double-fire the goodbye.
    duration_state: dict[str, asyncio.TimerHandle | bool | None] = {
        "timer": None, "scheduled": False,
    }

    def _on_max_duration_reached() -> None:
        if duration_state["scheduled"]:
            return
        duration_state["scheduled"] = True
        lifecycle.record_agent_ended("max_duration_reached")
        logger.warning(
            "max_duration: cap of %ds reached, ending call",
            idle_cfg.max_call_duration_seconds,
            extra={
                "call_id": lifecycle.metadata.call_id,
                "component": "agent.max_duration",
            },
        )

        async def _run() -> None:
            await _speak_goodbye_and_terminate(
                session, lifecycle, ctx, reason="max_duration_reached",
            )

        asyncio.create_task(_run())

    if idle_cfg.max_call_duration_seconds:
        loop = asyncio.get_event_loop()
        duration_state["timer"] = loop.call_later(
            idle_cfg.max_call_duration_seconds, _on_max_duration_reached,
        )

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
        # Issue #11: cancel any pending silence/duration timers so a normal
        # hangup doesn't accidentally fire goodbye-after-disconnect later.
        _cancel_silence_timer()
        timer = duration_state["timer"]
        if timer is not None:
            timer.cancel()
            duration_state["timer"] = None

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
        agent=receptionist,
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
