# AI Receptionist Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an open-source AI phone receptionist using OpenAI Realtime API + LiveKit Agents SDK that handles inbound calls with FAQ answering, call transfers, and message taking.

**Architecture:** LiveKit Agents SDK handles real-time audio transport and SIP telephony. OpenAI Realtime API provides speech-to-speech voice intelligence. Business configuration is YAML-based with Pydantic validation. No database required.

**Tech Stack:** Python 3.11+, LiveKit Agents SDK, OpenAI Realtime plugin, Pydantic, PyYAML, pytest

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `receptionist/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ai-receptionist"
version = "0.1.0"
description = "High-fidelity AI phone receptionist using OpenAI Realtime API and LiveKit"
requires-python = ">=3.11"
dependencies = [
    "livekit-agents>=1.0.0",
    "livekit-plugins-openai>=1.0.0",
    "livekit-plugins-noise-cancellation>=1.0.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]
```

**Step 2: Create .env.example**

```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
OPENAI_API_KEY=your-openai-api-key
```

**Step 3: Create .gitignore**

```
__pycache__/
*.py[cod]
.env
.env.local
*.egg-info/
dist/
build/
.venv/
venv/
messages/
.pytest_cache/
```

**Step 4: Create receptionist/__init__.py**

```python
```

(Empty file — just marks the package.)

**Step 5: Create directory structure**

```bash
mkdir -p config/businesses messages tests
```

**Step 6: Install dependencies**

Run: `pip install -e ".[dev]"`
Expected: All packages install successfully.

**Step 7: Commit**

```bash
git init
git add pyproject.toml .env.example .gitignore receptionist/__init__.py
git commit -m "chore: initial project scaffolding with dependencies"
```

---

### Task 2: Business Configuration (Pydantic Models + YAML Loader)

**Files:**
- Create: `receptionist/config.py`
- Create: `config/businesses/example-dental.yaml`
- Create: `tests/test_config.py`

**Step 1: Write the failing tests**

```python
# tests/test_config.py
import pytest
from pathlib import Path
from receptionist.config import BusinessConfig, load_config


EXAMPLE_YAML = """
business:
  name: "Test Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "coral"

greeting: "Thank you for calling Test Dental."

personality: "You are a friendly receptionist."

hours:
  monday: { open: "08:00", close: "17:00" }
  tuesday: { open: "08:00", close: "17:00" }
  wednesday: closed
  thursday: { open: "08:00", close: "17:00" }
  friday: { open: "08:00", close: "15:00" }
  saturday: closed
  sunday: closed

after_hours_message: "We are currently closed."

routing:
  - name: "Front Desk"
    number: "+15551234567"
    description: "General inquiries"

faqs:
  - question: "Where are you located?"
    answer: "123 Main Street."

messages:
  delivery: "file"
  file_path: "./messages/test-dental/"
"""


def test_load_config_from_yaml_string():
    config = BusinessConfig.from_yaml_string(EXAMPLE_YAML)
    assert config.business.name == "Test Dental"
    assert config.business.timezone == "America/New_York"
    assert config.voice.voice_id == "coral"
    assert config.greeting == "Thank you for calling Test Dental."
    assert len(config.routing) == 1
    assert config.routing[0].number == "+15551234567"
    assert len(config.faqs) == 1


def test_load_config_from_file(tmp_path):
    config_file = tmp_path / "test.yaml"
    config_file.write_text(EXAMPLE_YAML)
    config = load_config(config_file)
    assert config.business.name == "Test Dental"


def test_hours_closed_day():
    config = BusinessConfig.from_yaml_string(EXAMPLE_YAML)
    assert config.hours.wednesday is None


def test_hours_open_day():
    config = BusinessConfig.from_yaml_string(EXAMPLE_YAML)
    assert config.hours.monday is not None
    assert config.hours.monday.open == "08:00"
    assert config.hours.monday.close == "17:00"


def test_config_validation_missing_business_name():
    bad_yaml = """
business:
  type: "dental office"
  timezone: "America/New_York"
voice:
  voice_id: "coral"
greeting: "Hello"
personality: "Be nice"
hours:
  monday: closed
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  delivery: "file"
  file_path: "./messages/test/"
"""
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(bad_yaml)


def test_config_validation_invalid_delivery():
    bad_yaml = """
business:
  name: "Test"
  type: "test"
  timezone: "America/New_York"
voice:
  voice_id: "coral"
greeting: "Hello"
personality: "Be nice"
hours:
  monday: closed
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  delivery: "carrier_pigeon"
  file_path: "./messages/test/"
"""
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(bad_yaml)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'receptionist.config'`

**Step 3: Write the implementation**

