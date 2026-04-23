# Call Artifacts and Delivery — Design Spec

> **Status:** Draft — pending user review
> **Created:** 2026-04-23
> **Scope:** Production-readiness feature set covering call recording, transcripts, multi-channel message delivery (file/webhook/email), email triggers, retention, consent preamble, multi-language, and OpenAI model/voice upgrade.

---

## 1. Summary

Expand the AIReceptionist project from a single-channel, file-only messaging system into a production-grade receptionist platform with:

- **Call recordings** (LiveKit Egress → local disk or S3)
- **Call transcripts** (JSON source-of-truth + Markdown human-readable), with rich call metadata
- **Multi-channel message delivery** (file + webhook + email, configurable per business, enabled simultaneously)
- **Email delivery** via pluggable senders (SMTP + Resend), with separate triggers for message-taken and call-ended
- **Retention** with configurable TTL per artifact type
- **Consent preamble** spoken before the greeting when recording is enabled
- **Multi-language auto-detection** with a per-business language whitelist
- **OpenAI Realtime model upgrade** from `gpt-realtime` → `gpt-realtime-1.5` with `marin` as the new default voice
- **Failure visibility** via `.failures/` directory and a `list-failures` CLI

Architecture approach: reorganize `receptionist/` into capability-focused subpackages (`messaging/`, `email/`, `recording/`, `transcript/`, `retention/`). Each is independently testable with a small, mockable surface. `agent.py` becomes a thin orchestrator.

---

## 2. Configuration schema

Configuration remains YAML at `config/businesses/<name>.yaml`. Here is the full shape after this change. New/changed fields are marked.

```yaml
business:
  name: "Acme Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "marin"              # CHANGED default: was "coral"
  model: "gpt-realtime-1.5"      # CHANGED default: was "gpt-realtime"

languages:                       # NEW
  primary: "en"                  # greeting/FAQ language (ISO 639-1)
  allowed: ["en", "es"]          # auto-detect whitelist

greeting: "Thank you for calling Acme Dental, how can I help you today?"

personality: |
  You are a warm, professional receptionist for a dental office...

hours:
  monday:    { open: "08:00", close: "17:00" }
  # ... unchanged

after_hours_message: |
  Our office is currently closed...

routing:
  - name: "Front Desk"
    number: "+15551234567"
    description: "General inquiries, scheduling"
  # ... unchanged

faqs:
  - question: "..."
    answer: "..."
  # ... unchanged

# === MESSAGES: multi-channel delivery ===
messages:                        # CHANGED: was single `delivery`
  channels:
    - type: "file"
      file_path: "./messages/acme-dental/"
    - type: "email"
      to: ["owner@acmedental.com"]
      include_transcript: true
      include_recording_link: true
    - type: "webhook"
      url: "https://hooks.slack.com/services/..."
      headers:
        X-Api-Key: "${SLACK_TOKEN}"

# === RECORDING === (NEW section)
recording:
  enabled: true
  storage:
    type: "s3"                   # or "local"
    local:
      path: "./recordings/acme-dental/"
    s3:
      bucket: "acme-recordings"
      region: "us-east-1"
      prefix: "acme-dental/"
      endpoint_url: null         # optional, for R2/B2/MinIO
  consent_preamble:
    enabled: true
    text: "This call may be recorded for quality purposes."

# === TRANSCRIPTS === (NEW section)
transcripts:
  enabled: true
  storage:
    type: "local"
    path: "./transcripts/acme-dental/"
  formats: ["json", "markdown"]

# === EMAIL === (NEW section, shared by all email-consuming components)
email:
  from: "receptionist@acmedental.com"
  sender:
    type: "smtp"                 # or "resend"
    smtp:
      host: "smtp.gmail.com"
      port: 587
      username: ${SMTP_USERNAME}  # env-var reference, interpolated at load time
      password: ${SMTP_PASSWORD}  # env-var reference, interpolated at load time
      use_tls: true
    resend:
      api_key: "${RESEND_API_KEY}"
  triggers:
    on_message: true             # email when take_message fires
    on_call_end: false           # email summary after every call

# === RETENTION === (NEW section)
retention:
  recordings_days: 90            # 0 = keep forever
  transcripts_days: 90
  messages_days: 0               # default: keep messages forever
```

