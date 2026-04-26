# Changelog

All notable changes to the AI Receptionist project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Google Calendar integration** (issue #3): two new function tools
  (`check_availability`, `book_appointment`) let the agent book appointments
  on a per-business Google Calendar during live calls. Supports both
  service-account auth (Google Workspace) and OAuth 2.0 (any Google account)
  via a setup CLI. See `documentation/google-calendar-setup.md`.
- **`on_booking` email trigger**: fires a booking-specific email to staff
  when an appointment is booked. Reuses the existing EmailChannel dispatcher
  + retry infrastructure.
- **`receptionist/booking/` subpackage** with auth, client, availability
  (pure), booking (with race detection), and setup CLI modules.
- **`SlotProposal` + `BookingResult` dataclasses** for calendar types.
- **Setup CLI** at `python -m receptionist.booking setup <business-slug>`.
- **Optional caller-email calendar invite**: `book_appointment` accepts a
  `caller_email` parameter. When provided, the caller is added as an
  OPTIONAL Google attendee and Google sends them the standard
  invitation (with `.ics`, accept/decline, "Add to my calendar").
  Optional attendees do not impact the organizer's free/busy view if
  they decline.
- **`RECEPTIONIST_CONFIG` env var** lets `python -m receptionist.agent dev`
  pick a non-default business config without job metadata.
- **Relative-date resolver** in `check_availability`: "today",
  "tomorrow", "tonight", "next Monday", "this Friday" all resolve to
  absolute dates before parsing. Bare weekday names and absolute dates
  fall through unchanged.
- **Multi-channel message delivery**: `messages.channels` list supports `file`, `email`, and `webhook` types enabled simultaneously per business (design spec §2)
- **Call recording** via LiveKit Egress, stored locally or to S3/R2/B2/MinIO (spec §3)
- **Call transcripts** in JSON (source of truth) + Markdown, with per-call metadata (caller, outcome, duration, tools invoked, languages detected)
- **Email delivery** via pluggable senders — SMTP (`aiosmtplib`) or Resend (`httpx`), behind a shared `EmailSender` protocol
- **Email triggers** — `on_message` (fires when `take_message` succeeds) and `on_call_end` (fires on every call end), toggleable per business
- **Consent preamble** spoken before the greeting when recording is enabled (configurable text, default-on when recording is on)
- **Multi-language auto-detection** — per-business `languages.primary` + `languages.allowed` whitelist; `gpt-realtime-1.5` handles detection, polite redirect when caller speaks an unsupported language
- **Retention sweeper** — `python -m receptionist.retention sweep [--dry-run] [--business <name>]`; configurable TTL per artifact type (`recordings_days`, `transcripts_days`, `messages_days`; 0 = keep forever); skips `.failures/` directories
- **Failures CLI** — `python -m receptionist.messaging list-failures` surfaces records in each business's `.failures/` directory
- **Env-var interpolation** in YAML (`${VAR_NAME}` expanded against `os.environ` at load time; missing vars raise `ConfigError` at startup)
- **Configurable voice** — `voice.voice_id` default changed to `marin` (trained for `gpt-realtime-1.5`)
- New package structure: `receptionist/messaging/`, `receptionist/email/`, `receptionist/recording/`, `receptionist/transcript/`, `receptionist/retention/`, `receptionist/lifecycle.py`
- ~50 new unit tests across the new subpackages; 1 integration test (`tests/integration/test_call_flow.py`) for end-to-end message + call-end flows
- New gitignored artifact directories: `transcripts/`, `recordings/`
- `.python-version` pinned to `3.12`

### Changed
- **BREAKING: `CallMetadata.outcome: str | None` → `CallMetadata.outcomes: set[str]`**
  to support calls with multiple outcomes (e.g. transferred AND book an
  appointment). Email subjects and transcript headers render multi-outcome
  cases as "Transferred + Appointment booked". No external consumers of the
  old shape were known at the time of the change.
- **Valid outcomes** now include `"appointment_booked"` alongside
  `hung_up`, `message_taken`, `transferred`.
- New production deps: `google-api-python-client>=2.140`, `google-auth>=2.32`,
  `google-auth-oauthlib>=1.2`, `python-dateutil>=2.9` (all Apache 2.0).
- System prompt (`prompts.py`) gains a CALENDAR section when
  `config.calendar.enabled: true` — describes the two tools, the
  verbal-confirmation convention, and the no-fabrication hard rule.
- `Receptionist.__init__` gains `_offered_slots: set[str]` session cache +
  lazily-constructed `_calendar_client`.
- New artifact directory: `secrets/<business>/` (gitignored) for calendar
  credentials — service account JSON keys and OAuth token files.
- **Default voice model**: `gpt-realtime` → `gpt-realtime-1.5` (+7% instruction following, +10% alphanumeric transcription, +5% Big Bench Audio reasoning — same pricing)
- **`Receptionist`** now takes a `CallLifecycle` parameter; tool methods update per-call metadata (FAQs answered, transfer target, message-taken flag)
- **`take_message`** routes through the new `Dispatcher` — file channel completes synchronously (durable confirmation), email/webhook run as background tasks with retry/backoff
- **Legacy `messages.delivery: "file"` config form** is still accepted via a Pydantic `model_validator` that auto-converts it to the new `channels: [...]` list (deprecation warning logged)
- **`receptionist/messages.py`** removed; its contents moved to `receptionist/messaging/{models,channels/file}.py`
- **Dependency floor bumps**: `livekit-agents>=1.5.0`, `livekit-plugins-openai>=1.5.0`
- New production dependencies: `aiosmtplib>=3.0`, `resend>=2.0`, `httpx>=0.27`, `aioboto3>=13.0`, `aiofiles>=23.0`
- New dev dependencies: `pytest-mock>=3.12`, `respx>=0.21`, `moto>=5.0`
- **CALENDAR prompt block**: agent now reads back the callback number
  digit-by-digit and (when the caller volunteers an email) reads it
  back letter-by-letter, awaiting an explicit "yes" before booking.
  Prevents mishearings from being committed to a real calendar event.
- **`book_appointment` signature**: gains optional `caller_email: str | None`
  parameter (default `None` keeps the prior no-attendee behavior).

### Fixed
- **SIP transfer URI configurable** (issue #6, reported by @trinicomcom):
  the `transfer_call` tool used to hardcode `tel:{number}` for the
  LiveKit SIP transfer URI. That works for Twilio/Telnyx/most BYOC, but
  Asterisk classic `sip.conf` (chan_sip) rejects tel-URIs and the
  transfer would fail. Added a `sip.transfer_uri_template` field
  (default `"tel:{number}"`, validators require `{number}` placeholder)
  so Asterisk users can set `"sip:{number}"` or
  `"sip:{number}@your-pbx"`. Default behavior is unchanged for everyone
  on Twilio/Telnyx/BYOC.
- **OAuth scope**: added `https://www.googleapis.com/auth/calendar.freebusy`
  alongside `calendar.events`. The events scope alone is insufficient for
  `freeBusy.query` (Google treats freeBusy as a calendar-level operation,
  not an events-level one). Existing OAuth tokens issued for the
  single-scope set must be re-minted via `python -m receptionist.booking
  setup <business>`.
- **Setup CLI Unicode crash**: replaced `✓` markers with `[OK]`. Default
  Windows `cp1252` console can't render U+2713 — would crash AFTER a
  successful token write/chmod, masking the prior success.
- **Relative-date parsing**: `dateutil.parser` doesn't understand "today"
  / "tomorrow" / "next Monday" — `check_availability` would return
  "couldn't parse that date" for caller phrasings the prompt advertised
  as supported. Added `_resolve_relative_date()` that normalizes those
  phrases before parsing.

### Security
- OAuth token files enforced to `0600` permissions on Unix at agent startup
  (no-op on Windows).
- Calendar events tagged `[via AI receptionist / UNVERIFIED]` permanently
  so staff see the caller's identity was not verified.
- `sendUpdates="none"` on `events.insert` when no caller email is
  provided — no side-channel notifications from Google. When the
  caller volunteers an email, `sendUpdates="all"` and the caller is
  added as an OPTIONAL attendee so they get the standard invite.
- Calendar credentials are per-business, isolated in `secrets/<business>/`.
- Env-var interpolation avoids storing secrets in YAML files
- Call ID is sanitized (`[^a-zA-Z0-9_-]` stripped) before use in artifact paths
- `.failures/` records retain delivery context (no credential leakage — sender auth details stay in logs only)

---

## [0.1.0] - 2026-03-02

Initial release of the AI Receptionist.

### Added

#### Core Agent
- `receptionist/agent.py` — LiveKit Agents SDK integration with `AgentServer` and `Receptionist` class
- `Receptionist.on_enter()` — automatic greeting on call pickup
- `Receptionist.lookup_faq()` — function tool for FAQ matching (case-insensitive substring)
- `Receptionist.transfer_call()` — function tool for SIP call transfer via LiveKit API
- `Receptionist.take_message()` — function tool for recording caller messages
- `Receptionist.get_business_hours()` — function tool for timezone-aware hours checking
- Multi-business support via job metadata routing (`load_business_config`)
- Noise cancellation (BVCTelephony for SIP, BVC for WebRTC)

#### Configuration
- `receptionist/config.py` — Pydantic v2 models for business configuration
- YAML-based business configuration (`config/businesses/example-dental.yaml`)
- Models: `BusinessInfo`, `VoiceConfig`, `DayHours`, `WeeklyHours`, `RoutingEntry`, `FAQEntry`, `DeliveryMethod`, `MessagesConfig`, `BusinessConfig`
- Time format validation (HH:MM 24-hour), cross-field validation, safe YAML loading

#### Prompt System
- `receptionist/prompts.py` — builds natural-language system prompts from business config
- Includes business identity, personality, hours, routing, FAQs, and behavioral rules

#### Message Storage
- `receptionist/messages.py` — `Message` dataclass and file-based persistence
- JSON file output with microsecond-precision timestamps
- Webhook delivery stubbed (not yet implemented)

#### Security
- Path traversal protection on config name resolution (`^[a-zA-Z0-9_-]+$`)
- Error sanitization in tool functions (generic messages to LLM, full details in server logs)
- Non-blocking I/O via `asyncio.to_thread()` for file operations
- Safe YAML loading (`yaml.safe_load`), explicit UTF-8 encoding

#### Testing
- `tests/test_config.py` — 6 tests for YAML parsing, validation, and edge cases
- `tests/test_prompts.py` — 6 tests for prompt content verification
- `tests/test_messages.py` — 3 tests for file I/O and directory creation
- Total: 15 tests, all passing

#### Documentation
- `README.md` — setup guide and configuration reference
- `HANDOFF.md` — comprehensive project handoff document
- `documentation/index.md` — documentation landing page
- `documentation/architecture.md` — system architecture and design decisions
- `docs/plans/` — design document and implementation plan
