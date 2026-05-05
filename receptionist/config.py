# receptionist/config.py
from __future__ import annotations

import ipaddress
import logging
import os
import re
from pathlib import Path
from typing import Annotated, Literal, Union
from urllib.parse import urlparse

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
    name: str
    type: str
    timezone: str


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
    entirely (default — preserve original behavior). Set to e.g. 900 to
    cap calls at 15 minutes; the agent will say goodbye and disconnect
    when the cap is reached."""

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
    model: str = "gpt-realtime-1.5"
    auth: VoiceAuth | None = None
    idle: VoiceIdleConfig = Field(default_factory=VoiceIdleConfig)


class DayHours(BaseModel):
    open: str
    close: str

    @field_validator("open", "close")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError(f"Time must be in HH:MM 24-hour format, got: {v!r}")
        return v


class WeeklyHours(BaseModel):
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
    name: str
    number: str
    description: str


class FAQEntry(BaseModel):
    question: str
    answer: str


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------

class LanguagesConfig(BaseModel):
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
    type: Literal["file"]
    file_path: str


class EmailChannel(BaseModel):
    type: Literal["email"]
    to: list[str]
    include_transcript: bool = True
    include_recording_link: bool = True


class WebhookChannel(BaseModel):
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
            if ip.is_loopback or ip.is_private or ip.is_link_local:
                logger.warning(
                    "Webhook URL %r points at a loopback/private/link-local "
                    "address (%s). Fine in dev (ngrok / internal relays); in "
                    "production this can leak data to the AWS metadata "
                    "endpoint or other internal services.",
                    v, ip,
                )
        except ValueError:
            # Hostname is a domain — can't classify without DNS. Catch the
            # most common literal foot-guns by name.
            host = parsed.hostname.lower()
            if host in ("localhost",) or host.endswith(".localhost"):
                logger.warning(
                    "Webhook URL %r targets localhost. Fine in dev; in "
                    "production this likely indicates a misconfiguration.",
                    v,
                )
        return v


MessageChannel = Annotated[
    Union[FileChannel, EmailChannel, WebhookChannel],
    Field(discriminator="type"),
]


class MessagesConfig(BaseModel):
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
    path: str


class S3StorageConfig(BaseModel):
    bucket: str
    region: str
    prefix: str = ""
    endpoint_url: str | None = None


class RecordingStorageConfig(BaseModel):
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
    enabled: bool = True
    text: str = "This call may be recorded for quality purposes."


class RecordingConfig(BaseModel):
    enabled: bool
    storage: RecordingStorageConfig
    consent_preamble: ConsentPreambleConfig = Field(default_factory=ConsentPreambleConfig)


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------

class TranscriptStorageConfig(BaseModel):
    type: Literal["local"]
    path: str


class TranscriptsConfig(BaseModel):
    enabled: bool
    storage: TranscriptStorageConfig
    formats: list[Literal["json", "markdown"]] = Field(default_factory=lambda: ["json", "markdown"])


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

class SMTPConfig(BaseModel):
    host: str
    port: int = 587
    username: str
    password: str
    use_tls: bool = True


class ResendConfig(BaseModel):
    api_key: str


class EmailSenderConfig(BaseModel):
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
    on_message: bool = True
    on_call_end: bool = False
    on_booking: bool = False


class EmailConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    sender: EmailSenderConfig
    triggers: EmailTriggers = Field(default_factory=EmailTriggers)


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

class RetentionConfig(BaseModel):
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
    enabled: bool
    calendar_id: str = "primary"
    auth: CalendarAuth
    appointment_duration_minutes: int = Field(default=30, gt=0)
    buffer_minutes: int = Field(default=15, ge=0)
    buffer_placement: Literal["before", "after", "both"] = "after"
    booking_window_days: int = Field(default=30, gt=0)
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
# Top-level
# ---------------------------------------------------------------------------

class BusinessConfig(BaseModel):
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
    sip: SipConfig = Field(default_factory=SipConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)

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


def _interpolate_env_vars(node):
    if isinstance(node, str):
        def _replace(match: re.Match) -> str:
            var = match.group(1)
            if var not in os.environ:
                raise ValueError(f"Environment variable {var} referenced in config but not set")
            return os.environ[var]
        return _ENV_PATTERN.sub(_replace, node)
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