### 2.1 Key design decisions

1. **`messages.channels` is a list.** A business can enable file + email + webhook simultaneously. Replaces the previous `delivery` enum.
2. **Recording and transcripts are top-level, not nested under messages.** They are independent artifacts with independent enable/disable.
3. **Email config is shared.** Sender configuration lives in one place (`email.sender`) and is reused by both the `email` message channel and the `on_call_end` trigger. Triggers are separate toggles.
4. **`${ENV_VAR}` interpolation.** A Pydantic v2 validator expands `${VAR_NAME}` references against `os.environ` at load time. Missing variables raise a clear validation error. Values without `${...}` are passed through unchanged.
5. **Backwards compatibility.** The legacy single-channel form:
   ```yaml
   messages:
     delivery: "file"
     file_path: "./messages/acme-dental/"
   ```
   is auto-converted to the new `channels: [{type: "file", file_path: "..."}]` form via a Pydantic `model_validator`. Existing configs continue to work. Deprecation warning is logged on load. The legacy form will be removed in a future release after a deprecation cycle.
6. **S3 `endpoint_url` is optional.** When set, allows using S3-compatible backends (Cloudflare R2, Backblaze B2, MinIO). When null, the aioboto3 default AWS endpoint is used.

### 2.2 Pydantic model updates (`receptionist/config.py`)

New models:
- `LanguagesConfig(primary: str, allowed: list[str])` — ISO 639-1 codes, validated against a known set
- `FileChannel(type: Literal["file"], file_path: str)`
- `EmailChannel(type: Literal["email"], to: list[str], include_transcript: bool = True, include_recording_link: bool = True)`
- `WebhookChannel(type: Literal["webhook"], url: str, headers: dict[str, str] = {})`
- `MessageChannel = Annotated[Union[FileChannel, EmailChannel, WebhookChannel], Field(discriminator="type")]`
- `LocalStorageConfig(path: str)`
- `S3StorageConfig(bucket: str, region: str, prefix: str = "", endpoint_url: str | None = None)`
- `RecordingStorageConfig(type: Literal["local","s3"], local: LocalStorageConfig | None, s3: S3StorageConfig | None)` with `model_validator` ensuring the matching sub-config is present
- `ConsentPreambleConfig(enabled: bool, text: str)`
- `RecordingConfig(enabled: bool, storage: RecordingStorageConfig, consent_preamble: ConsentPreambleConfig)`
- `TranscriptStorageConfig(type: Literal["local"], path: str)` (S3 for transcripts is future work)
- `TranscriptsConfig(enabled: bool, storage: TranscriptStorageConfig, formats: list[Literal["json","markdown"]])`
- `SMTPConfig(host: str, port: int, username: str, password: str, use_tls: bool = True)`
- `ResendConfig(api_key: str)`
- `EmailSenderConfig(type: Literal["smtp","resend"], smtp: SMTPConfig | None, resend: ResendConfig | None)` with matching `model_validator`
- `EmailTriggers(on_message: bool = True, on_call_end: bool = False)`
- `EmailConfig(from_: str (aliased to "from"), sender: EmailSenderConfig, triggers: EmailTriggers)`
- `RetentionConfig(recordings_days: int = 90, transcripts_days: int = 90, messages_days: int = 0)` — `0` means keep forever

Updated `BusinessConfig` adds: `languages: LanguagesConfig`, `recording: RecordingConfig | None`, `transcripts: TranscriptsConfig | None`, `email: EmailConfig | None`, `retention: RetentionConfig = RetentionConfig()`. `messages.channels: list[MessageChannel]` replaces `messages.delivery`.

A top-level validator on `BusinessConfig` enforces cross-section invariants:
- If any `EmailChannel` is configured OR `email.triggers.on_call_end` is true, `email` section must be present.
- If `email` section is present and sender type is `smtp`, `email.sender.smtp` must be populated.
- If `recording.enabled` is false, `consent_preamble.enabled` is ignored (no-op).

### 2.3 Env-var interpolation