```python
# receptionist/config.py
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator


class BusinessInfo(BaseModel):
    name: str
    type: str
    timezone: str


class VoiceConfig(BaseModel):
    voice_id: str = "coral"


class DayHours(BaseModel):
    open: str
    close: str


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
    text = path.read_text()
    return BusinessConfig.from_yaml_string(text)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: All 6 tests PASS

**Step 5: Create the example config file**

```yaml
# config/businesses/example-dental.yaml

business:
  name: "Acme Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "coral"

greeting: "Thank you for calling Acme Dental, how can I help you today?"

personality: |
  You are a warm, professional receptionist for a dental office.
  Be concise but friendly. If you don't know something, offer to
  take a message or transfer to the office manager.

hours:
  monday:    { open: "08:00", close: "17:00" }
  tuesday:   { open: "08:00", close: "17:00" }
  wednesday: { open: "08:00", close: "12:00" }
  thursday:  { open: "08:00", close: "17:00" }
  friday:    { open: "08:00", close: "15:00" }
  saturday:  closed
  sunday:    closed

after_hours_message: |
  Our office is currently closed. Our regular hours are Monday
  through Friday. Would you like to leave a message?

routing:
  - name: "Front Desk"
    number: "+15551234567"
    description: "General inquiries, scheduling"
  - name: "Dr. Smith"
    number: "+15551234568"
    description: "Direct line for urgent dental issues"
  - name: "Billing"
    number: "+15551234569"
    description: "Insurance and payment questions"

faqs:
  - question: "Do you accept my insurance?"
    answer: "We accept most major dental insurance plans including Delta Dental, Cigna, Aetna, and MetLife. For other plans, we can verify your coverage when you call."
  - question: "How do I schedule an appointment?"
    answer: "I can transfer you to our front desk to schedule, or you can book online at acmedental.com/book."
  - question: "Where are you located?"
    answer: "We're at 123 Main Street, Suite 200, Springfield. Right next to the Springfield Mall."
  - question: "What should I do for a dental emergency?"
    answer: "For a dental emergency during business hours, I'll transfer you directly to Dr. Smith. After hours, please call 911 for life-threatening emergencies or visit the nearest emergency room."

messages:
  delivery: "file"
  file_path: "./messages/acme-dental/"
```

**Step 6: Commit**

```bash
git add receptionist/config.py config/businesses/example-dental.yaml tests/test_config.py
git commit -m "feat: business config Pydantic models with YAML loading and validation"
```

---

### Task 3: System Prompt Builder

**Files:**
- Create: `receptionist/prompts.py`
- Create: `tests/test_prompts.py`

**Step 1: Write the failing tests**

```python
# tests/test_prompts.py
from receptionist.config import BusinessConfig
from receptionist.prompts import build_system_prompt


EXAMPLE_YAML = """
business:
  name: "Test Dental"
  type: "dental office"
  timezone: "America/New_York"
voice:
  voice_id: "coral"
greeting: "Thank you for calling Test Dental."
personality: "You are a friendly receptionist."
hours:
  monday: { open: "08:00", close: "17:00" }
  tuesday: { open: "08:00", close: "17:00" }
  wednesday: closed
  thursday: { open: "08:00", close: "17:00" }
  friday: { open: "08:00", close: "15:00" }
  saturday: closed
  sunday: closed
after_hours_message: "We are currently closed."
routing:
  - name: "Front Desk"
    number: "+15551234567"
    description: "General inquiries"
  - name: "Billing"
    number: "+15551234569"
    description: "Payment questions"
faqs:
  - question: "Where are you located?"
    answer: "123 Main Street."
  - question: "Do you accept insurance?"
    answer: "Yes, most plans."
messages:
  delivery: "file"
  file_path: "./messages/test/"
"""


def _make_config():
    return BusinessConfig.from_yaml_string(EXAMPLE_YAML)


def test_prompt_contains_business_name():
    prompt = build_system_prompt(_make_config())
    assert "Test Dental" in prompt


def test_prompt_contains_personality():
    prompt = build_system_prompt(_make_config())
    assert "friendly receptionist" in prompt


def test_prompt_contains_faq_content():
    prompt = build_system_prompt(_make_config())
    assert "Where are you located?" in prompt
    assert "123 Main Street." in prompt


def test_prompt_contains_routing_info():
    prompt = build_system_prompt(_make_config())
    assert "Front Desk" in prompt
    assert "Billing" in prompt


def test_prompt_contains_hours():
    prompt = build_system_prompt(_make_config())
    assert "Monday" in prompt
    assert "08:00" in prompt


