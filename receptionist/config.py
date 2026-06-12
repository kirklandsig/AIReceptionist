# receptionist/config.py
from __future__ import annotations

import ipaddress
import logging
import os
import re
from pathlib import Path
from typing import Annotated, Literal, Union
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("receptionist")


class ConfigError(Exception):
    """Raised when a business config YAML can't be parsed or doesn't validate.

    Wraps both yaml.YAMLError (parse-time) and pydantic.ValidationError
    (schema-time) so callers don't need to catch both.
    """


# ---------------------------------------------------------------------------
# Existing unchanged-ish models
# ---------------------------------------------------------------------------

class BusinessInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    timezone: str

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"Invalid IANA timezone: {v!r}") from e
        return v


class APIKeyVoiceAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["api_key"]
    env: str = "OPENAI_API_KEY"


class CodexOAuthVoiceAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["oauth_codex"]
    path: str = "~/.codex/auth.json"


class StaticOAuthVoiceAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["oauth_static"]
    token: str | None = None
    token_env: str | None = None

    @model_validator(mode="after")
    def validate_single_token_source(self) -> StaticOAuthVoiceAuth:
        if bool(self.token) == bool(self.token_env):
            raise ValueError("oauth_static auth requires exactly one of token or token_env")
        return self


VoiceAuth = Annotated[
    Union[APIKeyVoiceAuth, CodexOAuthVoiceAuth, StaticOAuthVoiceAuth],
    Field(discriminator="type"),
]


class VoiceIdleConfig(BaseModel):
    """Issue #11 safety nets: silence timeout, max-duration cap, and
    unproductive-turn ceiling. Defaults are conservative so existing YAMLs
    remain backward-compatible: silence hangup is on (15s away + 30s grace =
    45s total caller silence before the agent says goodbye), max duration
    is OFF, and the unproductive-turn ceiling is 5 consecutive replies that
    look like the agent is stuck.
    """
    model_config = ConfigDict(extra="forbid")

    # ---- Silence hangup --------------------------------------------------
    silence_hangup_enabled: bool = True
    """Master switch for the silence-timeout path. When False, the agent
    never hangs up just because the caller stopped talking. The
    `away_seconds` value is still applied to LiveKit's `user_state` so
    other downstream consumers (analytics, dashboards) keep working."""

    away_seconds: float = Field(default=15.0, gt=0)
    """How long of silence flips LiveKit's `user_state` to `away`. Maps
    one-to-one to `AgentSession.user_away_timeout`. Below this, the caller
    is just thinking; above, they may have walked away from the phone."""

    silence_grace_seconds: float = Field(default=30.0, ge=0)
    """How long the agent waits after `user_state` becomes `away` before
    triggering the silence-timeout hangup. Set to 0 to hang up immediately
    on `away` (aggressive). Default 30s gives a long pause for callers who
    are looking up information or muting their phone."""

    # ---- Max call duration ----------------------------------------------
    max_call_duration_seconds: int | None = Field(default=None, gt=0)
    """Optional ceiling on the total call duration. None disables the cap
    entirely (default - preserve original behavior). Set to e.g. 900 to
    cap calls at 15 minutes; the agent will say goodbye and disconnect
    when the cap is reached."""

    # ---- Wall-clock silence fallback ------------------------------------
    absolute_silence_seconds: int | None = Field(default=None, gt=0)
    """Optional wall-clock silence fallback. None disables the fallback
    (default - preserve original behavior). Set to e.g. 120 to hang up when
    no final user transcript arrives for two minutes, even if SIP comfort
    noise keeps LiveKit's user_state from becoming away."""

    # ---- Unproductive turn ceiling --------------------------------------
    unproductive_hangup_enabled: bool = True
    """Master switch for the unproductive-turn safety net."""

    unproductive_turn_threshold: int = Field(default=5, gt=0)
    """How many consecutive `unproductive` agent replies trigger a hangup.
    A reply is considered unproductive if (a) the agent did NOT invoke any
    function tool that turn AND (b) the reply text matches one of the
    `unproductive_phrases` substrings (case-insensitive). Productive turns
    (any function tool call OR a substantive reply) reset the counter to 0.
    """

    unproductive_phrases: list[str] = Field(
        default_factory=lambda: [
            "i'm here to help",
            "i'm here to assist",
            "could you rephrase",
            "could you clarify",
            "i didn't quite catch",
            "i don't have specific information",
            "i'm not able to help with that",
            "i'm not sure i understand",
            "if you have a specific question",
        ]
    )
    """Substrings that signal the agent is stuck. Tunable per business so a
    plain-English clinic and a niche legal-research firm can adjust the
    deflection vocabulary. Matched case-insensitively against the agent's
    spoken reply."""


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: str = "marin"
    model: str = "gpt-realtime"
    auth: VoiceAuth | None = None
    idle: VoiceIdleConfig = Field(default_factory=VoiceIdleConfig)


class DayHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: str
    close: str

    @field_validator("open", "close")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError(f"Time must be in HH:MM 24-hour format, got: {v!r}")
        return v


class WeeklyHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monday: DayHours | None = None
    tuesday: DayHours | None = None
    wednesday: DayHours | None = None
    thursday: DayHours | None = None
    friday: DayHours | None = None
    saturday: DayHours | None = None
    sunday: DayHours | None = None

    @field_validator("*", mode="before")
    @classmethod
    def parse_closed(cls, v):
        if v == "closed":
            return None
        return v


class RoutingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    number: str
    description: str


# ---------------------------------------------------------------------------
# DTMF auto-attendant
# ---------------------------------------------------------------------------

_VALID_DTMF_DIGITS = {*"0123456789", "*", "#"}


class DtmfActionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["transfer", "take_message", "end_call", "repeat_menu"]
    routing: str | None = None
    acknowledgment_en: str
    acknowledgment_es: str | None = None


class DtmfConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    menu_announcement_en: str | None = None
    menu_announcement_es: str | None = None
    digits: dict[str, DtmfActionConfig] = Field(default_factory=dict)

    @field_validator("digits")
    @classmethod
    def _validate_digit_keys(cls, v: dict[str, DtmfActionConfig]) -> dict[str, DtmfActionConfig]:
        bad = [k for k in v.keys() if k not in _VALID_DTMF_DIGITS]
        if bad:
            raise ValueError(
                f"dtmf.digits has invalid keys {bad!r}; allowed: 0-9, *, #"
            )
        return v

    @model_validator(mode="after")
    def _repeat_menu_needs_menu_announcement_en(self) -> DtmfConfig:
        has_repeat = any(a.action == "repeat_menu" for a in self.digits.values())
        if has_repeat and not self.menu_announcement_en:
            raise ValueError(
                "dtmf.menu_announcement_en is required when any digit uses "
                "action=repeat_menu"
            )
        return self


class FAQEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------

class LanguagesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = "en"
    allowed: list[str] = Field(default_factory=lambda: ["en"])

    @field_validator("primary", "allowed")
    @classmethod
    def lowercase_codes(cls, v):
        if isinstance(v, str):
            return v.lower()
        return [s.lower() for s in v]

    @model_validator(mode="after")
    def primary_in_allowed(self) -> LanguagesConfig:
        if self.primary not in self.allowed:
            raise ValueError(
                f"languages.primary {self.primary!r} must appear in languages.allowed {self.allowed!r}"
            )
        return self


# ---------------------------------------------------------------------------
# Message channels (discriminated union on "type")
# ---------------------------------------------------------------------------

class FileChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["file"]
    file_path: str


class EmailChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["email"]
    to: list[str]
    include_transcript: bool = True
    include_recording_link: bool = True


class WebhookChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["webhook"]
    url: str
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _validate_url_safe(cls, v: str) -> str:
        """Reject non-http(s) schemes and warn (not reject) on private/loopback hosts.

        - Hard reject: file://, data:, javascript:, gopher:, etc. We only ever
          want webhooks to leave via HTTP(S).
        - Soft warn: loopback (127.0.0.0/8, ::1), private (10/8, 172.16/12,
          192.168/16, fc00::/7), link-local (169.254/16, fe80::/10). These are
          legitimate in dev (ngrok forwards, internal Slack relays) but a
          common foot-gun in prod (e.g. AWS metadata at 169.254.169.254).
        """
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"Webhook URL scheme must be http or https; got {parsed.scheme!r} in {v!r}. "
                f"file://, data:, javascript: and other schemes are rejected."
            )
        if not parsed.hostname:
            raise ValueError(f"Webhook URL has no host: {v!r}")

        # IP-literal check (don't try to resolve DNS at config-load time)
        try:
            ip = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            # Hostname is a domain — can't classify without DNS. Catch the
            # most common literal foot-guns by name.
            host = parsed.hostname.lower()
            if host in ("localhost",) or host.endswith(".localhost"):
                raise ValueError("Webhook URL must not target localhost")
        else:
            if ip.is_loopback or ip.is_private or ip.is_link_local:
                raise ValueError(
                    "Webhook URL must not target private, loopback, or link-local "
                    f"addresses; got {ip}"
                )
        return v


MessageChannel = Annotated[
    Union[FileChannel, EmailChannel, WebhookChannel],
    Field(discriminator="type"),
]


class MessagesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: list[MessageChannel]

    @model_validator(mode="before")
    @classmethod
    def convert_legacy_delivery(cls, data):
        """Accept legacy `delivery: file, file_path: ...` form and convert to channels list."""
        if not isinstance(data, dict):
            return data
        if "delivery" in data and "channels" not in data:
            delivery = data.pop("delivery")
            if delivery == "file":
                data["channels"] = [{"type": "file", "file_path": data.pop("file_path", "./messages/")}]
            elif delivery == "webhook":
                data["channels"] = [{"type": "webhook", "url": data.pop("webhook_url", "")}]
            else:
                raise ValueError(f"Unknown legacy delivery: {delivery!r}")
        return data


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

class LocalStorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class S3StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket: str
    region: str
    prefix: str = ""
    endpoint_url: str | None = None


class RecordingStorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["local", "s3"]
    local: LocalStorageConfig | None = None
    s3: S3StorageConfig | None = None

    @model_validator(mode="after")
    def validate_matching_subconfig(self) -> RecordingStorageConfig:
        if self.type == "local" and self.local is None:
            raise ValueError("recording.storage.local required when type is 'local'")
        if self.type == "s3" and self.s3 is None:
            raise ValueError("recording.storage.s3 required when type is 's3'")
        return self


class ConsentPreambleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    text: str = "This call may be recorded for quality purposes."


class RecordingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    storage: RecordingStorageConfig
    consent_preamble: ConsentPreambleConfig = Field(default_factory=ConsentPreambleConfig)


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------

class TranscriptStorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["local"]
    path: str


class TranscriptsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    storage: TranscriptStorageConfig
    formats: list[Literal["json", "markdown"]] = Field(default_factory=lambda: ["json", "markdown"])


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

class SMTPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 587
    username: str
    password: str
    use_tls: bool = True


class ResendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str


class EmailSenderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["smtp", "resend"]
    smtp: SMTPConfig | None = None
    resend: ResendConfig | None = None

    @model_validator(mode="after")
    def validate_matching_subconfig(self) -> EmailSenderConfig:
        if self.type == "smtp" and self.smtp is None:
            raise ValueError("email.sender.smtp required when type is 'smtp'")
        if self.type == "resend" and self.resend is None:
            raise ValueError("email.sender.resend required when type is 'resend'")
        return self