A root-level `@field_validator("*", mode="before")` is not sufficient because it fires per-model-field. Instead, a pre-parse step in `BusinessConfig.from_yaml_string()` walks the parsed YAML dict and substitutes `${VAR}` patterns in string values. Algorithm:

```
def _interpolate_env_vars(node):
    if isinstance(node, str):
        return re.sub(r'\$\{([A-Z_][A-Z0-9_]*)\}',
                      lambda m: _lookup_env_or_raise(m.group(1)),
                      node)
    if isinstance(node, dict): return {k: _interpolate_env_vars(v) for k, v in node.items()}
    if isinstance(node, list): return [_interpolate_env_vars(v) for v in node]
    return node
```

Missing env vars raise `ConfigError` with the variable name. Values with no `${...}` pattern pass through.

---

## 3. Package structure

```
receptionist/
├── __init__.py
├── agent.py                     # Thin session orchestrator
├── config.py                    # Pydantic models (expanded) + env-var interpolation
├── prompts.py                   # System prompt builder (adds language + consent blocks)
├── lifecycle.py                 # Call lifecycle hooks; owns CallMetadata for the active call
│
├── messaging/
│   ├── __init__.py
│   ├── models.py                # Message dataclass (moved from messages.py)
│   ├── dispatcher.py            # fans Message out to all configured channels
│   ├── failures.py              # .failures/ directory management + list-failures CLI
│   └── channels/
│       ├── __init__.py
│       ├── file.py              # file-write (from messages.py)
│       ├── webhook.py           # httpx POST with retry/backoff
│       └── email.py             # builds email via templates, sends via sender
│
├── email/
│   ├── __init__.py
│   ├── sender.py                # EmailSender protocol + EmailSendError
│   ├── smtp.py                  # aiosmtplib implementation
│   ├── resend.py                # resend-python implementation
│   └── templates.py             # Subject/body builders
│
├── recording/
│   ├── __init__.py
│   ├── egress.py                # start/stop LiveKit Egress wrapper
│   └── storage.py               # resolves local path vs S3 destination
│
├── transcript/
│   ├── __init__.py
│   ├── capture.py               # subscribes to AgentSession events
│   ├── formatter.py             # JSON + Markdown renderers
│   └── metadata.py              # CallMetadata dataclass
│
└── retention/
    ├── __init__.py
    └── sweeper.py               # CLI: `python -m receptionist.retention sweep`
```

### 3.1 Component responsibilities

| Component | Responsibility | Depends on |
|---|---|---|
| `agent.py` | Loads config, instantiates `Receptionist`, wires lifecycle hooks, starts session | `config`, `lifecycle` |
| `lifecycle.py` | Owns `CallMetadata` for the active call; subscribes to session events (greeting, tool calls, disconnect); triggers channel dispatch on call-end | `transcript`, `recording`, `messaging` |
| `messaging/dispatcher.py` | Takes a `Message` + `MessagesConfig`, awaits file channel synchronously, fires email/webhook as background tasks | `messaging/channels`, `messaging/failures` |
| `messaging/channels/*` | One per delivery type. Each implements `async def deliver(message, context) -> None`. `context` contains transcript/recording references when applicable | `email`, storage refs |
| `messaging/failures.py` | Writes failure records to `<file_path>/.failures/`, implements `list-failures` CLI | — |
| `email/sender.py` | `EmailSender` protocol: `async def send(to, subject, body_html, body_text, attachments) -> None`. Raises `EmailSendError(transient: bool)` | — |
| `email/smtp.py`, `email/resend.py` | Concrete `EmailSender` implementations | `aiosmtplib` / `resend` |
| `email/templates.py` | Pure functions: `build_message_email(msg, context)`, `build_call_end_email(metadata, context)` | — |
| `recording/egress.py` | `start_recording(room, config) -> RecordingHandle`, `stop_recording(handle) -> RecordingArtifact` | `livekit api` |
| `recording/storage.py` | Resolves destination (local path or S3 URL), uploads for local→S3 if needed | `aioboto3`, `aiofiles` |
| `transcript/capture.py` | `TranscriptCapture(session)` — listens to `user_input_transcribed`, `agent_speech_*`, tool invocations; accumulates `TranscriptSegment` list in memory | `livekit AgentSession` |
| `transcript/formatter.py` | `to_json(segments, metadata) -> str`, `to_markdown(segments, metadata) -> str` | — |
| `transcript/metadata.py` | `CallMetadata` dataclass: `caller_phone`, `start_ts`, `end_ts`, `duration`, `outcome`, `transfer_target`, `message_taken`, `faqs_answered`, `languages_detected`, `recording_failed`, `recording_artifact` | — |
| `retention/sweeper.py` | Walks configured artifact directories per business, deletes files older than TTL. Skips `.failures/` directories. | `config` |

