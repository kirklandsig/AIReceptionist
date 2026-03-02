from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator


class BusinessInfo(BaseModel):
    name: str
    type: str
    timezone: str


class VoiceConfig(BaseModel):
    voice_id: str = "coral"
    model: str = "gpt-realtime"


class DayHours(BaseModel):
    open: str
    close: str

    @field_validator("open", "close")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError(f"Time must be in HH:MM format, got: {v!r}")
        return v


class WeeklyHours(BaseModel):
    monday: Optional[DayHours] = None
    tuesday: Optional[DayHours] = None
    wednesday: Optional[DayHours] = None
    thursday: Optional[DayHours] = None
    friday: Optional[DayHours] = None
    saturday: Optional[DayHours] = None
    sunday: Optional[DayHours] = None

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


class DeliveryMethod(str, Enum):
    FILE = "file"
    WEBHOOK = "webhook"


class MessagesConfig(BaseModel):
    delivery: DeliveryMethod
    file_path: Optional[str] = None
    webhook_url: Optional[str] = None

    @model_validator(mode="after")
    def validate_delivery_fields(self) -> "MessagesConfig":
        if self.delivery == DeliveryMethod.FILE and not self.file_path:
            raise ValueError("file_path is required when delivery is 'file'")
        if self.delivery == DeliveryMethod.WEBHOOK and not self.webhook_url:
            raise ValueError("webhook_url is required when delivery is 'webhook'")
        return self


class BusinessConfig(BaseModel):
    business: BusinessInfo
    voice: VoiceConfig
    greeting: str
    personality: str
    hours: WeeklyHours
    after_hours_message: str
    routing: list[RoutingEntry]
    faqs: list[FAQEntry]
    messages: MessagesConfig

    @classmethod
    def from_yaml_string(cls, yaml_string: str) -> BusinessConfig:
        data = yaml.safe_load(yaml_string)
        return cls.model_validate(data)


def load_config(path: Path) -> BusinessConfig:
    text = path.read_text(encoding="utf-8")
    return BusinessConfig.from_yaml_string(text)