def test_prompt_contains_after_hours_instructions():
    prompt = build_system_prompt(_make_config())
    assert "currently closed" in prompt
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'receptionist.prompts'`

**Step 3: Write the implementation**

```python
# receptionist/prompts.py
from receptionist.config import BusinessConfig


def build_system_prompt(config: BusinessConfig) -> str:
    hours_lines = []
    for day_name in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        day_hours = getattr(config.hours, day_name)
        display_name = day_name.capitalize()
        if day_hours is None:
            hours_lines.append(f"  {display_name}: Closed")
        else:
            hours_lines.append(f"  {display_name}: {day_hours.open} - {day_hours.close}")
    hours_block = "\n".join(hours_lines)

    routing_lines = []
    for entry in config.routing:
        routing_lines.append(f"  - {entry.name}: {entry.description}")
    routing_block = "\n".join(routing_lines) if routing_lines else "  No routing configured."

    faq_lines = []
    for faq in config.faqs:
        faq_lines.append(f"  Q: {faq.question}\n  A: {faq.answer}")
    faq_block = "\n\n".join(faq_lines) if faq_lines else "  No FAQs configured."

    return f"""You are the receptionist for {config.business.name}, a {config.business.type}.

{config.personality}

BUSINESS HOURS (timezone: {config.business.timezone}):
{hours_block}

When the business is closed, say: {config.after_hours_message}

DEPARTMENTS YOU CAN TRANSFER TO:
{routing_block}

When a caller asks to be transferred, use the transfer_call tool with the department name.
When a caller wants to leave a message, use the take_message tool to record their name, message, and callback number.
When asked about business hours, use the get_business_hours tool.

FREQUENTLY ASKED QUESTIONS:
{faq_block}

You can answer these questions directly. For questions not covered here, offer to take a message or transfer the caller to the appropriate department.

IMPORTANT RULES:
- Be concise. Phone conversations should be efficient.
- Never make up information. If you don't know, say so and offer alternatives.
- Always confirm before transferring a call.
- If the caller seems upset, be empathetic and offer to connect them with a person.
"""
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompts.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add receptionist/prompts.py tests/test_prompts.py
git commit -m "feat: system prompt builder from business config"
```

---

### Task 4: Message Storage

**Files:**
- Create: `receptionist/messages.py`
- Create: `tests/test_messages.py`

**Step 1: Write the failing tests**

```python
# tests/test_messages.py
import json
from pathlib import Path
from receptionist.messages import save_message, Message


def test_save_message_creates_file(tmp_path):
    msg = Message(
        caller_name="John Doe",
        callback_number="+15559876543",
        message="Please call me back about my appointment.",
        business_name="Test Dental",
    )
    save_message(msg, delivery="file", file_path=str(tmp_path))

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1

    data = json.loads(files[0].read_text())
    assert data["caller_name"] == "John Doe"
    assert data["callback_number"] == "+15559876543"
    assert data["message"] == "Please call me back about my appointment."
    assert data["business_name"] == "Test Dental"
    assert "timestamp" in data


def test_save_multiple_messages(tmp_path):
    for i in range(3):
        msg = Message(
            caller_name=f"Caller {i}",
            callback_number=f"+1555000000{i}",
            message=f"Message {i}",
            business_name="Test Dental",
        )
        save_message(msg, delivery="file", file_path=str(tmp_path))

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 3


def test_save_message_creates_directory(tmp_path):
    nested = tmp_path / "sub" / "dir"
    msg = Message(
        caller_name="Jane",
        callback_number="+15551111111",
        message="Test",
        business_name="Test Dental",
    )
    save_message(msg, delivery="file", file_path=str(nested))
    assert nested.exists()
    assert len(list(nested.glob("*.json"))) == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_messages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'receptionist.messages'`

**Step 3: Write the implementation**

```python
# receptionist/messages.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class Message:
    caller_name: str
    callback_number: str
    message: str
    business_name: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def save_message(msg: Message, delivery: str, file_path: str | None = None, webhook_url: str | None = None) -> None:
    if delivery == "file":
        _save_to_file(msg, file_path)
    elif delivery == "webhook":
        _send_webhook(msg, webhook_url)
    else:
        raise ValueError(f"Unknown delivery method: {delivery}")


def _save_to_file(msg: Message, file_path: str | None) -> None:
    if file_path is None:
        raise ValueError("file_path is required for file delivery")

    directory = Path(file_path)
    directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"message_{timestamp}.json"

    filepath = directory / filename
    filepath.write_text(json.dumps(asdict(msg), indent=2))