### 3.2 Key boundaries

- **Transcript capture is independent of storage.** `TranscriptCapture` accumulates segments in memory during the call. `transcript/formatter.py` renders to text. Storage is a separate decision made in `lifecycle.on_call_ended()`.
- **Recording uses an async handle pattern.** Egress starts at call pickup, returns a handle. Stop at call end, returns the artifact. Neither touches audio bytes directly — LiveKit Egress handles the heavy lifting.
- **Dispatcher is the only thing `lifecycle` and `take_message` call.** Channels don't know about each other. Adding SMS later means `messaging/channels/sms.py` and registering it in the dispatcher — no other changes.
- **Email is a utility, not a channel.** The `email/` subpackage provides senders and templates. The actual channel is `messaging/channels/email.py`, which decides *what* goes in the email.
- **Retention is a separate process.** `python -m receptionist.retention sweep` runs on cron. Not part of agent runtime.

---

## 4. Data flow

### 4.1 End-to-end call lifecycle

```
1. Call arrives
   └─> agent.handle_call(ctx)
       ├─> config = load_business_config(ctx)
       ├─> metadata = CallMetadata(caller_phone=..., start_ts=now)
       ├─> transcript = TranscriptCapture(session, metadata) if config.transcripts.enabled
       ├─> if config.recording.enabled:
       │     recording_handle = await egress.start_recording(ctx.room, config)
       │     (sets metadata.recording_failed = True on exception, proceeds)
       └─> session.start(Receptionist(config, metadata, transcript), ...)

2. Consent preamble + greeting  (order matters: preamble FIRST)
   └─> Receptionist.on_enter()
       ├─> if config.recording.enabled and config.recording.consent_preamble.enabled:
       │     speak(config.recording.consent_preamble.text)
       └─> speak(config.greeting)

3. Conversation loop
   ├─> Caller speaks        -> user_input_transcribed event -> transcript.capture()
   │                                                        -> metadata.languages_detected.add(detected_lang)
   ├─> Agent speaks         -> agent_speech event           -> transcript.capture()
   └─> Tool invocations:
       ├─> lookup_faq       -> metadata.faqs_answered.append(faq_question)
       ├─> transfer_call    -> metadata.transfer_target = dept_name
       │                       metadata.outcome = "transferred"
       ├─> take_message     -> dispatcher.dispatch_message(Message, context)
       │                       ├─> AWAIT FileChannel.deliver(...)    [durable]
       │                       └─> asyncio.create_task for EmailChannel, WebhookChannel
       │                       metadata.message_taken = True
       │                       metadata.outcome = "message_taken" (if not already "transferred")
       └─> get_business_hours -> no metadata change

4. Call end (disconnect event)
   └─> lifecycle.on_call_ended()
       ├─> metadata.end_ts = now
       ├─> metadata.duration = end_ts - start_ts
       ├─> if metadata.outcome is None: metadata.outcome = "hung_up"
       ├─> if recording_handle: artifact = await egress.stop_recording(handle)
       │                         metadata.recording_artifact = artifact
       ├─> if config.transcripts.enabled:
       │     transcript_json = transcript.formatter.to_json(segments, metadata)
       │     transcript_md   = transcript.formatter.to_markdown(segments, metadata)
       │     write both to config.transcripts.storage.path (via asyncio.to_thread or aiofiles)
       ├─> if config.email.triggers.on_call_end:
       │     dispatcher.dispatch_call_end(metadata, transcript_refs, artifact)
       │     └─> EmailChannel only (call-end has no file/webhook equivalent)
       └─> done
```