class EmailTriggers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_message: bool = True
    on_call_end: bool = False
    on_booking: bool = False


class EmailSummaryConfig(BaseModel):
    """Post-call AI summary settings for the consolidated call-end email.

    enabled with a missing API-key env var degrades gracefully: the email
    is sent without a Summary section and a warning is logged.
    """
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    enabled: bool = True
    model: str = "gpt-5-mini"
    reasoning_effort: str | None = "medium"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 20.0
    max_transcript_chars: int = 24000

    @field_validator("model")
    @classmethod
    def _model_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("email.summary.model must be non-empty")
        return v

    @field_validator("timeout_seconds")
    @classmethod
    def _timeout_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("email.summary.timeout_seconds must be > 0")
        return v

    @field_validator("max_transcript_chars")
    @classmethod
    def _max_chars_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("email.summary.max_transcript_chars must be > 0")
        return v


class EmailConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_: str = Field(alias="from")
    sender: EmailSenderConfig
    triggers: EmailTriggers = Field(default_factory=EmailTriggers)
    summary: EmailSummaryConfig = Field(default_factory=EmailSummaryConfig)


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

class RetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recordings_days: int = 90
    transcripts_days: int = 90
    messages_days: int = 0  # 0 = keep forever


# ---------------------------------------------------------------------------
# SIP transfer config
# ---------------------------------------------------------------------------

class SipConfig(BaseModel):
    """Per-business SIP behavior. Today only the transfer URI scheme is configurable.

    `transfer_uri_template` is the format string the agent uses when telling
    LiveKit how to dial the routing target during a transfer. It must contain
    the literal `{number}` placeholder, which is substituted with the routing
    target's `number` field.

    Defaults to `tel:{number}` which works for Twilio, Telnyx, and most BYOC
    providers that translate tel-URIs to SIP. For Asterisk classic sip.conf
    (which rejects tel-URIs), use `sip:{number}` for local DID transfers, or
    `sip:{number}@your-pbx.example.com` for transfers to a remote SIP PBX.
    """
    model_config = ConfigDict(extra="forbid")

    transfer_uri_template: str = "tel:{number}"

    @field_validator("transfer_uri_template")
    @classmethod
    def _has_number_placeholder(cls, v: str) -> str:
        if "{number}" not in v:
            raise ValueError(
                f"transfer_uri_template must contain '{{number}}' placeholder; got: {v!r}"
            )
        return v


# ---------------------------------------------------------------------------
# Calendar — Google Calendar integration
# ---------------------------------------------------------------------------

class ServiceAccountAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["service_account"]
    service_account_file: str


class OAuthAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["oauth"]
    oauth_token_file: str


CalendarAuth = Annotated[
    Union[ServiceAccountAuth, OAuthAuth],
    Field(discriminator="type"),
]


class CalendarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    calendar_id: str = "primary"
    auth: CalendarAuth
    appointment_duration_minutes: int = Field(default=30, gt=0)
    buffer_minutes: int = Field(default=15, ge=0)
    buffer_placement: Literal["before", "after", "both"] = "after"
    booking_window_days: int = Field(default=30, gt=0, le=90)
    earliest_booking_hours_ahead: int = Field(default=2, ge=0)

    @model_validator(mode="after")
    def validate_auth_file_exists(self) -> CalendarConfig:
        """If enabled, require the configured auth file to exist on disk.

        Fail fast at agent startup, not at first call.
        """
        if not self.enabled:
            return self
        path_str = (
            self.auth.service_account_file
            if isinstance(self.auth, ServiceAccountAuth)
            else self.auth.oauth_token_file
        )
        path = Path(path_str)
        if not path.exists():
            raise ValueError(
                f"calendar auth file not found: {path_str}. "
                f"Did you run `python -m receptionist.booking setup <business-slug>`?"
            )
        return self


# ---------------------------------------------------------------------------
# Intakes — structured new-client intake by phone
# ---------------------------------------------------------------------------