def _send_webhook(msg: Message, webhook_url: str | None) -> None:
    if webhook_url is None:
        raise ValueError("webhook_url is required for webhook delivery")

    # Future: implement HTTP POST to webhook_url
    raise NotImplementedError("Webhook delivery not yet implemented")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_messages.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add receptionist/messages.py tests/test_messages.py
git commit -m "feat: message storage with file-based delivery"
```

---

### Task 5: Receptionist Agent + Server Entry Point

**Files:**
- Create: `receptionist/agent.py`

This task is the core — it wires everything together. Since the agent requires a running LiveKit server and OpenAI API to test end-to-end, we build it and verify it loads without runtime errors. Full integration testing requires the telephony setup (Task 6).

**Step 1: Write the agent**

```python
# receptionist/agent.py
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
```

**Step 2: Verify the module loads without import errors**

Run: `python -c "from receptionist.agent import Receptionist, server; print('Agent module loaded successfully')"`
Expected: `Agent module loaded successfully`

**Step 3: Commit**

```bash
git add receptionist/agent.py
git commit -m "feat: receptionist agent with function tools and server entry point"
```

---

### Task 6: Documentation and Setup Guide

**Files:**
- Create: `README.md`

**Step 1: Write README**

```markdown
# AI Receptionist

A high-fidelity, open-source AI phone receptionist powered by OpenAI's Realtime API and LiveKit.

Unlike existing AI receptionist products that use cheap cascaded STT-LLM-TTS pipelines, this project uses OpenAI's speech-to-speech model for natural, low-latency conversations that sound like a real person.

## Features

- Natural speech-to-speech conversations via OpenAI Realtime API
- Inbound phone call handling via SIP/Twilio/Telnyx
- FAQ answering from configurable knowledge base
- Call transfers to departments/people
- Message taking with file-based storage
- Multi-business support from a single agent
- Built-in noise cancellation for phone audio

## Prerequisites

- Python 3.11+
- OpenAI API key (with Realtime API access)
- LiveKit server ([self-hosted](https://docs.livekit.io/home/self-hosting/local/) or [LiveKit Cloud](https://cloud.livekit.io))
- SIP trunk provider (Twilio or Telnyx) with a phone number

## Quick Start

1. **Clone and install:**

```bash
git clone https://github.com/yourusername/AIReceptionist.git
cd AIReceptionist
pip install -e .
```

2. **Configure environment:**

```bash
cp .env.example .env
# Edit .env with your keys:
#   LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
```

3. **Configure your business:**

```bash
cp config/businesses/example-dental.yaml config/businesses/my-business.yaml
# Edit with your business name, FAQs, routing numbers, hours
```

4. **Set up telephony:**

Follow the [LiveKit SIP Trunk Setup Guide](https://docs.livekit.io/telephony/start/sip-trunk-setup/) to:
- Create an inbound SIP trunk pointing to your Twilio/Telnyx number
- Create a dispatch rule to route calls to the `receptionist` agent

5. **Run:**

```bash
python -m receptionist.agent dev
```

Call your phone number — you should hear your receptionist greeting.

## Configuration

Each business is defined by a YAML file in `config/businesses/`. See `example-dental.yaml` for a complete example.

Key sections:
- `business` — name, type, timezone
- `voice` — OpenAI voice selection (coral, alloy, ash, ballad, echo, sage, shimmer, verse)
- `greeting` — what the receptionist says when answering
- `personality` — system prompt personality instructions
- `hours` — business hours per day of week
- `routing` — departments/people the receptionist can transfer to
- `faqs` — question/answer pairs the receptionist can answer
- `messages` — how to store messages (file or webhook)

## Multi-Business Setup

One running agent can serve multiple businesses. Each inbound phone number maps to a business config via SIP dispatch rule metadata:

```json
{
  "metadata": "{\"config\": \"my-business\"}"
}
```

This loads `config/businesses/my-business.yaml`.

## Cost

Using OpenAI Realtime API: ~$0.20-0.30/min per call. A dental office with 30 calls/day averaging 2 minutes costs roughly $15/day.

## License

MIT
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup guide and configuration reference"
```

---

### Task 7: Run All Tests and Final Verification

**Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS (6 config + 6 prompts + 3 messages = 15 tests)

**Step 2: Verify the agent module loads cleanly**

Run: `python -c "from receptionist.agent import Receptionist, server; print('OK')"`
Expected: `OK`

**Step 3: Verify example config loads**

Run: `python -c "from receptionist.config import load_config; from pathlib import Path; c = load_config(Path('config/businesses/example-dental.yaml')); print(f'Loaded: {c.business.name}')"`
Expected: `Loaded: Acme Dental`

**Step 4: Final commit if any adjustments were needed**

```bash
git add -A
git status
# Only commit if there are changes
```