### 4.2 Consent preamble placement

**Decision: preamble is spoken before the greeting**, not after. Reason: in two-party consent states (CA, FL, IL, MD, MA, MT, NV, NH, PA, WA), callers must be notified before being recorded. Speaking the greeting first creates a compliance gap where the greeting itself is recorded without disclosure.

Implementation: `Receptionist.on_enter()` checks recording+preamble config and speaks preamble first. Egress is already running by this point, so the preamble itself is recorded (which is correct — the record shows disclosure happened).

### 4.3 Synchronous vs fire-and-forget dispatch

**`take_message` tool function:**
- Awaits `FileChannel.deliver(...)` synchronously. Guarantees a durable copy exists before the LLM confirms "message saved" to the caller.
- Fires `EmailChannel` and `WebhookChannel` via `asyncio.create_task(...)`. Tool returns immediately; channels proceed in the background.
- If no file channel is configured, the tool still awaits *one* channel synchronously (preference order: file > webhook > email) to maintain the "something durable exists before we confirm" invariant.

**Rationale:** a slow SMTP server or webhook endpoint would otherwise hold up the tool response, causing the agent to sit silent for seconds mid-call.

### 4.4 `CallMetadata` outcome resolution

Outcome priority (higher wins when multiple fire):

1. `"transferred"` (transfer_call succeeded)
2. `"message_taken"` (take_message succeeded)
3. `"hung_up"` (no tool fired, call ended)

If `transfer_call` succeeds after `take_message` (unusual but possible), outcome is `"transferred"`. This reflects the business-relevant final state.

---

## 5. Error handling

Principle: **failures in delivery channels never affect the caller's experience.** The call keeps going, artifacts land where they can, failures get logged and optionally retried.

### 5.1 Per-component failure behavior

| Component | Failure mode | Handling |
|---|---|---|
| Transcript capture | Event handler raises | try/except around each handler, log, skip segment, continue. No retry. |
| Recording start | Egress API error | Log with correlation ID, set `recording_handle = None`, `metadata.recording_failed = True`. Call proceeds. No retry (start-time failures repeat). |
| Recording stop | Stop API error / missing artifact | Log, leave `metadata.recording_artifact = None`, proceed with transcript + email. Treat start-time URL as authoritative. |
| Transcript write | Disk full / permission / invalid JSON | Try JSON first, Markdown second (independent). Log each failure. If both fail, email (if enabled) includes transcript inline in body as fallback. |
| File channel | Disk full / permission | Raise. Dispatcher propagates. `take_message` returns error to LLM → LLM offers alternative ("let me transfer you"). Full error logged server-side. |
| Email channel (background) | SMTP timeout / Resend rate limit / invalid address | Retry with exponential backoff: `max_attempts=3, initial=1s, factor=2`. On exhaustion: write failure record to `<file_path>/.failures/YYYYMMDD_HHMMSS.json`. |
| Webhook channel (background) | 4xx, 5xx, timeout | 4xx: no retry (permanent). 5xx + timeout: retry with same backoff. Same `.failures/` on exhaustion. |
| Email sender (SMTP) | Connection errors | Raise `EmailSendError(transient=True)`. Dispatcher retries. |
| Email sender (SMTP) | Auth errors | Raise `EmailSendError(transient=False)`. No retry. |
| Email sender (Resend) | 429 | Raise `EmailSendError(transient=True, retry_after=header)`. |
| Email sender (Resend) | 401/403 | Raise `EmailSendError(transient=False)`. |
| Retention sweeper | File locked / permission | Log per-file, skip, continue. Summary at end: `deleted N, failed M`. Non-zero exit only if ALL deletions failed. |
| Language detection out of whitelist | Caller speaks unsupported language | LLM prompt instructs it to politely respond in the primary language: "I can assist in English or Spanish — which would you prefer?" Continue conversation. No hard error. |

### 5.2 `.failures/` directory