# Validation kinds Riley can apply per question. Free-text is the default;
# "phone" / "email" / "date" / "yes_no" let the prompt nudge Riley toward
# the right shape and let downstream tooling (sync CLI, intake email) format
# the answer cleanly. These are advisory — the LLM is not bound to refuse
# malformed answers, only to ask for clarification.
_INTAKE_VALIDATION_KINDS = Literal["text", "phone", "email", "date", "yes_no"]


class IntakeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    """Canonical field name, e.g. `employer` or `accident_date`. Used as the
    answer key in the structured intake JSON. Must be unique within a case
    type. Stable across question wording changes so downstream consumers
    keep working."""

    prompt_en: str
    """The English question Riley reads to the caller verbatim."""

    prompt_es: str | None = None
    """Spanish translation of the question. If omitted, Riley will translate
    the English prompt at call time, which is less reliable. Strongly
    recommended for any business that handles Spanish-speaking callers."""

    required: bool = True
    """If False, Riley may skip the question if the caller declines to
    answer. Required questions must be present in the final submission."""

    validation: _INTAKE_VALIDATION_KINDS = "text"
    """Advisory shape hint. Drives the prompt phrasing in the persona and
    the formatting of the answer in the intake email."""

    critical: bool = False
    """If True, Riley does an explicit readback ("I have your callback as
    six-three-one… is that right?") and waits for confirmation before
    moving on. Use for legal name, callback number, email, DOB."""


class IntakeCaseType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    """Canonical identifier, e.g. `workers_comp`, `ssd`, `pension`. Used by
    the LLM when calling `record_intake_answer(case_type=...)`."""

    display_name: str
    """Human-readable name used in the intake email subject and in Riley's
    English-language spoken responses."""

    display_name_es: str | None = None
    """Spanish display name. Used by Riley in Spanish-language calls."""

    google_form_id: str | None = None
    """Optional Google Form ID for the sync CLI. Not used at call time."""

    questions: list[IntakeQuestion]

    @field_validator("questions")
    @classmethod
    def at_least_one_question(cls, v: list[IntakeQuestion]) -> list[IntakeQuestion]:
        if not v:
            raise ValueError("intake case type must define at least one question")
        return v

    @model_validator(mode="after")
    def unique_question_keys(self) -> IntakeCaseType:
        seen: set[str] = set()
        for q in self.questions:
            if q.key in seen:
                raise ValueError(
                    f"duplicate intake question key {q.key!r} in case type {self.key!r}"
                )
            seen.add(q.key)
        return self


class IntakeSubmissionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    """Directory where partial and final intake JSON files are written. The
    intake email goes to whichever EmailChannel(s) are configured in
    `messages.channels` — recipients live there, not here, so that operators
    have a single source of truth for who gets notified."""


class IntakesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    """Master switch. When False, the intake tools are still registered (so
    a YAML toggle is enough to enable later) but Riley is told in the
    system prompt that intake is unavailable and the tools refuse calls."""

    preamble_en: str = ""
    """English-language disclosure Riley speaks BEFORE starting questions.
    Typically "this takes 15-20 minutes, do you have time now or should I
    take a short message?" Empty string disables the preamble."""

    preamble_es: str | None = None
    """Spanish preamble. If None, Riley translates `preamble_en` at call
    time when speaking to a Spanish-speaking caller."""

    submission: IntakeSubmissionConfig

    case_types: list[IntakeCaseType]

    @field_validator("case_types")
    @classmethod
    def at_least_one_case_type(cls, v: list[IntakeCaseType]) -> list[IntakeCaseType]:
        if not v:
            raise ValueError("intakes config must define at least one case type")
        return v

    @model_validator(mode="after")
    def unique_case_type_keys(self) -> IntakesConfig:
        seen: set[str] = set()
        for ct in self.case_types:
            if ct.key in seen:
                raise ValueError(f"duplicate intake case type key {ct.key!r}")
            seen.add(ct.key)
        return self


