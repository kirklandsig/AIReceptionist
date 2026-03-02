# AIReceptionist -- Project Handoff Document

> **Last updated:** 2026-03-02
> **Purpose:** Transfer complete project context to a new developer or agent with zero knowledge loss.
> **Read time:** ~20 minutes for full comprehension.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Repository Structure](#3-repository-structure)
4. [Module-by-Module Breakdown](#4-module-by-module-breakdown)
5. [Configuration System](#5-configuration-system)
6. [How a Call Flows End-to-End](#6-how-a-call-flows-end-to-end)
7. [Dependencies and Versions](#7-dependencies-and-versions)
8. [Environment and Infrastructure](#8-environment-and-infrastructure)
9. [Testing](#9-testing)
10. [Security Measures](#10-security-measures)
11. [Key Design Decisions and Rationale](#11-key-design-decisions-and-rationale)
12. [Known Issues and Technical Debt](#12-known-issues-and-technical-debt)
13. [Planned Future Work](#13-planned-future-work)
14. [Cost Profile](#14-cost-profile)
15. [Git History](#15-git-history)
16. [Quick Start for New Developers](#16-quick-start-for-new-developers)
17. [Troubleshooting and Gotchas](#17-troubleshooting-and-gotchas)

---

## 1. Project Overview

### What It Is

AIReceptionist is a **voice-based AI phone receptionist** that answers incoming calls for businesses, provides information from a configurable FAQ list, checks business hours, transfers calls to departments, and takes messages when staff are unavailable. It speaks and listens using real-time speech-to-speech AI -- callers talk to it like a human receptionist.

### What It Is Not

- It is not a chatbot or text-based system (though a web widget channel is planned).
- It is not a general-purpose voice assistant -- it is scoped to receptionist duties for a specific business.
- It does not currently record calls or generate transcripts (planned).

### Core Technology Stack

| Layer              | Technology                              |
| ------------------ | --------------------------------------- |
| Voice AI           | OpenAI Realtime API (speech-to-speech)  |
| Audio Transport    | LiveKit Agents SDK                      |
| Telephony          | LiveKit SIP (connects to phone numbers) |
| Configuration      | YAML files + Pydantic v2 validation     |
| Message Storage    | JSON files on disk (webhook planned)    |
| Language           | Python 3.14.2 (see compatibility notes) |

### How It Works in One Paragraph

A phone call arrives via a SIP trunk connected to LiveKit Cloud. LiveKit dispatches the call to this agent process. The agent loads the appropriate business configuration (YAML file), builds a system prompt describing the business, and connects to the OpenAI Realtime API for speech-to-speech conversation. The caller's audio streams to OpenAI, which generates spoken responses in real time. The agent has function tools (lookup FAQ, check hours, transfer call, take message) that the LLM can invoke during conversation. Messages are saved as JSON files. Call transfers use the LiveKit SIP transfer API.

---

## 2. Architecture

### High-Level Diagram

```
                    PSTN / SIP Trunk
                         |
                         v
               +-------------------+
               |  LiveKit Cloud    |
               |  SIP Gateway      |
               +-------------------+
                         |
                         v
               +-------------------+
               |  LiveKit Agents   |  <-- This project
               |  AgentServer      |
               +-------------------+
                    |           |
                    v           v
          +-------------+  +------------------+
          | Business    |  | OpenAI Realtime  |
          | Config YAML |  | API (voice LLM)  |
          +-------------+  +------------------+
                    |
                    v
          +-------------------+
          | Message Storage   |
          | (JSON files)      |
          +-------------------+
```

### Component Responsibilities

- **AgentServer** (`receptionist/agent.py`): Entry point. Accepts incoming LiveKit sessions, loads config, creates the AI agent session.
- **Receptionist** (`receptionist/agent.py`): The agent class. Defines the personality, greeting, and all tool functions the LLM can call.
- **BusinessConfig** (`receptionist/config.py`): Pydantic models that validate and structure all business-specific settings loaded from YAML.
- **build_system_prompt** (`receptionist/prompts.py`): Converts a BusinessConfig into the natural-language system prompt that instructs the LLM how to behave.
- **save_message** (`receptionist/messages.py`): Persists caller messages to disk (or, in the future, to a webhook endpoint).

### Multi-Business Model

One running agent process can serve multiple businesses. The routing works as follows:

1. An incoming call arrives with **job metadata** containing a `"config"` key (e.g., `"example-dental"`).
2. The agent loads `config/businesses/example-dental.yaml`.
3. If no metadata is provided, it falls back to the **first YAML file** found in `config/businesses/`.
4. Each business gets its own system prompt, FAQs, hours, routing, and message directory.

---

## 3. Repository Structure

```
AIReceptionist/
├── README.md                          # Setup guide and configuration reference
├── HANDOFF.md                         # THIS FILE -- full project context
├── pyproject.toml                     # Project metadata, dependencies, tool config
├── .env.example                       # Template for required environment variables
├── .gitignore                         # Standard Python + project-specific ignores
│
├── receptionist/                      # Main application package
│   ├── __init__.py                    # Package marker (empty or minimal)
│   ├── agent.py          (177 lines) # Agent server, session handler, Receptionist class
│   ├── config.py          (101 lines)# Pydantic v2 models, YAML loading, validation
│   ├── prompts.py          (63 lines)# System prompt builder from BusinessConfig
│   └── messages.py         (55 lines)# Message dataclass, file/webhook save logic
│
├── config/
│   └── businesses/
│       └── example-dental.yaml        # Example business configuration file
│
├── tests/
│   ├── test_config.py     (6 tests)  # YAML parsing, validation, edge cases
│   ├── test_prompts.py    (6 tests)  # Prompt content verification
│   └── test_messages.py   (3 tests)  # File creation, multiple messages, directory creation
│
├── docs/
│   └── plans/
│       ├── 2026-03-02-ai-receptionist-design.md
│       └── 2026-03-02-ai-receptionist-implementation.md
│
└── messages/                          # Runtime message storage (gitignored)
```

### What Is Gitignored

The `messages/` directory is gitignored because it contains runtime data (caller messages saved as JSON files). It is created automatically when the first message is saved.

---

## 4. Module-by-Module Breakdown

### 4.1 `receptionist/config.py` (101 lines)

This module defines the entire configuration schema using Pydantic v2 models.

**Models (in dependency order):**

| Model            | Fields                                                        | Notes                                                                                                  |
| ---------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `BusinessInfo`   | `name: str`, `type: str`, `timezone: str`                     | Core identity. `timezone` must be a valid IANA timezone string (e.g., `"America/New_York"`).            |
| `VoiceConfig`    | `voice_id: str` (default `"coral"`), `model: str` (default `"gpt-realtime"`) | OpenAI Realtime voice and model selection. Model can be `"gpt-realtime"` (latest) or `"gpt-4o-realtime-preview"` (original). |
| `DayHours`       | `open: str`, `close: str`                                     | Both validated by regex `^([01]\d|2[0-3]):[0-5]\d$` to enforce HH:MM 24-hour format.                  |
| `WeeklyHours`    | 7 fields: `monday` through `sunday`, each `Optional[DayHours]`| A `field_validator` converts the string `"closed"` to `None` for any day.                              |
| `RoutingEntry`   | `name: str`, `number: str`, `description: str`                | Represents a department the agent can transfer calls to.                                               |
| `FAQEntry`       | `question: str`, `answer: str`                                | Single FAQ pair.                                                                                       |
| `DeliveryMethod` | Enum: `"file"`, `"webhook"`                                   | How messages are delivered.                                                                            |
| `MessagesConfig` | `delivery: DeliveryMethod`, `file_path: Optional[str]`, `webhook_url: Optional[str]` | A `model_validator` enforces that `file_path` is required when `delivery=file` and `webhook_url` is required when `delivery=webhook`. |
| `BusinessConfig` | All of the above as nested fields                             | Top-level model. Has a `from_yaml_string()` classmethod for parsing raw YAML.                          |

**Key functions:**

- `BusinessConfig.from_yaml_string(yaml_str) -> BusinessConfig`: Parses a YAML string using `yaml.safe_load` and validates it through Pydantic.
- `load_config(path: str) -> BusinessConfig`: Reads a YAML file with explicit UTF-8 encoding and returns a validated `BusinessConfig`.

### 4.2 `receptionist/prompts.py` (63 lines)

**Single function:** `build_system_prompt(config: BusinessConfig) -> str`

This function constructs the full natural-language system prompt that the OpenAI Realtime LLM uses to guide its behavior. The prompt includes:

1. **Business identity**: "You are the AI receptionist for {name}, a {type}."
2. **Personality instructions**: Warm, professional, concise.
3. **Weekly hours schedule**: Formatted day-by-day from config, including which days are closed.
4. **After-hours message**: What to say when the business is closed.
5. **Routing departments**: List of departments the agent can transfer to, with descriptions.
6. **Tool usage instructions**: When and how to use each function tool.
7. **FAQ list**: All question-answer pairs, so the LLM can answer them directly.
8. **Behavioral rules**: Stay concise, never fabricate information, confirm before transferring, show empathy.

### 4.3 `receptionist/messages.py` (55 lines)

**Dataclass:** `Message`
- `caller_name: str`
- `callback_number: str`
- `message: str`
- `business_name: str`
- `timestamp: str` -- Automatically set to current UTC time in ISO 8601 format.

**Functions:**

- `save_message(message: Message, config: MessagesConfig)`: Dispatches to `_save_to_file()` or `_send_webhook()` based on `config.delivery`.
- `_save_to_file(message, file_path)`: Creates the directory if needed, writes the message as a JSON file. Filename format uses UTC timestamp with microseconds to avoid collisions (e.g., `2026-03-02T14-30-00-123456.json`).
- `_send_webhook(message, webhook_url)`: **Stubbed** -- raises `NotImplementedError`. This is a known gap.

### 4.4 `receptionist/agent.py` (177 lines)

This is the largest and most important module. It ties everything together.

**Top-level functions:**

- `load_business_config(ctx)`: Determines which business config to load.
  1. Checks `ctx.job.metadata` for a `"config"` key.
  2. Validates the config name matches `^[a-zA-Z0-9_-]+$` (path traversal protection).
  3. Loads `config/businesses/{config_name}.yaml`.
  4. If no metadata, falls back to the first `.yaml` file in `config/businesses/`.

- `_get_caller_identity(ctx)`: Iterates over room participants to find the SIP participant. Returns caller identity or `None` with a warning log.

**Class: `Receptionist(Agent)`**

This is a LiveKit Agents SDK `Agent` subclass. It defines:

| Method                | Purpose                                                                                                   |
| --------------------- | --------------------------------------------------------------------------------------------------------- |
| `__init__(config)`    | Stores `BusinessConfig`, passes `build_system_prompt(config)` as the agent's `instructions`.              |
| `on_enter()`          | Called when the agent joins the session. Generates a spoken greeting using the business name from config.  |
| `lookup_faq(question)`| **Tool function.** Performs case-insensitive substring matching against all FAQs in config. Returns the answer if found, or a neutral "I don't have specific information about that" fallback. |
| `transfer_call(department)` | **Tool function.** Looks up the department in `config.routing`, calls the LiveKit SIP transfer API (`ctx.room.transfer_participant`). Error messages are sanitized -- details are logged server-side, and a generic message is returned to the LLM. |
| `take_message(caller_name, message, callback_number)` | **Tool function.** Creates a `Message` dataclass and saves it via `asyncio.to_thread(save_message, ...)` to avoid blocking the event loop. |
| `get_business_hours()`| **Tool function.** Uses `zoneinfo.ZoneInfo` to get the current time in the business's timezone. Performs lexicographic HH:MM comparison against today's `DayHours` to determine open/closed status. |

**Server setup:**

```python
server = AgentServer()

@server.rtc_session()
async def handle_call(ctx):
    config = await load_business_config(ctx)
    session = AgentSession(
        model=openai.realtime.RealtimeModel()
    )
    receptionist = Receptionist(config)
    # Noise cancellation: BVCTelephony for SIP calls, BVC otherwise
    await session.start(receptionist, room=ctx.room)
```

**Entry point:** `python -m receptionist.agent dev`

The `dev` argument runs the agent in development mode (auto-reload, verbose logging).

---

## 5. Configuration System

### YAML File Format

Business configs live in `config/businesses/`. Here is the structural template based on `example-dental.yaml`:

```yaml
business:
  name: "Example Dental Office"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "coral"          # OpenAI Realtime voice
  # model: "gpt-realtime"   # Optional: model variant (default: latest)

hours:
  monday:
    open: "08:00"
    close: "17:00"
  tuesday:
    open: "08:00"
    close: "17:00"
  wednesday:
    open: "08:00"
    close: "17:00"
  thursday:
    open: "08:00"
    close: "17:00"
  friday:
    open: "08:00"
    close: "15:00"
  saturday: "closed"
  sunday: "closed"

routing:
  - name: "Front Desk"
    number: "+15551234567"
    description: "General inquiries and appointment scheduling"
  - name: "Billing"
    number: "+15551234568"
    description: "Insurance and payment questions"

faq:
  - question: "What insurance do you accept?"
    answer: "We accept most major dental insurance plans including Delta Dental, Cigna, and Aetna."
  - question: "What are your hours?"
    answer: "We are open Monday through Thursday 8 AM to 5 PM, Friday 8 AM to 3 PM."

messages:
  delivery: "file"
  file_path: "messages/example-dental"

personality: "friendly and professional"
after_hours_message: "Our office is currently closed. I can take a message and someone will get back to you on our next business day."
```

### Adding a New Business

1. Create a new YAML file in `config/businesses/` (e.g., `acme-plumbing.yaml`).
2. Follow the structure above, filling in all required fields.
3. For multi-business dispatch, ensure job metadata includes `{"config": "acme-plumbing"}`.

### Validation Rules

- `DayHours.open` and `DayHours.close` must match `HH:MM` 24-hour format.
- `WeeklyHours` fields accept either a `DayHours` object or the string `"closed"` (converted to `None`).
- `MessagesConfig` cross-validates: `file_path` required for file delivery, `webhook_url` required for webhook delivery.
- `BusinessInfo.name` is a required non-empty string.
- YAML is loaded with `yaml.safe_load` (safe against code injection).
- File is read with explicit `encoding="utf-8"`.

---

## 6. How a Call Flows End-to-End

This section traces a complete phone call through the system.

### Step 1: Call Arrival

1. An external caller dials the business phone number.
2. The SIP trunk provider routes the call to the LiveKit Cloud SIP gateway.
3. LiveKit Cloud creates a new room and dispatches the call to the registered agent.

### Step 2: Session Initialization (`handle_call`)

1. `handle_call(ctx)` is triggered by the `@server.rtc_session()` decorator.
2. `load_business_config(ctx)` runs:
   - Checks `ctx.job.metadata` for a `"config"` key.
   - If found and valid (alphanumeric slug), loads the corresponding YAML file.
   - If not found, loads the first YAML in `config/businesses/`.
3. An `AgentSession` is created with `openai.realtime.RealtimeModel()`.
4. A `Receptionist` instance is created with the loaded config.
5. Noise cancellation is applied (BVCTelephony for SIP, BVC otherwise).
6. The session starts.

### Step 3: Greeting (`on_enter`)

1. The `Receptionist.on_enter()` method fires.
2. It generates a greeting like: "Thank you for calling Example Dental Office. How can I help you today?"
3. This is spoken to the caller via the OpenAI Realtime API.

### Step 4: Conversation Loop

1. The caller speaks. Audio streams through LiveKit to OpenAI Realtime.
2. OpenAI processes the speech and generates a response.
3. If the LLM determines it needs to use a tool, it invokes one:
   - **`lookup_faq(question)`**: Searches FAQs, returns answer or fallback.
   - **`get_business_hours()`**: Checks if the business is currently open.
   - **`transfer_call(department)`**: Transfers via SIP to the department's number.
   - **`take_message(caller_name, message, callback_number)`**: Saves a message to disk.
4. The LLM incorporates tool results into its spoken response.

### Step 5: Call End

1. The caller hangs up, or the call is transferred.
2. The LiveKit session ends.
3. Any messages taken are already persisted as JSON files in the `messages/` directory.

---

## 7. Dependencies and Versions

### Production Dependencies

| Package                               | Requirement     | Installed Version | Purpose                                    |
| ------------------------------------- | --------------- | ----------------- | ------------------------------------------ |
| `livekit-agents`                      | `>=1.0.0`       | 1.4.3             | Agent SDK for real-time voice sessions      |
| `livekit-plugins-openai`              | `>=1.0.0`       | 1.4.3             | OpenAI Realtime API integration for LiveKit |
| `livekit-plugins-noise-cancellation`  | `>=0.2.3`       | 0.2.5             | Background noise cancellation (BVC/Krisp)   |
| `pydantic`                            | `>=2.0`         | (latest v2)       | Data validation for config models           |
| `pyyaml`                              | `>=6.0`         | (latest)          | YAML config file parsing                    |
| `python-dotenv`                       | `>=1.0`         | (latest)          | `.env` file loading for secrets             |

### Development Dependencies

| Package          | Requirement  | Purpose                          |
| ---------------- | ------------ | -------------------------------- |
| `pytest`         | `>=8.0`      | Test runner                      |
| `pytest-asyncio` | `>=0.24`     | Async test support               |

### Important Compatibility Note

The `livekit-agents` package officially restricts Python to `<3.14`. The development environment runs **Python 3.14.2**, which means it was force-installed or the constraint was bypassed. This may cause **runtime compatibility issues**. For production deployment, use **Python 3.11 or 3.12** for maximum stability and compatibility.

---

## 8. Environment and Infrastructure

### LiveKit Cloud

- **Project URL:** `wss://aireceptionist-402e6ask.livekit.cloud`
- **Agent registration:** The agent registers with `agent_name=""` (empty string) for auto-dispatch.
- **Production note:** For multi-business routing with dispatch rules, restore `agent_name="receptionist"` and configure LiveKit dispatch rules accordingly.

### Required Environment Variables

These should be set in a `.env` file (see `.env.example` for template):

| Variable              | Purpose                                    |
| --------------------- | ------------------------------------------ |
| `LIVEKIT_URL`         | LiveKit Cloud WebSocket URL                |
| `LIVEKIT_API_KEY`     | LiveKit API key for authentication         |
| `LIVEKIT_API_SECRET`  | LiveKit API secret for authentication      |
| `OPENAI_API_KEY`      | OpenAI API key for Realtime API access     |

### Development Environment

- **OS:** Windows 11 Pro 10.0.26200
- **Python:** 3.14.2 (see compatibility note above)
- **Shell:** bash (Git Bash or similar on Windows)

### Running the Agent

```bash
# Development mode (auto-reload, verbose logging)
python -m receptionist.agent dev

# Production mode
python -m receptionist.agent start
```

### Running Tests

```bash
pytest                    # Run all 15 tests
pytest tests/test_config.py   # Run only config tests
pytest -v                 # Verbose output
```

---

## 9. Testing

### Test Coverage Summary

| Test File            | Tests | What It Covers                                                              |
| -------------------- | ----- | --------------------------------------------------------------------------- |
| `test_config.py`     | 6     | YAML parsing, file loading, closed/open day hours, missing name validation, invalid delivery method validation, cross-field delivery validation |
| `test_prompts.py`    | 6     | Business name in prompt, personality text, FAQ content, routing info, hours schedule, after-hours message |
| `test_messages.py`   | 3     | Single file creation and content, multiple file uniqueness, auto-directory creation |

**Total: 15 tests, all passing.**

### What Is NOT Tested

- The `agent.py` module (would require mocking LiveKit SDK and OpenAI Realtime API).
- Webhook delivery (stubbed, not implemented).
- Integration/end-to-end call flow.
- `get_business_hours()` timezone logic.
- `transfer_call()` SIP transfer logic.
- Error handling paths in agent tools.

### Testing Approach

Tests use plain `pytest` with fixtures. Config tests construct YAML strings and validate parsing. Prompt tests check that specific content appears in the generated prompt string. Message tests use temporary directories to verify file I/O.

---

## 10. Security Measures

The following security hardening was applied in commit `1201e07`:

### Path Traversal Protection

The `load_business_config()` function validates the `config` name from job metadata against `^[a-zA-Z0-9_-]+$` before constructing a file path. This prevents an attacker from passing `../../etc/passwd` as a config name.

```
config_name from metadata -> regex validation -> config/businesses/{config_name}.yaml
```

### Error Sanitization

When tool functions (e.g., `transfer_call`) encounter exceptions, the full error details are logged server-side using Python logging. The message returned to the LLM is generic (e.g., "I'm sorry, I'm unable to transfer your call right now"). This prevents leaking internal paths, stack traces, or infrastructure details to callers.

### Non-Blocking I/O

`save_message()` is called via `asyncio.to_thread()` to prevent file I/O from blocking the event loop (which would cause audio glitches or dropped frames in the voice session).

### Input Validation

- `DayHours` enforces HH:MM 24-hour format via regex.
- `MessagesConfig` uses a Pydantic `model_validator` for cross-field validation.
- YAML files are read with `yaml.safe_load` (prevents arbitrary code execution).
- Files are opened with explicit `encoding="utf-8"`.

---

## 11. Key Design Decisions and Rationale

### Decision 1: OpenAI Realtime API (Speech-to-Speech)

**Choice:** Use OpenAI's Realtime API for end-to-end speech-to-speech processing.
**Alternative considered:** Cascaded pipeline (Deepgram STT -> Claude/GPT-4o -> ElevenLabs TTS).
**Rationale:** The Realtime API provides the lowest latency and highest fidelity for voice conversations. It handles interruptions, backchanneling, and natural turn-taking natively. The cascaded approach is planned as a future cost-conscious alternative.

### Decision 2: LiveKit Agents SDK

**Choice:** LiveKit Agents SDK for real-time audio transport.
**Rationale:** LiveKit is the same infrastructure OpenAI uses for ChatGPT Advanced Voice Mode. It provides production-grade WebRTC, SIP integration, and an agent framework with built-in session management.

### Decision 3: YAML Configuration Over Database

**Choice:** Business configs are YAML files on disk.
**Alternative considered:** Database (PostgreSQL, SQLite).
**Rationale:** Zero additional infrastructure. Configs are git-versionable, human-readable, and trivially editable. For the expected scale (tens of businesses, not thousands), YAML is sufficient. A database can be added later if needed.

### Decision 4: FAQs in System Prompt (Not RAG)

**Choice:** All FAQ entries are embedded directly in the LLM system prompt.
**Alternative considered:** RAG with vector database.
**Rationale:** At 10-30 FAQs (typical for a small business), the LLM can reason over them directly in context. RAG adds complexity (embedding model, vector store, retrieval logic) with no benefit at this scale. If FAQ counts grow beyond ~50-100, revisit this decision.

### Decision 5: File-Based Message Storage

**Choice:** Messages saved as individual JSON files on disk.
**Alternative considered:** Database, message queue.
**Rationale:** Simplest possible approach for MVP. No additional dependencies. Easy to inspect and debug. Webhook delivery is planned for production integrations.

### Decision 6: Multi-Business via Job Metadata

**Choice:** A single agent process serves multiple businesses, selected by job metadata.
**Rationale:** Efficient resource usage. No need to run N agent processes for N businesses. LiveKit's dispatch system routes calls to the right config.

---

## 12. Known Issues and Technical Debt

### Critical / Should Fix Before Production

| #  | Issue                                        | Impact                                      | Suggested Fix                                                    |
| -- | -------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------- |
| 1  | Webhook delivery is stubbed (`NotImplementedError`) | Cannot integrate with external systems      | Implement `_send_webhook()` using `httpx` or `aiohttp`          |
| 2  | Python 3.14 compatibility uncertain          | Potential runtime crashes in production      | Pin to Python 3.11 or 3.12 in production Dockerfile/deployment   |
| 3  | `agent_name=""` for dev testing              | No named dispatch in production              | Restore `agent_name="receptionist"` and configure dispatch rules |

### Medium Priority

| #  | Issue                                        | Impact                                      | Suggested Fix                                                    |
| -- | -------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------- |
| 4  | `lookup_faq` uses simple substring matching  | May return wrong FAQ for ambiguous queries   | Use TF-IDF or embedding similarity; sufficient for <30 FAQs now  |
| 5  | No call recording or transcript capture      | No audit trail or review capability          | Use LiveKit Egress API for recordings; OpenAI Realtime text output for transcripts |
| 6  | No email notification for messages           | Staff must manually check message files      | Add SMTP/SendGrid integration triggered after `save_message()`   |

### Low Priority / Nice to Have

| #  | Issue                                        | Impact                                      | Suggested Fix                                                    |
| -- | -------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------- |
| 7  | No admin dashboard or web UI                 | Config changes require file editing          | Build a web UI (FastAPI + React) for config management           |
| 8  | No integration tests for agent.py            | Core module untested                         | Mock LiveKit and OpenAI SDKs; test tool invocation paths         |
| 9  | No structured logging                        | Harder to debug in production                | Add structured JSON logging with correlation IDs per call        |

---

## 13. Planned Future Work

These items come from the design document at `docs/plans/2026-03-02-ai-receptionist-design.md`:

### Near-Term

1. **Webhook message delivery**: Implement `_send_webhook()` to POST messages to external endpoints (CRM, Slack, etc.).
2. **Call recordings**: Use the LiveKit Egress API to record calls for quality assurance and compliance.
3. **Call transcripts**: Capture the text output from the OpenAI Realtime API to generate searchable transcripts.
4. **Email notifications**: Send email alerts when a message is taken (SMTP or SendGrid).

### Medium-Term

5. **Cascaded pipeline mode**: Offer an alternative pipeline using Deepgram STT + Claude/GPT-4o + ElevenLabs TTS. This would be cheaper (~$0.05-0.10/min vs. ~$0.20-0.30/min) at the cost of slightly higher latency.
6. **Web widget channel**: Allow businesses to embed a voice widget on their website. Uses browser WebRTC directly (no telephony needed), lowering per-call costs.

### Long-Term

7. **Admin dashboard**: Web UI for managing business configs, viewing messages, listening to recordings, and viewing analytics.
8. **Analytics**: Track call volume, common questions, transfer rates, message rates, peak hours.
9. **Multi-language support**: Leverage OpenAI Realtime's multilingual capabilities.

---

## 14. Cost Profile

### Per-Call Cost Breakdown

| Cost Component            | Rate                      |
| ------------------------- | ------------------------- |
| OpenAI Realtime API       | ~$0.20-0.30 per minute    |
| SIP trunk (telephony)     | ~$0.01-0.02 per minute    |
| LiveKit Cloud             | Included in agent hosting |

### Example Monthly Cost

| Metric                     | Value            |
| -------------------------- | ---------------- |
| Calls per day              | 30               |
| Average call duration      | 2 minutes        |
| Daily cost                 | ~$15             |
| Monthly cost (30 days)     | ~$450            |

### Cost Reduction Strategies

- **Cascaded pipeline** (Deepgram + Claude + ElevenLabs): Could reduce AI cost to ~$0.05-0.10/min.
- **Web widget** (no telephony): Eliminates SIP trunk costs entirely.
- **Shorter calls**: Optimize prompts and FAQ coverage to resolve calls faster.

---

## 15. Git History

The repository has 9 commits on the `main` branch, listed newest to oldest:

```
713c212 docs: add README with setup guide and configuration reference
1201e07 fix: harden agent against path traversal, error leaks, and blocking I/O
865cb62 feat: receptionist agent with function tools and server entry point
9673f30 feat: message storage with file-based delivery
953dfb8 feat: system prompt builder from business config
6acbdfc fix: add config validation for delivery fields, time format, and UTF-8 encoding
7d70f91 feat: business config Pydantic models with YAML loading and validation
89578d6 docs: add design doc and implementation plan
bddec57 chore: initial project scaffolding with dependencies
```

### Development Progression

1. **Scaffolding** (`bddec57`): Initial project structure, `pyproject.toml`, dependencies.
2. **Design** (`89578d6`): Design document and implementation plan written before coding.
3. **Config** (`7d70f91`, `6acbdfc`): Pydantic models for business config, then hardened with validation.
4. **Prompts** (`953dfb8`): System prompt builder from business config.
5. **Messages** (`9673f30`): File-based message storage.
6. **Agent** (`865cb62`, `1201e07`): Core agent with tools, then hardened for security.
7. **Docs** (`713c212`): README with setup guide.

---

## 16. Quick Start for New Developers

### Prerequisites

- Python 3.11 or 3.12 (recommended; 3.14 works but is not officially supported by livekit-agents)
- A LiveKit Cloud account (or self-hosted LiveKit server)
- An OpenAI API key with Realtime API access

### Setup Steps

```bash
# 1. Clone the repository
cd C:\Users\MDASR\Desktop\Projects\AIReceptionist

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# or: .venv\Scripts\activate    # Windows CMD
# or: source .venv/bin/activate # Linux/macOS

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Set up environment variables
cp .env.example .env
# Edit .env and fill in:
#   LIVEKIT_URL=wss://aireceptionist-402e6ask.livekit.cloud
#   LIVEKIT_API_KEY=<your key>
#   LIVEKIT_API_SECRET=<your secret>
#   OPENAI_API_KEY=<your key>

# 5. Run the tests to verify everything works
pytest

# 6. Start the agent in development mode
python -m receptionist.agent dev
```

### Testing with LiveKit Playground

1. Go to the LiveKit Cloud dashboard.
2. Open the "Playground" or "Agent Playground" tool.
3. Connect to the same LiveKit project.
4. The agent should accept the session (since `agent_name=""` accepts all dispatches).
5. Speak to test the conversation flow.

### Testing with a Real Phone Call

1. Configure a SIP trunk in LiveKit Cloud pointing to your phone number provider.
2. Create a dispatch rule routing incoming SIP calls to the agent.
3. Call the phone number.

---

## 17. Troubleshooting and Gotchas

### "Browser not supported" or agent not picking up calls

- Ensure `agent_name=""` in the code (for dev) or that dispatch rules match the agent name (for production).
- Check that the `.env` file has correct `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`.
- Verify the agent is running and connected: the console should show a registration message.

### "No config found" or config loading errors

- Ensure at least one `.yaml` file exists in `config/businesses/`.
- If using job metadata routing, verify the metadata `"config"` value matches the YAML filename (without `.yaml` extension).
- Check that the YAML file is valid (use a YAML linter).

### Audio issues (silence, glitches, dropped audio)

- Check your `OPENAI_API_KEY` -- the Realtime API requires specific access.
- Noise cancellation requires the `livekit-plugins-noise-cancellation` package. If it fails to load, the agent may still work but without noise cancellation.
- Ensure the event loop is not being blocked (the `asyncio.to_thread` wrapper on `save_message` is specifically for this).

### Python 3.14 issues

- If you encounter import errors or C extension failures, switch to Python 3.11 or 3.12.
- `livekit-agents` officially requires Python `<3.14`. Force-installing on 3.14 may cause subtle issues.

### Tests failing

- Run `pip install -e ".[dev]"` to ensure dev dependencies are installed.
- Tests do not require LiveKit or OpenAI credentials -- they test config, prompts, and messages only.
- If `test_messages.py` fails, check filesystem permissions on the temp directory.

### Message files not appearing

- Check the `messages` config in the YAML file -- `file_path` must be set when `delivery` is `"file"`.
- The directory is created automatically on first write, but the process needs write permissions.
- Look in the path specified by `file_path` in the business YAML config (e.g., `messages/example-dental/`).

---

## End of Handoff Document

This document contains everything needed to understand, maintain, and extend the AIReceptionist project. For architectural rationale and long-term vision, also consult:

- `docs/plans/2026-03-02-ai-receptionist-design.md`
- `docs/plans/2026-03-02-ai-receptionist-implementation.md`

For setup and configuration reference:

- `README.md`
- `.env.example`
- `config/businesses/example-dental.yaml`