Path resolution order:
1. If a `FileChannel` is configured in `messages.channels`, use `<file_channel.file_path>/.failures/`.
2. Otherwise, use `./messages/<business_name_slug>/.failures/` (created on demand; `business_name_slug` is derived from `business.name` via `re.sub(r'[^a-zA-Z0-9_-]+', '-', name).lower()`).

This guarantees `.failures/` always has a stable, writable location regardless of channel configuration.

Failure record format (one file per failure):
```json
{
  "failed_at": "2026-04-23T14:30:00.123456+00:00",
  "channel": "email",
  "message": { ...full Message dataclass... },
  "context": { "transcript_path": "...", "recording_url": "..." },
  "attempts": [
    {"attempt": 1, "error_type": "SMTPAuthError", "error_detail": "535 authentication failed", "at": "..."},
    {"attempt": 2, "error_type": "SMTPAuthError", "error_detail": "...", "at": "..."},
    {"attempt": 3, "error_type": "SMTPAuthError", "error_detail": "...", "at": "..."}
  ]
}
```

The retention sweeper explicitly skips `.failures/` directories — failure records are not subject to TTL.

### 5.3 Logging contract

Every failure log line includes:
- `call_id` — LiveKit room name, stable per call
- `business_name` — from config
- `component` — e.g., `"messaging.channels.email"`
- `error_type` — exception class name
- `error_detail` — message, sanitized of credentials

Log format stays Python's `logging` default for now (structured JSON logging is HANDOFF §12 #9, deferred).

### 5.4 What's explicitly NOT retried

- LLM/OpenAI Realtime failures — LiveKit/OpenAI own reconnection.
- SIP transfer failures — existing `transfer_call` handling preserved.
- Local disk writes — if disk is broken, retries don't help.

### 5.5 What's surfaced to the caller

Nothing, with one exception: if `take_message`'s synchronous channel (typically file) fails, the LLM is informed so it can offer an alternative. Every other failure is silent from the caller's perspective.

---

## 6. Testing strategy

### 6.1 Unit tests (required)

Each new subpackage gets a dedicated test file. Target: 3–6 tests per component covering main success path and main failure mode.

| Test file | Covers |
|---|---|
| `tests/messaging/test_dispatcher.py` | Multi-channel fan-out, file-first sequencing, fire-and-forget for email/webhook, failure → `.failures/` write, empty channel list → no-op |
| `tests/messaging/test_file_channel.py` | Ported from existing `test_messages.py` |
| `tests/messaging/test_webhook_channel.py` | Successful POST, 4xx no-retry, 5xx retry with backoff, env-var header interpolation |
| `tests/messaging/test_email_channel.py` | Correct subject/body for Message + CallMetadata triggers, `include_transcript` / `include_recording_link` toggles |
| `tests/messaging/test_failures.py` | Writes correctly-shaped failure records, list-failures CLI happy path, empty dir path, corrupt-JSON skip-and-continue |
| `tests/email/test_templates.py` | Pure functions: subject formatting, Markdown body rendering, attachment metadata |
| `tests/email/test_smtp.py` | `aiosmtplib` mocked; transient vs. permanent error classification |
| `tests/email/test_resend.py` | `respx` mock transport; 429 Retry-After, 401 permanent |
| `tests/transcript/test_capture.py` | Segments accumulate in order, tool calls captured, concurrent user+agent speech interleaves correctly |
| `tests/transcript/test_formatter.py` | JSON shape stable (golden file), Markdown output matches snapshot |
| `tests/transcript/test_metadata.py` | Outcome resolution priority, duration math across timezones |
| `tests/recording/test_storage.py` | Resolves local path correctly, constructs S3 URL correctly (uses moto for S3). Does NOT test egress actually running. |
| `tests/retention/test_sweeper.py` | Deletes files older than TTL, skips `.failures/`, handles `0 = keep forever`, logs per-file errors |
| `tests/test_config.py` (expanded) | New fields validated, env-var interpolation, backwards-compat legacy `delivery` → `channels`, language whitelist |

### 6.2 Shared fixtures (`tests/conftest.py`)

