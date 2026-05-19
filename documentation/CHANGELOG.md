# Changelog

All notable changes to the AI Receptionist project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Security
- Hardened webhook configuration and notification transports: webhook URLs
  now reject localhost, loopback, private, and link-local hosts; webhook and
  Resend errors avoid logging sensitive URL/body details; and the pre-commit
  secret scan now checks generic assignments and YAML raw-secret fields.
- Tightened config validation so invalid timezones, unknown config keys,
  unsafe env-var placeholders, and excessive calendar booking windows fail at
  config load instead of during a live call.

### Fixed
- Made call finalization more resilient: recording/transcript failures no
  longer prevent deferred message emails from firing, deferred message queues
  are cleared after dispatch, and background tasks are retained until they
  complete.
- Added regression coverage for SIP transfer behavior, lifecycle failure
  paths, webhook retry semantics, Resend error hygiene, config validation,
  and email subject normalization.

### Changed
- Updated public documentation and examples to reflect the current
  `messages.channels` schema, implemented webhook delivery, stricter webhook
  URL validation, current test layout, and optional voice idle/auth blocks.

### Fixed
- **Agent-initiated `end_call` no longer drops the call-end and deferred
  message emails.** When the **caller** hung up first, `on_call_ended`
  ran fine; when the **agent** ended the call (via the `end_call` tool —
  caller goodbye, silence timeout, max duration, unproductive turns),
  the LiveKit job process started tearing down asyncio's default
  ThreadPoolExecutor before our `on_call_ended` could finish, and
  `aiosmtplib`'s DNS lookup failed with `Executor shutdown has been
  called`. Result: zero emails delivered on agent-ended calls.
  - `_speak_goodbye_and_terminate` now `await`s
    `lifecycle.on_call_ended()` **before** invoking `_terminate_room`,
    so transcript writes + deferred message emails + call-end emails
    fire while the event loop and executor are still healthy.
  - `CallLifecycle` gains a `_finalized` flag. The LiveKit session-close
    handler still invokes `on_call_ended` on natural disconnect, but
    the second call is now a guarded no-op (no duplicate emails, no
    duplicate transcript writes).
  - INFO-level diagnostic logging on both sides
    (`agent_end: invoking lifecycle.on_call_ended pre-terminate
    (pending=N, channels=M)`, `on_call_ended entered (finalized=…)`)
    so the same race is one log read away if it ever recurs.
  - Regression test in `tests/test_lifecycle.py::test_on_call_ended_is_idempotent`
    proves a double-call yields exactly one email and one transcript write.

### Changed (privacy / housekeeping)
- **Sanitized the tracked law-firm template.** The previous
  `config/businesses/example-licomplaw.yaml` carried client-identifying
  values (business display name, receptionist persona name, intake email
  domain, and a tenant-specific Resend env-var name). Renamed to
  `config/businesses/example-workers-comp.yaml` and replaced every
  identifying string with a generic placeholder:
  - business display name → `Example Workers' Comp Law`
  - persona name → `Alex`
  - intake email → `intake@example.com`
  - Resend env var → `EXAMPLE_RESEND_API_KEY`
  - file/recording/transcript paths → `./{messages,recordings,transcripts}/example-workers-comp/`

  Updated `tests/test_config.py` to match (with a regression guard that
  asserts the public template contains no `licomplaw` / `nycomplaw`
  substring), and updated `.env.example`, `documentation/ringcentral-setup.md`,
  `documentation/multi-business-setup.md`, `documentation/configuration-reference.md`,
  and `tests/MANUAL.md` to reference the new template name and `<slug>`
  placeholders instead of tenant-specific values. Operators copying the
  template into a tenant-local YAML still override every placeholder, so
  no behavior changes — only the surface that ends up on GitHub.
- **Stopped tracking `/docs/`.** That directory holds internal design
  specs, implementation plans, and superpowers workflow artifacts that
  aren't user-facing reference docs. Added `docs/` to `.gitignore` and
  ran `git rm -r --cached docs/` so the files stay on disk locally for
  development history but no longer ship in the public repository. The
  three tracked references to `docs/plans/` (in `CLAUDE.md`,
  `documentation/CHANGELOG.md`'s artifact list, and `documentation/index.md`'s
  file-tree) were removed.

