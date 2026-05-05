# Changelog

All notable changes to the AI Receptionist project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **`end_call` function tool** (issue #10): the agent can now end the call
  itself when the caller has clearly finished — e.g. "goodbye", "thanks,
  bye", "that's all I needed". The tool says a brief goodbye, then disconnects
  the SIP caller via `remove_participant` (preferred — sends a SIP BYE) and
  falls back to `delete_room` if removal fails. The system prompt teaches
  the LLM when to call it and, equally important, when NOT to call it.
- **`agent_ended` outcome and `agent_end_reason` field** on `CallMetadata`
  (issues #10/#11). Distinguishes agent-initiated hangups from caller
  hangups in call summaries, transcripts, and dashboards. The reason is a
  short label drawn from a closed vocabulary (`caller_goodbye`,
  `silence_timeout`, `unproductive_turns_exhausted`); call-end emails and
  Markdown transcript headers render it next to the outcome row.

### Fixed
- **CallerID resolution for non-SIP-kind participants** (issue #9):
  the SIP participant resolver no longer requires
  `participant.kind == PARTICIPANT_KIND_SIP`. Some BYOC/Asterisk SIP trunks
  publish the SIP participant with a different kind value but with an
  identity matching `sip_<digits>` and/or `sip.*` attributes. The kind gate
  was the silent-`Unknown` trap reported by @trinicomcom: even though the
  identity was clearly `sip_17135550038`, the helper short-circuited before
  the identity-regex fallback ran. The kind comparison is preserved as a
  preference in `_get_caller_identity` (SIP-kind participants still win) but
  is no longer a precondition.
- **Late SIP attribute updates** are now captured: `handle_call` subscribes
  to `participant_attributes_changed` and re-runs CallerID capture when any
  `sip.*` attribute arrives after the participant has already joined the
  room (Telnyx INVITE → PRACK delay, Asterisk diversion-header late update).

### Changed
- **Always-on `agent.callerid` INFO logs** record the snapshot at
  `handle_call` start, the participant identity/kind/attribute keys for
  every capture attempt, and a clear positive/negative result line. Operators
  no longer need to flip a debug flag to diagnose CallerID issues.

### Added
- **Per-business OpenAI Realtime auth selection**: `voice.auth` can now
  choose how each business authenticates to the Realtime API. Omitting
  `voice.auth` preserves the existing `OPENAI_API_KEY` behavior; explicit
  options include `api_key` (custom env var), `oauth_codex` (Codex CLI /
  ChatGPT-login OAuth token at `~/.codex/auth.json`), and `oauth_static`
  (raw bearer token, inline or env-sourced). `oauth_codex` now refreshes
  expired access tokens with `tokens.refresh_token` and writes rotated tokens
  back to the same auth file.
- **OpenAI OAuth setup CLI**: `python -m receptionist.voice setup <business>`
  runs Codex login, copies the Codex auth file to
  `secrets/<business>/openai_auth.json`, validates it, and updates the
  business YAML `voice.auth` block.
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
- `Receptionist.__init__` gains a bounded `_offered_slot_batches:
  deque[frozenset[str]]` (maxlen=3) session cache, a cached
  `_dispatcher` for take_message, and a `_routing_by_name` dict for
  case-insensitive O(1) department lookup. `_calendar_client` is still
  lazily constructed on first calendar tool call.
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
- **BYOC/Asterisk CallerID fallback** (issue #9, reported by @trinicomcom):
  if LiveKit does not populate `sip.phoneNumber`, CallerID resolution now
  falls back to `sip.fromUser`, `sip.from`, and SIP participant identities
  like `sip_17135550038`. The agent also re-scans existing room participants
  after registering the `participant_connected` handler to close the small
  connect-window race.
- **CallerID capture race** (issue #9, reported by @trinicomcom): call-end
  emails and transcripts could show `Caller: Unknown` because
  `sip.phoneNumber` was read before the SIP participant had joined the
  LiveKit room. The agent now also captures the caller phone when
  LiveKit emits `participant_connected` for the SIP participant.
- **Transfer target visibility** (issue #9, reported by @trinicomcom):
  call-end email subjects, HTML email bodies, and Markdown transcript
  headers now show the matched transfer destination (for example,
  `Transferred to Agent Smith`). The value was already stored in JSON
  transcript metadata and the plain-text email body, but the HTML email
  body omitted it, so most mail clients hid it.
- **Call-end HTML email parity**: appointment details, FAQs answered,
  languages detected, transcript path, and recording-failed status now
  render in the HTML body to match the plain-text call-end email body.
- **Friendlier YAML error for the "uncommented with leading space" trap**
  (issue #8, reported by @trinicomcom): leaving a single space before
  a top-level section (e.g. ` sip:` instead of `sip:`) used to produce
  the cryptic `expected <block end>, but found '<block mapping start>'`
  parser error pointing at the wrong line. `BusinessConfig.from_yaml_string`
  now wraps `yaml.YAMLError` in a new `ConfigError` and detects this
  exact pattern, producing a message that names the offending section
  and explains how to fix it. The original yaml error is still chained
  via `raise ... from e` for debugging. Example YAML config and the
  troubleshooting doc updated with explicit "remove BOTH the # AND the
  space" guidance above each commented section.
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
- **Setup CLI now validates `business_slug`** with the same
  `^[a-zA-Z0-9_-]+$` regex used elsewhere. `python -m receptionist.booking
  setup ../../etc/passwd` previously would have resolved into a path
  traversal attempt; now rejected by argparse with a clear error.
- **`take_message` and `book_appointment` cap caller-supplied free-text**
  fields (caller_name 200, callback_number 50, message 4000, notes
  1000, caller_email 254). Truncation logged at INFO; staff can pull
  the original from logs if needed. Prevents storage bloat and
  Google's 8KB calendar event description ceiling from being hit.
- **Webhook URL safety**: `WebhookChannel.url` now hard-rejects schemes
  other than `http`/`https` at config load (no more `file://`,
  `data:`, etc.) and warns when the host is loopback / private /
  link-local (legitimate in dev but a common SSRF foot-gun in prod —
  e.g. AWS metadata endpoint at `169.254.169.254`).
- **Production code asserts replaced with explicit raises**:
  `recording/storage.py`, `recording/egress.py`, `messaging/retry.py`
  used `assert x is not None` patterns that are stripped under
  `python -O`. Now raise `ValueError`/`RuntimeError` so optimized-mode
  failures are debuggable.
- **`CallMetadata.mark_finalized()`** now logs at WARNING when
  `start_ts`/`end_ts` parsing fails instead of silently leaving
  `duration_seconds` at `None`.
- **Windows OAuth token ACL**: `_check_token_permissions` previously
  returned silently on Windows. Now logs a one-shot WARNING per token
  path nudging operators to put the file in a user-only directory
  (stdlib has no NTFS-ACL inspection without `pywin32`, so a hard
  guard would require an extra dep).

### Performance
- **`Dispatcher` and `EmailChannel` instances cached per call** instead
  of reconstructed per `take_message` / per email trigger. Saves
  filesystem walk + dict iteration on every invocation.
- **`_offered_slots` is now bounded** — replaced unbounded `set[str]`
  with `deque[frozenset[str]]` of `maxlen=3`. Prevents the cache from
  growing without limit on long, chatty calls. Behavior unchanged at
  the LLM level (only the most recent batch ever matters in practice).
- **Routing lookup is now O(1)** via dict-by-lowercased-name built at
  `Receptionist.__init__`. FAQ matching deliberately stays linear (its
  bidirectional substring match doesn't fit a single dict).
- **Lightweight imports hoisted** out of `check_availability` and
  `book_appointment`. The `googleapiclient`-pulling chain stays
  deferred so calendar-disabled businesses still skip the ~50MB import
  cost.

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
