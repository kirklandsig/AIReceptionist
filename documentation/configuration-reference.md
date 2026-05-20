# Configuration Reference

This document is a complete reference for the YAML business configuration file used by AI Receptionist. Every field, validation rule, default value, and example is documented here.

---

## Table of Contents

- [Overview](#overview)
- [File Location](#file-location)
- [Complete Example](#complete-example)
- [Field Reference](#field-reference)
  - [business](#business)
  - [voice](#voice)
  - [languages](#languages)
  - [greeting](#greeting)
  - [personality](#personality)
  - [hours](#hours)
  - [after_hours_message](#after_hours_message)
  - [routing](#routing)
  - [faqs](#faqs)
  - [messages](#messages)
  - [email](#email)
  - [recording](#recording)
  - [transcripts](#transcripts)
  - [retention](#retention)
  - [sip](#sip)
- [Validation Rules](#validation-rules)
- [Loading Behavior](#loading-behavior)
- [Tips and Best Practices](#tips-and-best-practices)

---

## Overview

Each business served by AI Receptionist is defined by a single YAML configuration file. This file controls every aspect of the receptionist's behavior: how it greets callers, what it knows about the business, when the business is open, where to transfer calls, and how to handle messages.

Configuration files are validated at load time using Pydantic models defined in `receptionist/config.py`. Invalid configurations produce clear error messages and prevent the agent from starting with bad data.

---

## File Location

Configuration files live in:

```
config/businesses/<slug>.yaml
```

The `<slug>` is an alphanumeric identifier (plus hyphens and underscores) used to reference the config. Examples:

```
config/businesses/example-dental.yaml
config/businesses/example-workers-comp.yaml
config/businesses/smith-law-firm.yaml
config/businesses/downtown_clinic.yaml
```

**Slug validation**: Must match `^[a-zA-Z0-9_-]+$`. No spaces, no path separators, no special characters. This is enforced for security (path traversal prevention).

The checked-in `example-workers-comp.yaml` is a concrete RingCentral/Twilio
workers' compensation law-firm template using generic placeholder values
(business name `Example Workers' Comp Law`, persona `Alex`, intake email
`intake@example.com`, Resend env var `EXAMPLE_RESEND_API_KEY`). Copy it to
a tenant-specific local YAML (e.g. `config/businesses/<your-slug>.yaml`) for
deployment, then replace those placeholders with real values. Any business
YAML other than the tracked `example-*.yaml` files is gitignored by design.

---

## Complete Example

```yaml
business:
  name: "Acme Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"
  idle:
    absolute_silence_seconds: 120

languages:
  primary: "en"
  allowed: ["en", "es"]

greeting: "Thank you for calling Acme Dental. How can I help you today?"

personality: |
  You are a warm, professional dental office receptionist. You speak clearly
  and at a moderate pace. You are patient with callers and always try to be
  helpful. You use simple language and avoid medical jargon unless the caller
  uses it first.

hours:
  monday:    { open: "08:00", close: "17:00" }
  tuesday:   { open: "08:00", close: "17:00" }
  wednesday: { open: "08:00", close: "17:00" }
  thursday:  { open: "08:00", close: "17:00" }
  friday:    { open: "08:00", close: "15:00" }
  saturday:  closed
  sunday:    closed

after_hours_message: |
  Acme Dental is currently closed. I can take a message and someone will
  follow up during our next business day. If this is a dental emergency,
  please go to your nearest emergency room.

routing:
  - name: "Scheduling"
    number: "+15551234001"
    description: "Book, change, or cancel appointments"
  - name: "Billing"
    number: "+15551234002"
    description: "Insurance, payments, and billing questions"

faqs:
  - question: "What insurance do you accept?"
    answer: "We accept most major dental insurance plans including Delta Dental, Cigna, Aetna, MetLife, and United Healthcare."
  - question: "Where are you located?"
    answer: "We are at 123 Main Street, Suite 200."

# Message delivery: each entry in `channels` is independent. File channel
# fires synchronously so the take_message tool can confirm "saved" to the
# caller. Email channel is deferred to call-end so the email body embeds
# the full transcript.
messages:
  channels:
    - type: "file"
      file_path: "./messages/acme-dental/"
    - type: "email"
      to: ["owner@acme-dental.example.com"]
      include_transcript: true
      include_recording_link: true

# Top-level email config used by any `type: "email"` channel and by the
# call-end / booking email triggers.
email:
  from: "Receptionist <noreply@acme-dental.example.com>"
  sender:
    type: "smtp"
    smtp:
      host: "smtp.gmail.com"
      port: 587
      username: "noreply@acme-dental.example.com"
      password: ${ACME_DENTAL_SMTP_PASSWORD}   # env-var interpolation
      use_tls: true
  triggers:
    on_message: true
    on_call_end: true
    on_booking: false

recording:
  enabled: false   # set to true once cloud storage is configured below
  storage:
    type: "s3"
    s3:
      bucket: "acme-dental-recordings"
      region: "us-east-1"
      # endpoint_url: "https://<account>.r2.cloudflarestorage.com"   # for R2/B2/MinIO
  consent_preamble:
    enabled: false
    text: "This call may be recorded for quality and training."

transcripts:
  enabled: true
  storage:
    type: "local"
    path: "./transcripts/acme-dental/"
  formats: ["json", "markdown"]

retention:
  recordings_days: 90
  transcripts_days: 90
  messages_days: 0   # 0 = keep forever

sip:
  transfer_uri_template: "tel:{number}"
```

---

## Field Reference

### business

Business identity information.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | The full business name as it should be spoken. Used in the system prompt and message records. |
| `type` | string | Yes | The type of business (e.g., "dental office", "law firm", "medical clinic"). Used in the system prompt to establish context. |
| `timezone` | string | Yes | Valid IANA timezone identifier for the business location. Invalid zones fail at config load. |

**Timezone examples**: `America/New_York`, `America/Chicago`, `America/Denver`, `America/Los_Angeles`, `Europe/London`, `Asia/Tokyo`

Full list: [IANA Time Zone Database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

```yaml
business:
  name: "Springfield Family Law"
  type: "law firm"
  timezone: "America/Chicago"
```

---

### voice

Voice configuration for the OpenAI Realtime API.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `voice_id` | string | No | `"marin"` | The OpenAI voice to use for the receptionist. |
| `model` | string | No | `"gpt-realtime-1.5"` | The OpenAI Realtime model variant to use. |
| `auth` | object | No | omitted | Per-business auth source for Realtime. If omitted, the LiveKit OpenAI plugin uses `OPENAI_API_KEY` exactly as before. |

**Available models**:

| Model | Description |
|-------|-------------|
| `gpt-realtime-1.5` | Current high-quality speech-to-speech model (default) |
| `gpt-realtime` | Latest speech-to-speech model alias |
| `gpt-4o-realtime-preview` | Original Advanced Voice model |

**Recommendation**: keep the default `gpt-realtime-1.5` unless you have a specific reason to pin another variant.

**Available voices**:

| Voice | Description |
|-------|-------------|
| `alloy` | Neutral, balanced |
| `ash` | Warm, conversational |
| `ballad` | Soft, gentle |
| `coral` | Friendly, professional |
| `echo` | Clear, articulate |
| `sage` | Calm, authoritative |
| `shimmer` | Bright, energetic |
| `verse` | Rich, expressive |
| `marin` | Natural, approachable (default) |

**Recommendation**: `marin` works well with `gpt-realtime-1.5`. `ash` is good for warmer, more personal businesses. `sage` suits authoritative contexts like law firms.

```yaml
voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"
```

#### `voice.auth`

`voice.auth` is optional. If you omit it, the agent keeps the original
behavior: the LiveKit OpenAI plugin reads `OPENAI_API_KEY` from the process
environment.

When `voice.auth` is present, it is strict. The configured source must
resolve successfully; the agent will not silently fall back to a global
`OPENAI_API_KEY` if a business-specific auth source is missing.

##### API key auth

Use the default OpenAI API-key flow, optionally with a business-specific env
var name.

```yaml
voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"
  auth:
    type: "api_key"
    env: "ACME_OPENAI_KEY"  # default: OPENAI_API_KEY
```

##### ChatGPT / Codex OAuth auth

Use the Codex CLI / ChatGPT-login OAuth access token. This lets a business use
the signed-in ChatGPT account's subscription entitlements for OpenAI Realtime
instead of an `OPENAI_API_KEY`, when that account has access to the configured
model. The agent reads
`tokens.access_token` from the JSON file and passes it as the Realtime bearer
token. If the access token is expired or within 60 seconds of expiring, the
agent uses `tokens.refresh_token` to refresh it through OpenAI's OAuth token
endpoint and writes the rotated tokens back to the same file.

```yaml
voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"
  auth:
    type: "oauth_codex"
    path: "~/.codex/auth.json"  # default
```

This path is best for local development or smoke-testing OAuth access. For
multi-tenant production, prefer per-business token files or API keys rather
than sharing one user login across all businesses.

To create a per-business token file, run:

```bash
python -m receptionist.voice setup example-dental
```

If the target token file is already usable, the setup command validates it and
updates the YAML without logging in again. Otherwise, it launches `codex login`,
copies the resulting Codex auth file to `secrets/<business>/openai_auth.json`,
validates the token, and updates the business YAML in place:

```yaml
voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"
  auth:
    type: "oauth_codex"
    path: "secrets/example-dental/openai_auth.json"
```

For multiple businesses using different ChatGPT accounts, run setup once per
business and sign into the correct account each time:

```yaml
# config/businesses/acme.yaml
voice:
  auth:
    type: "oauth_codex"
    path: "secrets/acme/openai_auth.json"

# config/businesses/trinicom.yaml
voice:
  auth:
    type: "oauth_codex"
    path: "secrets/trinicom/openai_auth.json"
```

For non-interactive smoke tests only, `--reuse-existing-codex-auth` skips the
login step when `--codex-auth-source` already contains a usable token. Do not
use that flag for per-business onboarding unless you intentionally want to copy
the currently logged-in Codex account.

See [ChatGPT OAuth Setup](chatgpt-oauth-setup.md) for the complete walkthrough,
including subscription use, multi-business token files, refresh locking, and
troubleshooting.

##### Static OAuth bearer auth

Use a raw bearer token directly or read it from an env var. Prefer
`token_env` so secrets do not live in YAML.

```yaml
voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"
  auth:
    type: "oauth_static"
    token_env: "OPENAI_OAUTH_TOKEN"
```

Exactly one of `token` or `token_env` is required.

#### `voice.idle` (issue #11 safety nets)

`voice.idle` configures independent safety nets so the agent doesn't
hold a SIP and Realtime session open indefinitely. Defaults are conservative
- silence hangup is on (45s total silence), the wall-clock silence fallback
and max duration cap are off, and the unproductive-turn ceiling is 5 - so
omitting the block preserves prior behavior except for the enabled silence
and unproductive defaults.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `silence_hangup_enabled` | bool | `true` | Master switch for the silence-timeout path. |
| `away_seconds` | float | `15.0` | Seconds of silence before LiveKit's `user_state` flips to `away`. |
| `silence_grace_seconds` | float | `30.0` | Additional seconds the agent waits after `away` before hanging up. |
| `max_call_duration_seconds` | int or null | `null` | Optional ceiling on total call duration in seconds. `null` disables. Must be greater than 0 when set. |
| `absolute_silence_seconds` | int or null | `null` | Optional wall-clock fallback for SIP trunks where comfort noise prevents `user_state` from becoming `away`. Measures time since the last non-empty final user transcript. Suggested production value: `120`. Must be greater than 0 when set. |
| `unproductive_hangup_enabled` | bool | `true` | Master switch for the unproductive-turn ceiling. |
| `unproductive_turn_threshold` | int | `5` | Consecutive unproductive replies before the agent ends. |
| `unproductive_phrases` | list[str] | tuned defaults | Substrings (case-insensitive) that mark a reply as a deflection. |

Examples:

```yaml
# Aggressive silence handling: hang up after 30s total silence.
voice:
  voice_id: "marin"
  idle:
    away_seconds: 10
    silence_grace_seconds: 20
```

```yaml
# Cap every call at 10 minutes.
voice:
  voice_id: "marin"
  idle:
    max_call_duration_seconds: 600
```

```yaml
# Add a wall-clock fallback for muted SIP calls. The normal user_state path
# still runs; this catches trunks that send comfort noise instead of silence.
voice:
  voice_id: "marin"
  idle:
    absolute_silence_seconds: 120
```

```yaml
# Disable the unproductive-turn cap entirely (e.g. for clinics where
# callers commonly need long, exploratory conversations).
voice:
  voice_id: "marin"
  idle:
    unproductive_hangup_enabled: false
```

When the agent hangs up via any of these paths, the call summary records
`outcomes: ["agent_ended"]` and `agent_end_reason: "<silence_timeout |
unproductive_turns_exhausted | max_duration_reached>"`. See
[`function-tools-reference.md#end_call`](function-tools-reference.md#end_call)
for the full vocabulary.

---

### languages

Optional. Multi-language hint for the receptionist. The agent auto-detects
the caller's language at runtime; this block constrains which detections are
acceptable and which language the agent should default to.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `languages.primary` | string | No | `"en"` | ISO-639 code of the agent's default language. |
| `languages.allowed` | list[string] | No | `["en"]` | ISO-639 codes the agent may switch to if the caller speaks one of them. The detected language is appended to call metadata as `languages_detected`. |

If a caller speaks a language not in `allowed`, the agent stays in `primary`
and does not announce the limitation; it just answers normally in the
configured language.

```yaml
languages:
  primary: "en"
  allowed: ["en", "es"]
```

---

### greeting

The first thing the receptionist says when answering the call.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `greeting` | string | Yes | The opening greeting spoken to the caller. |

**Tips**:
- Keep it concise (under 30 words). Callers want to state their purpose quickly.
- Include the business name so the caller knows they reached the right place.
- End with an open question to invite the caller to speak.

```yaml
greeting: "Thank you for calling Springfield Family Law. How can I help you today?"
```

---

### personality

Instructions that shape the receptionist's conversational style and behavior.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `personality` | string | Yes | Multi-line personality and behavior instructions injected into the system prompt. |

This field is passed directly into the LLM system prompt. It should describe:

- Tone and demeanor (warm, professional, casual, formal)
- Speaking style (pace, vocabulary level, use of jargon)
- Behavioral guidelines (patience, empathy, boundaries)
- Business-specific instructions (what to emphasize, what to avoid)

```yaml
personality: |
  You are a professional and empathetic legal receptionist. You speak in a
  calm, reassuring tone. You never offer legal advice or opinions on cases.
  You are careful with confidential information. When unsure about something,
  you offer to have an attorney call the person back rather than guessing.
```

**YAML note**: Use `|` for multi-line strings. This preserves line breaks, which improves readability in the prompt.

---

### hours

Weekly business hours schedule.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `hours` | object | Yes | Contains keys for each day of the week. |
| `hours.<day>` | object or `"closed"` | Yes (all 7 days) | Either an object with `open`/`close` times, or the string `"closed"`. |
| `hours.<day>.open` | string | Yes (if not "closed") | Opening time in `HH:MM` 24-hour format. |
| `hours.<day>.close` | string | Yes (if not "closed") | Closing time in `HH:MM` 24-hour format. |

**Day keys**: `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`

**Time format**: `HH:MM` in 24-hour format. Leading zero required for single-digit hours.

| Time | Format |
|------|--------|
| 8:00 AM | `"08:00"` |
| 12:00 PM | `"12:00"` |
| 5:30 PM | `"17:30"` |
| 9:00 PM | `"21:00"` |
| Midnight | `"00:00"` |

**Validation**: The `DayHours` model validates that `open` and `close` match the `HH:MM` pattern. The system uses lexicographic string comparison for time checks, which works correctly for 24-hour format.

```yaml
hours:
  monday:
    open: "09:00"
    close: "18:00"
  tuesday:
    open: "09:00"
    close: "18:00"
  wednesday:
    open: "09:00"
    close: "18:00"
  thursday:
    open: "09:00"
    close: "20:00"   # Late hours on Thursday
  friday:
    open: "09:00"
    close: "16:00"   # Early close Friday
  saturday:
    open: "10:00"
    close: "14:00"   # Half day Saturday
  sunday: "closed"
```

---

### after_hours_message

Message the receptionist delivers when the business is closed.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `after_hours_message` | string | Yes | What the receptionist should say (or know to say) when a call comes in outside business hours. |

**Tips**:
- Include the regular business hours so the caller knows when to call back.
- Mention emergency alternatives if applicable (911, emergency line).
- Offer to take a message.

```yaml
after_hours_message: |
  Our office is currently closed. Our regular hours are Monday through
  Friday from 9 AM to 6 PM, and Saturday from 10 AM to 2 PM. If you need
  immediate legal assistance, please call the State Bar referral line at
  1-800-555-0199. Otherwise, I'd be happy to take a message and have
  someone return your call on the next business day.
```

---

### routing

Departments or individuals that callers can be transferred to.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `routing` | list | Yes | Array of routing entries. Can be empty `[]` if no transfers are available. |

Each routing entry:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Department or person name (used for matching transfer requests). |
| `number` | string | Yes | Phone number to transfer to (E.164 format recommended). |
| `description` | string | Yes | What this department/person handles. Used in the system prompt to help the AI route correctly. |

**Matching behavior**: When a caller requests a transfer, the `transfer_call` tool performs a case-insensitive match against routing entry names.

```yaml
routing:
  - name: "Sales"
    number: "+15551000001"
    description: "New customer inquiries, pricing, and service packages"
  - name: "Support"
    number: "+15551000002"
    description: "Technical support for existing customers"
  - name: "Dr. Martinez"
    number: "+15551000003"
    description: "Direct line for Dr. Martinez's patients"
```

**No routing available**: If the business does not support call transfers, use an empty list:

```yaml
routing: []
```

---

### faqs

Frequently asked questions and their answers.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `faqs` | list | Yes | Array of FAQ entries. Can be empty `[]`. |

Each FAQ entry:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | string | Yes | The question as it might be asked. Used for substring matching and as context in the system prompt. |
| `answer` | string | Yes | The answer to provide. Should be conversational (this is spoken aloud, not read). |

**Matching behavior**: The `lookup_faq` tool performs case-insensitive substring matching against the question field. If no match is found, it returns a neutral message that tells the LLM to use its system prompt knowledge instead.

**Important**: FAQs are also included in the system prompt itself, so the AI has access to them even without explicitly calling the `lookup_faq` tool. The tool provides a structured lookup mechanism that reinforces accuracy.

```yaml
faqs:
  - question: "What insurance do you accept?"
    answer: "We accept most major insurance plans including Blue Cross, Aetna, Cigna, and United Healthcare. We can verify your specific coverage when you schedule an appointment."

  - question: "How long is a typical consultation?"
    answer: "An initial consultation usually takes about 30 to 45 minutes. Follow-up appointments are typically 15 to 20 minutes."

  - question: "Is there parking available?"
    answer: "Yes, we have free parking in the lot behind our building. There's also metered street parking on Main Street."

  - question: "Do you offer payment plans?"
    answer: "Yes, we offer flexible payment plans for treatments over $500. Our billing department can set that up for you."
```

---

### messages

`messages.channels` is a list of independent delivery destinations. Each
caller message produced by the `take_message` tool fans out to every
configured channel.

```yaml
messages:
  channels:
    - type: "file"
      file_path: "./messages/acme-dental/"
    - type: "email"
      to: ["owner@example.com", "back-office@example.com"]
      include_transcript: true
      include_recording_link: true
    - type: "webhook"
      url: "https://your-app.example.com/api/messages"
      headers:
        Authorization: "Bearer ${SLACK_TOKEN}"
```

#### Dispatch behavior

Within one `dispatch_message` call the dispatcher picks one channel to await
synchronously and runs the rest as background tasks. Preference order is
**file > webhook > email**. The synchronous channel's success is what the
caller-facing tool confirms with "saved"; failures of background channels are
recorded under `.failures/` for later replay.

The `take_message` tool deliberately skips the email channel mid-call (it
passes `skip_email_channel=True` to the dispatcher). The lifecycle queues
the email and fires it at call-end with the freshly-written transcript path,
so the email body can embed the full conversation. File and webhook channels
still fire mid-call.

#### Channel: `type: "file"`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | const `"file"` | Yes | Discriminator. |
| `file_path` | string | Yes | Directory where each message is written as a JSON file. The directory is created if it doesn't exist. |

File naming: `message_YYYYMMDD_HHMMSS_ffffff.json`. The JSON shape:

```json
{
  "caller_name": "Jane Doe",
  "callback_number": "+15551234567",
  "message": "I need to reschedule my appointment for next Tuesday.",
  "business_name": "Acme Dental",
  "timestamp": "2026-03-02T14:30:25.123456+00:00"
}
```

#### Channel: `type: "email"`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | const `"email"` | Yes | — | Discriminator. |
| `to` | list[string] | Yes | — | One or more recipient addresses. |
| `include_transcript` | bool | No | `true` | When true and a markdown transcript exists, the full conversation is embedded at the bottom of every email this channel sends (message email + call-end email + booking email). |
| `include_recording_link` | bool | No | `true` | When true and the call has a recording artifact, the recording URL/path is rendered. Set false for tenants who don't want bucket links in mail. |

The email channel also requires the top-level `email:` block, which holds the
sender configuration and trigger flags. See [`email`](#email) below.

#### Channel: `type: "webhook"`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | const `"webhook"` | Yes | Discriminator. |
| `url` | string | Yes | Public HTTP(S) endpoint to POST the message JSON. Must use `http://` or `https://`; other schemes, localhost, loopback, private, and link-local hosts are rejected at config load. |
| `headers` | dict[string, string] | No | Optional headers added to the POST request. Supports `${VAR}` env-var interpolation. |

The webhook channel sends a JSON POST with the same Message shape shown
under the file channel. Retries follow `WebhookChannel`'s retry policy
(exponential backoff with jitter); persistent failures land in `.failures/`.

---

### email

Top-level email configuration consumed by any `messages.channels[type=email]`
entry and by the call-end / booking email triggers. Omit the whole block if
your config has no email channels and no email triggers.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `from` | string | Yes | — | RFC 5322 From address; typically `"Friendly Name <noreply@example.com>"`. |
| `sender.type` | enum `"smtp"` \| `"resend"` | Yes | — | Backend that actually sends. |
| `sender.smtp` | object | Conditional | — | Required when `sender.type=smtp`. |
| `sender.smtp.host` | string | Yes | — | SMTP server hostname, e.g. `smtp.gmail.com`. |
| `sender.smtp.port` | int | No | `587` | Typically 587 (STARTTLS) or 465 (TLS). |
| `sender.smtp.username` | string | Yes | — | Login username, often the same as the From address. |
| `sender.smtp.password` | string | Yes | — | Password / app password. Use `${VAR}` interpolation; do not paste secrets into YAML. |
| `sender.smtp.use_tls` | bool | No | `true` | STARTTLS on; set false only for self-hosted relays you control. |
| `sender.resend` | object | Conditional | — | Required when `sender.type=resend`. |
| `sender.resend.api_key` | string | Yes | — | Resend API key, typically `${VAR}` interpolated. |
| `triggers.on_message` | bool | No | `true` | Fire an email per `take_message` invocation (deferred to call-end so the transcript is embedded). |
| `triggers.on_call_end` | bool | No | `false` | Fire a call summary email at the end of every call. |
| `triggers.on_booking` | bool | No | `false` | Fire an email when `book_appointment` succeeds (requires `calendar` configured). |

#### SMTP example (Gmail app password)

```yaml
email:
  from: "Receptionist <noreply@acme-dental.example.com>"
  sender:
    type: "smtp"
    smtp:
      host: "smtp.gmail.com"
      port: 587
      username: "noreply@acme-dental.example.com"
      password: ${ACME_DENTAL_SMTP_PASSWORD}
      use_tls: true
  triggers:
    on_message: true
    on_call_end: true
    on_booking: false
```

#### Resend example

```yaml
email:
  from: "Receptionist <noreply@acme-dental.example.com>"
  sender:
    type: "resend"
    resend:
      api_key: ${ACME_DENTAL_RESEND_API_KEY}
  triggers:
    on_message: true
    on_call_end: true
```

---

### recording

Optional. When enabled, calls are recorded via LiveKit Egress and the URL
(or local path) is attached to the call-end email and transcript metadata.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `enabled` | bool | Yes | — | Master switch. Omit `recording:` entirely OR set false to disable. |
| `storage.type` | enum `"local"` \| `"s3"` | Yes | — | Where the recording file lands. **LiveKit Cloud rejects `local`** — use `s3` (or a self-hosted LiveKit). |
| `storage.local.path` | string | Conditional | — | Required when `storage.type=local`. Directory the recording WAV/OGG is written to. Self-hosted LiveKit only. |
| `storage.s3.bucket` | string | Conditional | — | Required when `storage.type=s3`. |
| `storage.s3.region` | string | Conditional | — | AWS region or equivalent. |
| `storage.s3.endpoint_url` | string | No | omitted | S3-compatible endpoint for R2 / B2 / MinIO. Leave unset for AWS S3. |
| `consent_preamble.enabled` | bool | No | `false` | When true, the agent speaks `consent_preamble.text` before the greeting. Two-party-consent jurisdictions usually need this on. |
| `consent_preamble.text` | string | Conditional | — | Required when `consent_preamble.enabled=true`. |

AWS credentials for S3 storage are read from process environment
(`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`) as
LiveKit Egress expects.

```yaml
recording:
  enabled: true
  storage:
    type: "s3"
    s3:
      bucket: "acme-recordings"
      region: "us-east-1"
  consent_preamble:
    enabled: true
    text: "This call may be recorded for quality and training."
```

---

### transcripts

Per-call JSON (source of truth) and Markdown (human-readable) transcripts.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `enabled` | bool | Yes | — | Master switch. |
| `storage.type` | const `"local"` | Yes | — | Only local-disk storage today. |
| `storage.path` | string | Yes | — | Directory both formats are written to. |
| `formats` | list[enum] | No | `["json", "markdown"]` | Subset of `["json", "markdown"]`. The Markdown format is what the email template embeds. |

```yaml
transcripts:
  enabled: true
  storage:
    type: "local"
    path: "./transcripts/acme-dental/"
  formats: ["json", "markdown"]
```

---

### retention

Optional. Background sweeper deletes recordings, transcripts, and messages
older than the configured number of days. Run the sweeper via
`python -m receptionist.retention sweep [--dry-run] [--business <slug>]`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `recordings_days` | int | `90` | Days to keep recording files. `0` keeps forever. |
| `transcripts_days` | int | `90` | Days to keep transcript JSON+Markdown. `0` keeps forever. |
| `messages_days` | int | `0` | Days to keep message JSON files. `0` keeps forever (the typical default — voicemail-style intake is usually retained indefinitely). |

`.failures/` directories are skipped by the sweeper so failed-delivery
records aren't lost while you triage them.

```yaml
retention:
  recordings_days: 90
  transcripts_days: 90
  messages_days: 0
```

---

### sip

Per-business SIP transfer behavior. The whole section is optional;
omitting it gets the default (`tel:{number}`) which works for Twilio,
Telnyx, and most BYOC SIP trunks.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `transfer_uri_template` | string | No | `"tel:{number}"` | URI format string used by `transfer_call`. Must contain the literal `{number}` placeholder. |

**When to override the default:**

- **Asterisk classic `sip.conf` (chan_sip)** rejects tel-URIs. Use
  `sip:{number}` for transfers to local DIDs, or
  `sip:{number}@your-pbx.example.com` for transfers to a remote PBX.
- **Other custom SIP gateways** that need a specific URI form.

The agent substitutes the `routing.*.number` value into `{number}` at
runtime. The validator rejects templates that don't contain `{number}`
(would otherwise silently dial the literal template string).

**Example (Asterisk):**

```yaml
sip:
  transfer_uri_template: "sip:{number}"
```

---

### intakes

Structured new-client intake by phone. Riley walks the caller through a
configurable question script per case type, persists each answer
incrementally, and emails the completed submission at call-end. The whole
section is optional; omitting it disables the intake feature entirely.

For setup steps, Spanish-language handling, and operational guidance see
the [Intake Setup](intakes-setup.md) guide.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `enabled` | bool | No | `false` | Master switch. When `false`, the intake tools are unavailable and the INTAKES prompt section is omitted. |
| `preamble_en` | string | No | `""` | English-language disclosure Riley speaks before starting questions (e.g. "this takes 15-20 minutes, do you have time now?"). |
| `preamble_es` | string | No | `None` | Spanish preamble. If omitted, Riley translates `preamble_en` at call time. |
| `submission.file_path` | string | Yes | — | Directory where partial and final intake JSONs are written. |
| `case_types[*].key` | string | Yes | — | Canonical identifier passed to `record_intake_answer(case_type=...)`. Stable across question rewording. |
| `case_types[*].display_name` | string | Yes | — | Human-readable label used in the intake email subject. |
| `case_types[*].display_name_es` | string | No | `None` | Spanish display name. |
| `case_types[*].google_form_id` | string | No | `None` | Optional, used by the sync CLI only. |
| `case_types[*].questions[*].key` | string | Yes | — | Canonical field name (e.g. `employer`, `accident_date`). Unique within a case type. |
| `case_types[*].questions[*].prompt_en` | string | Yes | — | The English question Riley reads verbatim. |
| `case_types[*].questions[*].prompt_es` | string | No | `None` | Spanish translation. |
| `case_types[*].questions[*].required` | bool | No | `true` | If `false`, Riley may skip the question if the caller declines. |
| `case_types[*].questions[*].validation` | `text`/`phone`/`email`/`date`/`yes_no` | No | `"text"` | Advisory shape hint. Influences prompt phrasing. |
| `case_types[*].questions[*].critical` | bool | No | `false` | If `true`, Riley reads the answer back per-character and waits for explicit confirmation. |

**Validation rules:**

- At least one case type required when the block is present.
- At least one question required per case type.
- `case_types[*].key` must be unique across case types.
- `questions[*].key` must be unique within each case type.

**Example:**

```yaml
intakes:
  enabled: true
  preamble_en: "This intake takes 15-20 minutes. Do you have time now?"
  preamble_es: "Esta entrevista toma 15-20 minutos. ¿Tiene tiempo ahora?"
  submission:
    file_path: "./messages/<slug>/intakes/"
  case_types:
    - key: workers_comp
      display_name: "Workers' Compensation"
      display_name_es: "Compensación por accidentes laborales"
      questions:
        - key: caller_full_name
          prompt_en: "Your full legal name?"
          prompt_es: "¿Su nombre legal completo?"
          required: true
          critical: true
          validation: text
```

---

## Validation Rules

The following validation rules are enforced by the Pydantic models in `config.py`:

| Rule | Field(s) | Error |
|------|----------|-------|
| Required fields present | All required fields | `field required` |
| String type | name, type, timezone, etc. | `value is not a valid string` |
| HH:MM format | hours.*.open, hours.*.close | Custom validation error |
| Valid day values | hours.* | Must be DayHours object or "closed" |
| All 7 days present | hours | All days monday-sunday required |
| Channel type valid | messages.channels[*].type | Must be one of `"file"`, `"email"`, `"webhook"` |
| Email channel requires top-level email config | email | `EmailChannel configured but no EmailConfig provided` |
| SMTP/Resend config matches sender.type | email.sender | `email.sender.smtp required when type is 'smtp'` etc. |
| Webhook URL scheme | messages.channels[type=webhook].url | Must be `http://` or `https://`; other schemes rejected |
| Webhook host safety | messages.channels[type=webhook].url | localhost, loopback, private, and link-local hosts rejected |
| Unknown config keys | All config sections | Extra fields are rejected so typos fail loudly |
| Calendar booking window | calendar.booking_window_days | Must be 1-90 days |
| Recording S3 requires bucket+region | recording.storage.s3 | Required when `storage.type=s3` |
| Consent preamble text required when enabled | recording.consent_preamble | Cross-field validation error |
| Transfer URI template contains `{number}` | sip.transfer_uri_template | Must contain literal `{number}` placeholder |
| Non-empty strings | routing.*.name, routing.*.number, etc. | Must not be empty |
| Config slug format | Runtime slug | Must match `^[a-zA-Z0-9_-]+$` |
| `${VAR}` env-var interpolation | Any string value | Variable must exist in the process env at load time; placeholders must use uppercase/underscore env-var names |
| Intake case type uniqueness | intakes.case_types[*].key | Must be unique across case types |
| Intake question uniqueness | intakes.case_types[*].questions[*].key | Must be unique within each case type |
| Intake requires at least one case type | intakes.case_types | List cannot be empty when intakes block present |
| Intake requires at least one question | intakes.case_types[*].questions | Each case type must define at least one question |

---

## Loading Behavior

### At Agent Startup

1. The agent reads job metadata for a `"config"` key.
2. If found, the slug is validated and used to locate `config/businesses/<slug>.yaml`.
3. If not found, the agent falls back to the first YAML file (alphabetically) in `config/businesses/`.
4. The YAML file is read with UTF-8 encoding and parsed with `yaml.safe_load()`.
5. The parsed data is validated through the `BusinessConfig` Pydantic model.
6. Any validation error halts the agent with a descriptive error message.

### The `from_yaml_string` Classmethod

`BusinessConfig.from_yaml_string(yaml_string)` provides a convenient way to load configuration from a YAML string (useful for testing or dynamic config sources):

```python
config = BusinessConfig.from_yaml_string("""
business:
  name: "Test Business"
  type: "test"
  timezone: "UTC"
# ... rest of config
""")
```

---

## Tips and Best Practices

### Writing Effective Greetings

- Keep under 30 words.
- Always include the business name.
- End with an open-ended question ("How can I help you?").
- Avoid "press 1 for..." language. This is a conversational AI, not an IVR.

### Writing Effective Personalities

- Be specific about tone: "warm and professional" is better than "nice."
- Include behavioral boundaries: "never offer legal advice" or "don't diagnose conditions."
- Mention speaking pace if important for your audience.
- Include industry-specific guidance about what to say and what to avoid.

### Writing Effective FAQs

- Write questions the way callers actually ask them, not formal versions.
- Write answers that sound natural when spoken aloud.
- Keep answers under 3 sentences. The AI can elaborate if asked.
- Cover your top 10-15 most common questions.
- Don't duplicate information that's already in the hours or routing config.

### Choosing a Timezone

- Use the IANA timezone identifier for the business's physical location.
- Do not use abbreviations like "EST" or "PST" — these are ambiguous and do not handle daylight saving time correctly.
- Use `America/New_York` (not `US/Eastern`), `America/Los_Angeles` (not `US/Pacific`), etc.

### Routing Numbers

- Use E.164 format: `+1XXXXXXXXXX` for US numbers.
- Ensure the numbers are reachable from your SIP trunk provider.
- Test each routing number to confirm transfers work before going live.

### Message File Paths

- Use a relative path like `./messages/<slug>/` — it will be relative to the process working directory.
- The directory is created on first write; the process just needs write permissions on the parent.
- For multi-business deployments, use per-business directories: `./messages/acme-dental/`, `./messages/smith-law/`, etc.

### Where to put secrets

- `.env` file in the project root (gitignored) is the canonical home for
  passwords, API keys, and OAuth tokens that the YAML references via
  `${VAR}` interpolation. `.env.example` is safe to commit; it lists the
  variable *names* but never values.
- Per-business OAuth token files live under `secrets/<slug>/openai_auth.json`.
  `secrets/*` is gitignored except `secrets/.gitkeep`.
- Tenant-specific YAML files live at `config/businesses/<slug>.yaml` and are
  gitignored by pattern, with the exception `config/businesses/example-*.yaml`
  which is the only YAML committed to the repo.