- `make_config(**overrides)` — returns a `BusinessConfig` with sensible defaults
- `make_message(...)` — returns a `Message` with defaults
- `make_call_metadata(...)` — returns a populated `CallMetadata`
- `tmp_business_dir(tmp_path)` — realistic `messages/`, `transcripts/`, `recordings/` layout
- `mock_email_sender` — records calls to `EmailSender.send(...)` without sending
- `moto_s3` — aioboto3 + moto v5 `@mock_aws` fixture for S3 tests

### 6.3 NOT unit-tested (intentional)

| Skipped | Why |
|---|---|
| `agent.py` session setup | Mocking `livekit-agents` SDK not cost-effective; manual validation instead |
| `Receptionist` tool methods | Orchestration shells around tested components |
| LiveKit Egress API calls | External service; test only our thin wrapper |
| Actual SMTP delivery | Out of scope; test up to `aiosmtplib.send(...)` boundary |

### 6.4 Integration test

One integration test guards cross-component wiring:

`tests/integration/test_call_flow.py::test_message_taken_dispatches_to_all_channels`
- Loads test YAML with file + email + webhook channels enabled
- Calls `messaging.dispatcher.dispatch_message(...)` directly
- Asserts: file written, mock email sender called, mock webhook received POST
- Fails if any channel is skipped

### 6.5 Manual validation (`tests/MANUAL.md`)

Walked through each release:

- [ ] Place LiveKit playground call → greeting heard
- [ ] Place Spanish-language call with `allowed: ["en","es"]` → agent responds in Spanish
- [ ] Recording enabled → file appears in configured storage (local or S3)
- [ ] Consent preamble heard before greeting when recording enabled
- [ ] Leave a voice message → file written, email received, webhook endpoint receives POST
- [ ] Hang up mid-call → transcript + metadata finalized; call-end email sent (if configured)
- [ ] `python -m receptionist.retention sweep --dry-run` → lists files that would be deleted
- [ ] `python -m receptionist.messaging list-failures` → lists any `.failures/` records

### 6.6 Coverage target

Current suite: 15 tests. New suite adds ~40–50 tests (total ~55–65). Goal is not a percentage — every public function in `messaging/`, `email/`, `transcript/`, `recording/storage`, `retention/` has at least one test exercising success + one main failure mode.

### 6.7 TDD workflow

For each new subpackage: write the test file first (or at least skeletons), then implement. The implementation plan (`writing-plans`) will sequence tests before code within each rollout step.

---

## 7. Dependencies

### 7.1 New production dependencies

| Package | Min version | Purpose |
|---|---|---|
| `aiosmtplib` | `>=3.0` | Async SMTP for email |
| `resend` | `>=2.0` | Resend API client |
| `httpx` | `>=0.27` | Async HTTP (webhook channel, Resend transport) |
| `aioboto3` | `>=13.0` | Async S3 for recording storage |
| `aiofiles` | `>=23.0` | Async file I/O for transcripts |

### 7.2 New dev dependencies

| Package | Min version | Purpose |
|---|---|---|
| `pytest-mock` | `>=3.12` | Cleaner mocking syntax |
| `moto` | `>=5.0` | S3 mock (supports aioboto3 via `@mock_aws`) |
| `respx` | `>=0.21` | `httpx` mock transport |

### 7.3 Environment variables

None required for agent to run. Configs can reference these via `${VAR}` interpolation when the corresponding channel/storage is enabled:

