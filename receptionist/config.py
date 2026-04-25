# receptionist/config.py
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Existing unchanged-ish models
# ---------------------------------------------------------------------------

class BusinessInfo(BaseModel):
    name: str
    type: str
    timezone: str


class VoiceConfig(BaseModel):
    voice_id: str = "marin"
    model: str = "gpt-realtime-1.5"


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
    retention: RetentionConfig = Field(default_factory=RetentionConfig)

    @model_validator(mode="after")
    def validate_cross_section(self) -> BusinessConfig:
        needs_email = any(c.type == "email" for c in self.messages.channels)
        if self.email and self.email.triggers.on_call_end:
            needs_email = True
        if needs_email and self.email is None:
            raise ValueError(
                "email channel or on_call_end trigger is configured but no top-level `email` section is present"
            )
        return self

    @classmethod
    def from_yaml_string(cls, yaml_string: str) -> BusinessConfig:
        data = yaml.safe_load(yaml_string)
        data = _interpolate_env_vars(data)
        return cls.model_validate(data)


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