### Added
- **Telephony setup guide for non-default paths** (closes #4).
  New `documentation/telephony-setup.md` documents the three realistic
  ways a PSTN number reaches AIReceptionist: porting to a SIP trunk
  provider (Path A — the tested default), Bring Your Own Carrier with a
  transit provider like Telnyx BYOC (Path B), and keeping a copper
  landline via an FXS gateway (Grandstream HT813 or similar) plus an
  on-prem PBX (Path C). Includes a starter Asterisk `pjsip.conf` +
  `extensions.conf` snippet for Path C, a trade-off table comparing the
  three, and explicit E911 / power-outage / internet-outage caveats.
  Linked from README and `documentation/index.md`. Path C is explicitly
  marked as untested by the project's CI; treat the snippet as a
  starting point.

### Changed
- **Configuration reference rewritten for the channels-based schema.**
  `documentation/configuration-reference.md` previously described the
  long-gone `messages.delivery: file|webhook` shape. It now documents the
  current `messages.channels: [...]` list (with the file, email, and
  webhook channel sub-schemas), the top-level `email:` block (SMTP /
  Resend, triggers), the `recording:` block (local + S3-compatible
  storage, consent preamble), the `transcripts:` block, the `retention:`
  block, and the `languages:` block. Complete Example, Table of Contents,
  and Validation Rules updated to match.
- **Linux systemd deployment guide tightened for issue #14.** The previous
  recipe referenced `/opt/ai-receptionist` while `git clone` actually
  produces `/opt/AIReceptionist`, and didn't show the
  `python -m venv .venv` step. The agent appeared to start but couldn't
  import its own modules under the service user (`ModuleNotFoundError`).
  Updated the deployment guide to use `/opt/AIReceptionist` consistently,
  to create the service user explicitly, to set up the venv with
  `python3 -m venv .venv` before `pip install -e .`, to lock `.env` to
  `chmod 600` and `chown ai-receptionist`, and to document the
  lowercased-alias symlink as the optional last step instead of an
  implicit assumption.

### Added
- **Full transcript embedded in caller-message emails too** (parallel to
  the call-end email). When the caller invokes `take_message` mid-call,
  the file/webhook channels still fire synchronously (caller hears
  "saved", message data is durable on disk before we return), but the
  EmailChannel portion is intentionally deferred to call-end so the
  message email can embed the full conversation that led up to the
  message. New plumbing:
  - `Dispatcher.dispatch_message` accepts `skip_email_channel=True`,
    which the `take_message` tool now sets.
  - `CallLifecycle.enqueue_message_email(msg)` queues messages; the
    queue drains in `on_call_ended` after the transcript file is written,
    firing `EmailChannel.deliver(msg, ctx)` for each configured channel
    when the `on_message` email trigger is enabled.
  - `build_message_email` mirrors `build_call_end_email`: it accepts
    `include_transcript` / `include_recording_link` and embeds the
    transcript with the same `(transcript_unavailable)` fallback when
    the file can't be read. `EmailChannel.deliver` passes the per-channel
    flags through from `channel_config`.
  - 8 new regression tests across templates, channel, dispatcher, and
    lifecycle; full suite `400 passed, 2 skipped`.
- **Full transcript embedded in call-end emails** (and `include_transcript` /
  `include_recording_link` per-channel toggles now actually do something).
  Previously the two flags on `messages.channels[type=email]` were dead — the
  call-end template only ever rendered the transcript file *path*. Now, when
  `include_transcript: true` (default) and a markdown transcript exists, the
  agent reads the file and embeds the conversation directly into the email
  body (plain text + a monospace `<pre>` block in HTML), so the operator can
  read the call without opening another file. If the markdown file is missing
  or unreadable the email still sends with the path plus a
  `(transcript_unavailable)` marker — the call-end flow never crashes over
  an unreadable transcript. `include_recording_link: false` now suppresses
  the recording URL/failure row entirely for tenants who don't want bucket
  links in mail. New regression coverage in `tests/email/test_templates.py`
  and `tests/messaging/test_email_channel.py`; full suite `390 passed, 2 skipped`.
- **RingCentral + Twilio law-firm deployment guide**:
  `documentation/ringcentral-setup.md` documents the RingEX reception-group
  path where a Twilio DID acts as the AI bridge into LiveKit SIP, using named
  agent dispatch with `metadata={"config":"<slug>"}` where `<slug>` is the
  tenant's chosen business slug.
- **`example-workers-comp` business config template**: tracked template for
  a workers' compensation law firm using the RingCentral + Twilio + LiveKit
  path. Uses generic placeholder values (business name
  `Example Workers' Comp Law`, persona `Alex`, intake email
  `intake@example.com`, Resend env var `EXAMPLE_RESEND_API_KEY`) so the
  public template never carries client identity; operators override every
  placeholder when they copy the template into their gitignored local YAML.
  Enables local recording + transcript storage, disables the recording
  consent preamble, and ships 15 placeholder claims-rep transfer targets
  to replace before go-live. Originally tracked as `example-licomplaw.yaml`
  but renamed for sanitization.
- **ChatGPT OAuth setup documentation**: new
  `documentation/chatgpt-oauth-setup.md` explains how to use a ChatGPT/Codex
  login token for OpenAI Realtime so eligible ChatGPT subscriptions can power
  calls instead of an OpenAI Platform API key. README, deployment,
  development, configuration, troubleshooting, `.env.example`, and docs index
  pages now link to the flow.
- **`voice.idle` safety nets** (issue #11): configurable guards stop the
  agent from running indefinitely on silent or off-topic callers.
  - **Silence hangup** (default ON, 15s away + 30s grace = 45s total
    silence). Wires `AgentSession.user_away_timeout` and a `user_state_changed`
    listener; if the caller stays `away` past the grace period, the agent
    says a brief "we'll wrap up" and disconnects with reason
    `silence_timeout`. Disable per business with `voice.idle.silence_hangup_enabled: false`.
  - **Max-duration cap** (default OFF). Set
    `voice.idle.max_call_duration_seconds: 900` to cap calls at 15 minutes;
    the agent will say goodbye and disconnect with reason
    `max_duration_reached` when the cap is reached.
  - **Absolute silence fallback** (default OFF). Set
    `voice.idle.absolute_silence_seconds: 120` to end with reason
    `silence_timeout` when no non-empty final user transcript arrives for two
    minutes, even if SIP comfort noise prevents LiveKit's `user_state` from
    becoming `away`.
  - **Unproductive-turn ceiling** (default ON, threshold 5). Counts
    consecutive agent replies that match a tunable list of "stuck"
    phrases (`unproductive_phrases`) AND did not invoke any function tool
    that turn. It only scores replies after a final caller transcript, so
    greetings and consent preambles cannot consume the budget. After the
    threshold, the agent ends with reason `unproductive_turns_exhausted`.
    Catches the Trinicom Blade Runner scenario where the caller monologues
    at the agent for 21 minutes.
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
  `silence_timeout`, `unproductive_turns_exhausted`,
  `max_duration_reached`); call-end emails and Markdown transcript headers
  render it next to the outcome row.

### Fixed
- **Muted-call silence timeout fallback** (issue #11): SIP trunks that send
  comfort noise can keep LiveKit's `user_state` from becoming `away`, which
  bypassed the original silence watcher. The optional
  `voice.idle.absolute_silence_seconds` timer now measures wall-clock time
  since the last non-empty final user transcript and uses the same
  `silence_timeout` hangup path.
- **Benign post-close LiveKit engine warning** (issue #10): the exact
  `WARNING ... engine: connection error: engine is closed` line emitted after
  intentional call teardown is now suppressed while other engine connection
  errors still log normally.
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
- **LiveKit agent dispatch default** now registers the worker as
  `receptionist` via `RECEPTIONIST_AGENT_NAME`, matching production dispatch
  rules by default. Local Playground/wildcard testing can still set
  `RECEPTIONIST_AGENT_NAME=""` for the current process.
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
  expired access tokens with `tokens.refresh_token`, serializes concurrent
  refreshes with an in-process lock plus a per-file refresh lock, and writes
  rotated tokens back to the same auth file.
- **OpenAI OAuth setup CLI**: `python -m receptionist.voice setup <business>`
  validates an existing per-business target token when present; otherwise it
  runs Codex login, copies the Codex auth file to
  `secrets/<business>/openai_auth.json`, validates it, and updates the
  business YAML `voice.auth` block. `--reuse-existing-codex-auth` is available
  for non-interactive smoke tests that intentionally copy an existing Codex
  auth file.
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
- Webhook delivery was originally stubbed in that historical version

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