| Variable | Used by |
|---|---|
| `SMTP_USERNAME`, `SMTP_PASSWORD` | SMTP email sender |
| `RESEND_API_KEY` | Resend email sender |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` | S3 recording storage |
| Custom names for webhook auth headers | Webhook channel (e.g., `SLACK_TOKEN`) |

`.env.example` gets an expanded, commented block documenting these.

---

## 8. Operations

### 8.1 New runtime directories (all gitignored)

```
messages/<business>/          # existing; now also holds .failures/
messages/<business>/.failures/
transcripts/<business>/       # new
recordings/<business>/        # new, when storage.type == "local"
```

`.gitignore` adds `transcripts/` and `recordings/`.

### 8.2 New CLI entrypoints

```
python -m receptionist.retention sweep [--dry-run] [--business <name>]
python -m receptionist.messaging list-failures [--business <name>]
```

Both use the same config loader as `agent.py`. Both documented in README and HANDOFF.

### 8.3 Cron recommendation

Documented in README, not shipped:

```
# Unix crontab
0 3 * * * cd /path/to/AIReceptionist && .venv/bin/python -m receptionist.retention sweep
```

Windows scheduled task equivalent also documented.

### 8.4 Python version

- `pyproject.toml requires-python` stays `>=3.11` (no hard upper bound)
- Add `.python-version` pinning to `3.12`
- README + HANDOFF call out: develop and deploy on 3.11 or 3.12; 3.14 dev env is known-working but unsupported by `livekit-agents`

### 8.5 `agent_name` in production

Stays `agent_name=""` for now. Production-named dispatch is a deployment decision tracked in HANDOFF §12 #3, out of scope for this spec.

---

## 9. Rollout sequencing

Each slice ends with `pytest` green and a commit. No giant WIP branches.

1. **Foundation** — Config schema expansion (new Pydantic models, env-var interpolation, backwards-compat legacy `delivery` handling). Tests green.
2. **Model + voice upgrade** — Default model → `gpt-realtime-1.5`, default voice → `marin`. Update `example-dental.yaml` comments. Minimal risk, immediate value.
3. **Package restructure (TDD)** — Write dispatcher tests first (failing). Move `messages.py` → `messaging/channels/file.py`. Implement `messaging/dispatcher.py` with file-only channel. Tests pass. Existing `take_message` tool routes through new dispatcher.
4. **Email subpackage** — `EmailSender` protocol + SMTP impl + Resend impl + templates + `EmailChannel`. Unit tests. No lifecycle integration yet.
5. **Webhook channel** — `WebhookChannel` with retry/backoff, env-var headers. Unit tests.
6. **Transcript capture + formatter** — Accumulate segments, render JSON/Markdown, write on call-end. Unit tests. One integration test.
7. **Recording** — `recording/storage.py` (local + S3 via aioboto3 + moto tests) + `recording/egress.py` (thin egress wrapper). Storage tests; egress validated manually.
8. **Lifecycle integration** — Wire disconnect handler in `agent.py`. Plumb `CallMetadata` + `TranscriptCapture` through `Receptionist`. Fire dispatchers on events. This is where it comes together.
9. **Consent preamble** — Update `Receptionist.on_enter()` to speak preamble first. Update `prompts.py` if the system prompt needs the consent text. Unit test the ordering.
10. **Multi-language** — Add language block to system prompt (`prompts.py`). Validate whitelist codes in `config.py`. Update `example-dental.yaml` with a two-language example.
11. **Retention sweeper + failures CLI** — Both new module CLIs with tests.
12. **Docs + CHANGELOG** — Update `HANDOFF.md`, `documentation/*`, `documentation/CHANGELOG.md`, `.env.example`, `README.md`.
13. **Manual validation** — Walk `tests/MANUAL.md` live against LiveKit playground.

Each step is independently valuable. Stopping after step 4 leaves working email delivery. After step 7, working recordings. After step 8, everything wired.

---

## 10. Out of scope

Tracked for future specs, NOT addressed here:

- Admin web UI (HANDOFF §12 #7)
- Call analytics / metrics dashboards (HANDOFF §13 #8)
- SMS delivery channel
- Retry CLI for `.failures/` (visibility only for now — list-failures exists, resend-failures does not)
- Cron scheduling itself (documented recommendation only)
- `agent.py` unit tests (deferred per §6.3)
- Structured JSON logging (HANDOFF §12 #9)
- Email to S3 storage for transcripts (only local is supported in this spec)
- Production `agent_name` + LiveKit dispatch rules (HANDOFF §12 #3)

---

## 11. Open questions

None at spec-approval time. Record new questions here if they arise during implementation.

---

## 12. References

- HANDOFF.md §11 (design decisions), §12 (known issues), §13 (planned work)
- OpenAI Realtime model changelog: `gpt-realtime-1.5` release 2026-02-23
- LiveKit Egress API: https://docs.livekit.io/agents/egress/
- Keep a Changelog format: https://keepachangelog.com/en/1.1.0/