# ---------------------------------------------------------------------------
# Agent mode and approved info packets
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["receptionist", "intake_only"] = "receptionist"


class InfoPacketLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    url: str

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("info packet link URL must be http or https")
        return v


class InfoPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    display_name: str
    email_subject: str
    email_body: str
    links: list[InfoPacketLink] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", v):
            raise ValueError("info packet key must be a safe identifier")
        return v


class InfoPacketsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    default_packet: str | None = None
    packets: list[InfoPacket] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_packets(self) -> InfoPacketsConfig:
        keys = [packet.key for packet in self.packets]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate info packet key")
        if self.enabled and not self.packets:
            raise ValueError("info_packets.enabled requires at least one packet")
        if self.default_packet is not None and self.default_packet not in set(keys):
            raise ValueError(
                "info_packets.default_packet must match a configured packet key"
            )
        return self

    def by_key(self) -> dict[str, InfoPacket]:
        return {packet.key: packet for packet in self.packets}


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

class BusinessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business: BusinessInfo
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    languages: LanguagesConfig = Field(default_factory=LanguagesConfig)
    greeting: str
    personality: str
    hours: WeeklyHours
    after_hours_message: str
    routing: list[RoutingEntry]
    faqs: list[FAQEntry]
    messages: MessagesConfig
    recording: RecordingConfig | None = None
    transcripts: TranscriptsConfig | None = None
    email: EmailConfig | None = None
    calendar: CalendarConfig | None = None
    intakes: IntakesConfig | None = None
    sip: SipConfig = Field(default_factory=SipConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    info_packets: InfoPacketsConfig | None = None
    dtmf: DtmfConfig | None = None

    @model_validator(mode="after")
    def _dtmf_transfer_routing_must_exist(self) -> BusinessConfig:
        if self.dtmf is None:
            return self
        known = {entry.name for entry in self.routing}
        for digit, action_cfg in self.dtmf.digits.items():
            if action_cfg.action != "transfer":
                continue
            if not action_cfg.routing:
                raise ValueError(
                    f"dtmf.digits[{digit!r}] uses action=transfer but has no "
                    f"`routing`; set it to one of {sorted(known)!r}"
                )
            if action_cfg.routing not in known:
                raise ValueError(
                    f"dtmf.digits[{digit!r}] references routing entry "
                    f"{action_cfg.routing!r} which does not exist. Known routing "
                    f"entries: {sorted(known)!r}"
                )
        return self

    @model_validator(mode="after")
    def validate_cross_section(self) -> BusinessConfig:
        needs_email = any(c.type == "email" for c in self.messages.channels)
        if self.email:
            if self.email.triggers.on_call_end:
                needs_email = True
            if self.email.triggers.on_booking:
                needs_email = True
        if needs_email and self.email is None:
            raise ValueError(
                "email channel or on_call_end/on_booking trigger is configured but "
                "no top-level `email` section is present"
            )
        # NEW: on_booking trigger requires calendar enabled
        if self.email and self.email.triggers.on_booking and (
            self.calendar is None or not self.calendar.enabled
        ):
            raise ValueError(
                "email.triggers.on_booking is true but calendar is not enabled. "
                "Enable calendar or disable the on_booking trigger."
            )
        if (
            self.info_packets is not None
            and self.info_packets.enabled
            and self.email is None
        ):
            raise ValueError("info_packets.enabled requires top-level email config")
        # Intakes deliver their submission email through whichever email
        # channels are already in `messages.channels`, so enabling intakes
        # without an email channel means the operator only gets the file
        # artifact. That's OK (file is the durable copy) but warn in the
        # prompt-build path; here we just require the file_path to be set,
        # which Pydantic already enforces.
        return self

    @classmethod
    def from_yaml_string(cls, yaml_string: str) -> BusinessConfig:
        try:
            data = yaml.safe_load(yaml_string)
        except yaml.YAMLError as e:
            raise ConfigError(_friendly_yaml_error(e, yaml_string)) from e
        data = _interpolate_env_vars(data)
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# YAML error helpers
# ---------------------------------------------------------------------------

# Matches a key like " sip:" or "  recording:" — leading whitespace + plain
# identifier + colon at end-of-line. Used to detect the most common config
# pitfall: uncommenting a "# section:" block by removing only "#", leaving
# the line indented by one space. YAML then sees the section as nested under
# the previous block and the parser error points at the "wrong" line.
_LEADING_WS_KEY_RE = re.compile(r"^\s+([a-z_][a-z0-9_]*)\s*:\s*(?:#.*)?$", re.IGNORECASE)


def _friendly_yaml_error(e: yaml.YAMLError, source: str) -> str:
    """Translate a yaml parse error into something an operator can act on.

    Catches the indentation trap from uncommenting "# section:" blocks where
    the user left a leading space. Falls back to a clear-but-generic message
    that still includes the underlying yaml position.
    """
    base = str(e)
    mark = getattr(e, "problem_mark", None)
    if mark is None:
        return f"Config YAML failed to parse:\n{base}"

    lineno = mark.line + 1  # mark uses 0-based; humans want 1-based
    col = mark.column + 1
    lines = source.splitlines()
    offending_line = lines[mark.line] if 0 <= mark.line < len(lines) else ""

    # Detect the specific "I uncommented and left a leading space" trap so we
    # can give an actionable hint rather than the cryptic raw yaml message.
    m = _LEADING_WS_KEY_RE.match(offending_line)
    if (
        m is not None
        and "block end" in (getattr(e, "problem", "") or "")
    ):
        key = m.group(1)
        return (
            f"Config YAML indentation error at line {lineno}: '{offending_line.strip()}' "
            f"is indented with {col - 1} space(s) but appears to be a top-level "
            f"section. If you just uncommented a '# {key}:' example block, "
            f"remove BOTH the leading '#' AND the space after it so '{key}:' "
            f"starts at column 0.\n\n"
            f"Original yaml error:\n{base}"
        )
    return f"Config YAML failed to parse at line {lineno}, column {col}:\n{base}"


# ---------------------------------------------------------------------------
# Env var interpolation
# ---------------------------------------------------------------------------

_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
# Matches the *shape* of an env-var placeholder (`${...}`) so we can detect
# lowercase or invalid placeholders that look like an interpolation attempt
# but won't be expanded by _ENV_PATTERN. Anything else (e.g. plain "${" in a
# greeting because it really is the literal characters "$" + "{") is left
# alone because it does not look like a placeholder.
_ENV_PLACEHOLDER_SHAPE = re.compile(r"\$\{[^}\s]*\}")


def _interpolate_env_vars(node):
    if isinstance(node, str):
        def _replace(match: re.Match) -> str:
            var = match.group(1)
            if var not in os.environ:
                raise ValueError(f"Environment variable {var} referenced in config but not set")
            return os.environ[var]
        interpolated = _ENV_PATTERN.sub(_replace, node)
        remaining = _ENV_PLACEHOLDER_SHAPE.search(interpolated)
        if remaining is not None:
            raise ValueError(
                f"Invalid environment variable placeholder {remaining.group(0)!r}. "
                "Use ${UPPERCASE_NAME} with uppercase ASCII letters, digits, and underscores."
            )
        return interpolated
    if isinstance(node, dict):
        return {k: _interpolate_env_vars(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_interpolate_env_vars(v) for v in node]
    return node


# ---------------------------------------------------------------------------
# File loader
# ---------------------------------------------------------------------------

def load_config(path: Path | str) -> BusinessConfig:
    text = Path(path).read_text(encoding="utf-8")
    return BusinessConfig.from_yaml_string(text)


