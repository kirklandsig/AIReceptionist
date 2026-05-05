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
  - [greeting](#greeting)
  - [personality](#personality)
  - [hours](#hours)
  - [after_hours_message](#after_hours_message)
  - [routing](#routing)
  - [faqs](#faqs)
  - [messages](#messages)
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
config/businesses/smith-law-firm.yaml
config/businesses/downtown_clinic.yaml
```

**Slug validation**: Must match `^[a-zA-Z0-9_-]+$`. No spaces, no path separators, no special characters. This is enforced for security (path traversal prevention).

---

## Complete Example

```yaml
business:
  name: "Acme Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "coral"

greeting: "Thank you for calling Acme Dental. How can I help you today?"

personality: |
  You are a warm, professional dental office receptionist. You speak clearly
  and at a moderate pace. You are patient with callers and always try to be
  helpful. You use simple language and avoid medical jargon unless the caller
  uses it first.

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

after_hours_message: |
  I'm sorry, but Acme Dental is currently closed. Our regular office hours
  are Monday through Thursday from 8 AM to 5 PM, and Friday from 8 AM to
  3 PM. If this is a dental emergency, please call 911 or go to your nearest
  emergency room. I'd be happy to take a message and have someone call you
  back during business hours.

routing:
  - name: "Scheduling"
    number: "+15551234001"
    description: "Book, change, or cancel appointments"
  - name: "Billing"
    number: "+15551234002"
    description: "Insurance, payments, and billing questions"
  - name: "Clinical"
    number: "+15551234003"
    description: "Speak with a dental assistant about treatment questions"

faqs:
  - question: "What insurance do you accept?"
    answer: "We accept most major dental insurance plans including Delta Dental, Cigna, Aetna, MetLife, and United Healthcare. We also offer a discount for patients paying out of pocket."
  - question: "Where are you located?"
    answer: "We are located at 123 Main Street, Suite 200, Springfield. We're in the medical plaza next to Springfield General Hospital."
  - question: "Do you accept new patients?"
    answer: "Yes, we are currently accepting new patients! We'd love to schedule your first visit."
  - question: "What is your cancellation policy?"
    answer: "We ask that you give us at least 24 hours notice if you need to cancel or reschedule your appointment."

messages:
  delivery: "file"
  file_path: "messages/"
```

---

## Field Reference

### business

Business identity information.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | The full business name as it should be spoken. Used in the system prompt and message records. |
| `type` | string | Yes | The type of business (e.g., "dental office", "law firm", "medical clinic"). Used in the system prompt to establish context. |
| `timezone` | string | Yes | IANA timezone identifier for the business location. Used by `get_business_hours` for accurate time calculations. |

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

##### Codex OAuth auth

Use the Codex CLI / ChatGPT-login OAuth access token. The agent reads
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

`voice.idle` configures three independent safety nets so the agent doesn't
hold a SIP and Realtime session open indefinitely. Defaults are conservative
— silence hangup is on (45s total silence), max duration is off, and the
unproductive-turn ceiling is 5 — so omitting the block preserves the
prior behavior for the silence and unproductive paths and disables the
duration cap.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `silence_hangup_enabled` | bool | `true` | Master switch for the silence-timeout path. |
| `away_seconds` | float | `15.0` | Seconds of silence before LiveKit's `user_state` flips to `away`. |
| `silence_grace_seconds` | float | `30.0` | Additional seconds the agent waits after `away` before hanging up. |
| `max_call_duration_seconds` | int or null | `null` | Optional ceiling on total call duration in seconds. `null` disables. Must be greater than 0 when set. |
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

Configuration for how caller messages are stored and delivered.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `messages` | object | Yes | Message delivery configuration. |
| `messages.delivery` | string | Yes | Delivery method: `"file"` or `"webhook"`. |
| `messages.file_path` | string | Conditional | Directory path for file-based message storage. **Required when delivery is `"file"`**. |
| `messages.webhook_url` | string | Conditional | URL endpoint for webhook delivery. **Required when delivery is `"webhook"`**. |

#### File Delivery

Messages are saved as individual JSON files in the specified directory:

```yaml
messages:
  delivery: "file"
  file_path: "messages/"
```

File naming: `message_YYYYMMDD_HHMMSS_ffffff.json` (microsecond precision to avoid collisions).

File content:
```json
{
  "caller_name": "John Smith",
  "callback_number": "555-123-4567",
  "message": "I need to reschedule my appointment for next Tuesday.",
  "business_name": "Acme Dental",
  "timestamp": "2026-03-02T14:30:25.123456+00:00"
}
```

#### Webhook Delivery (Planned)

```yaml
messages:
  delivery: "webhook"
  webhook_url: "https://your-app.com/api/messages"
```

**Note**: Webhook delivery is defined in the configuration schema but the implementation currently raises `NotImplementedError`. This is planned for a future release.

#### Cross-Field Validation

The `MessagesConfig` model enforces these rules:

- If `delivery` is `"file"`, then `file_path` must be provided.
- If `delivery` is `"webhook"`, then `webhook_url` must be provided.
- Providing mismatched fields (e.g., `delivery: "file"` with only `webhook_url`) will raise a validation error.

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

## Validation Rules

The following validation rules are enforced by the Pydantic models in `config.py`:

| Rule | Field(s) | Error |
|------|----------|-------|
| Required fields present | All required fields | `field required` |
| String type | name, type, timezone, etc. | `value is not a valid string` |
| HH:MM format | hours.*.open, hours.*.close | Custom validation error |
| Valid day values | hours.* | Must be DayHours object or "closed" |
| All 7 days present | hours | All days monday-sunday required |
| Delivery method valid | messages.delivery | Must be "file" or "webhook" |
| file_path required for file delivery | messages.file_path | Cross-field validation error |
| webhook_url required for webhook delivery | messages.webhook_url | Cross-field validation error |
| Non-empty strings | routing.*.name, routing.*.number, etc. | Must not be empty |
| Config slug format | Runtime slug | Must match `^[a-zA-Z0-9_-]+$` |

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

- Use a relative path like `messages/` — it will be relative to the project root.
- Ensure the directory exists and the process has write permissions.
- For multi-business setups, consider per-business directories: `messages/acme-dental/`.
