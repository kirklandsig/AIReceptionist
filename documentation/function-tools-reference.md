# Function Tools Reference

This document provides a detailed reference for each function tool exposed by the Receptionist agent to the OpenAI Realtime model. These tools are the mechanisms through which the AI takes actions during a phone call.

---

## Table of Contents

- [Overview](#overview)
- [How Function Tools Work](#how-function-tools-work)
- [lookup_faq](#lookup_faq)
- [transfer_call](#transfer_call)
- [take_message](#take_message)
- [get_business_hours](#get_business_hours)
- [check_availability](#check_availability)
- [book_appointment](#book_appointment)
- [record_intake_answer](#record_intake_answer)
- [finalize_intake](#finalize_intake)
- [send_info_packet](#send_info_packet)
- [end_call](#end_call)
- [Tool Interaction Patterns](#tool-interaction-patterns)
- [Error Handling](#error-handling)
- [Extending the Tool Set](#extending-the-tool-set)

---

## Overview

The Receptionist agent exposes the following function tools to the OpenAI Realtime model. Calendar tools are always registered but only respond meaningfully when `calendar.enabled: true`; intake tools are always registered but only respond meaningfully when `intakes.enabled: true`:

| Tool | Purpose | Triggers |
|------|---------|----------|
| `lookup_faq` | Search configured FAQs for an answer | Caller asks a question about the business |
| `transfer_call` | Transfer the call to a department/person | Caller requests to speak with someone specific |
| `take_message` | Record a message from the caller | Caller wants to leave a message |
| `get_business_hours` | Check current open/closed status | Caller asks about business hours |
| `check_availability` | Find calendar slots near a caller-requested time | Caller wants to book an appointment |
| `book_appointment` | Book a specific previously-offered slot | Caller confirms a time |
| `record_intake_answer` | Record one answer in an in-progress intake | Caller is going through a structured intake |
| `finalize_intake` | Submit the completed intake | Riley has captured all required answers and confirmed critical fields |
| `send_info_packet` | Email a configured information packet to the caller (two-step: first call returns the address for read-back, second call with `destination_confirmed=true` sends) | Caller consented and confirmed an email address |
| `end_call` | Say goodbye and hang up | Caller has clearly finished the conversation |

These tools are defined as methods on the `Receptionist` class in `agent.py`, decorated with `@function_tool()`. The LiveKit Agents SDK and OpenAI Realtime API handle the serialization, invocation, and result passing automatically.

---

## How Function Tools Work

### Architecture

```
Caller speaks → OpenAI Realtime API (understands intent)
                       │
                       ▼
              Model decides to call a tool
                       │
                       ▼
              Tool call sent to agent
                       │
                       ▼
              Agent executes tool method
                       │
                       ▼
              Result returned to model
                       │
                       ▼
              Model speaks the response to caller
```

### Lifecycle

1. The caller says something that requires an action (e.g., "Can I leave a message?").
2. The OpenAI Realtime model determines that a tool call is appropriate.
3. The model generates a tool call with the tool name and arguments.
4. The LiveKit Agents SDK routes the call to the corresponding method on the `Receptionist` class.
5. The method executes and returns a string result.
6. The result is sent back to the model.
7. The model incorporates the result into its next spoken response.

### Tool Definitions

Tools are defined as async methods with the `@function_tool()` decorator. The method signature defines the parameters, and the docstring defines the tool description sent to the model:

```python
@function_tool()
async def my_tool(self, param: str) -> str:
    """Description used by the model to decide when to call this tool.

    Args:
        param: Description of the parameter.
    """
    return "result string"
```

---

## lookup_faq

### Purpose

Searches the business's configured FAQ entries for an answer to the caller's question. Provides structured knowledge retrieval to supplement the LLM's system prompt knowledge.

### Signature

```python
@function_tool()
async def lookup_faq(self, question: str) -> str
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | str | Yes | The caller's question or a rephrased version of it. |

### Return Value

- **Match found**: Returns the answer from the matching FAQ entry.
- **No match**: Returns a neutral message such as "I don't have a specific FAQ entry for that question. Let me see if I can help based on what I know." This message is designed to prompt the LLM to fall back to its system prompt knowledge rather than simply saying "I don't know."

### Matching Algorithm

The tool performs **case-insensitive substring matching** against the `question` field of each FAQ entry in the configuration:

```python
# Pseudocode
query = question.lower()
for faq in config.faqs:
    if query in faq.question.lower():
        return faq.answer
return "no specific FAQ match" message
```

### Matching Behavior

| Caller Question | FAQ Question | Match? |
|----------------|-------------|--------|
| "Do you take insurance?" | "What insurance do you accept?" | Yes ("insurance" substring) |
| "Where is your office?" | "Where are you located?" | Yes ("where" substring) |
| "What are your prices?" | "Do you accept new patients?" | No |

### Design Notes

- **Substring matching was chosen over semantic search** for simplicity and determinism. It works well for the typical 10-20 FAQ entries a small business has.
- **FAQs are also embedded in the system prompt**, so the LLM has access to this knowledge even without calling the tool. The tool provides a structured retrieval mechanism that reinforces accuracy.
- **The "no match" response is deliberately neutral** — it does not say "I don't know" because the LLM may actually know the answer from its system prompt.

### Example Interaction

```
Caller: "What kind of insurance do you guys take?"

→ Model calls: lookup_faq(question="what insurance do you accept")
← Tool returns: "We accept most major dental insurance plans including
   Delta Dental, Cigna, Aetna, MetLife, and United Healthcare. We also
   offer a discount for patients paying out of pocket."

Agent speaks: "We accept most major dental insurance plans including
Delta Dental, Cigna, Aetna, MetLife, and United Healthcare. If you're
paying out of pocket, we do offer a discount as well."
```

---

## transfer_call

### Purpose

Transfers the active phone call to a specific department or person by initiating a SIP transfer through the LiveKit API.

### Signature

```python
@function_tool()
async def transfer_call(self, department: str) -> str
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `department` | str | Yes | The name of the department or person to transfer to. |

### Return Value

- **Success**: Returns a confirmation message (e.g., "Transferring you to Scheduling now.").
- **Department not found**: Returns a message indicating the department was not recognized, along with available options.
- **Transfer failure**: Returns a sanitized error message (no internal details exposed).

### Transfer Process

1. The tool receives the department name.
2. It performs a **case-insensitive match** against the `name` field of each routing entry in the configuration.
3. If a match is found:
   a. The agent announces the transfer to the caller (e.g., "Let me transfer you to Scheduling.").
   b. The agent calls the LiveKit SIP transfer API with the matched phone number.
   c. The matched routing entry name is recorded on call metadata as the transfer target.
   d. The SIP transfer is initiated (the caller is connected to the target number).
4. If no match is found, the tool returns available departments.

Successful transfer targets appear in call-end artifacts: the email subject,
HTML email body, plain-text email body, Markdown transcript header, and JSON
metadata all identify the matched routing entry name.

### Matching Behavior

| Caller Request | Routing Entry Name | Match? |
|---------------|-------------------|--------|
| "scheduling" | "Scheduling" | Yes (case-insensitive) |
| "BILLING" | "Billing" | Yes (case-insensitive) |
| "accounts" | "Billing" | No (not a substring match) |
| "Dr. Smith" | "Dr. Smith" | Yes (case-insensitive) |

### LiveKit SIP Transfer

The actual transfer is performed using the LiveKit API. The agent calls into LiveKit's SIP transfer endpoint, which instructs the SIP gateway to perform a REFER or re-INVITE to the target phone number.

```python
# Simplified pseudocode
participant = self._get_caller_identity()
uri = config.sip.transfer_uri_template.format(number=target.number)
await livekit_api.sip_transfer(participant, transfer_to=uri)
```

### Transfer URI scheme (`sip.transfer_uri_template`)

The format of the `transfer_to` URI is configurable per-business via the
`sip.transfer_uri_template` field, with `{number}` substituted at runtime.
The default — `tel:{number}` — works for Twilio, Telnyx, and most BYOC
SIP trunks that translate tel-URIs into routable SIP requests.

If your trunk is **Asterisk classic `sip.conf`** (chan_sip), it strictly
requires a `sip:` URI and rejects tel-URIs. Set the template to
`sip:{number}` for local DID transfers, or `sip:{number}@your-pbx.example.com`
for transfers to a remote PBX. See `documentation/configuration-reference.md`
for the full schema.

### Error Handling

- **SIP transfer failures** (network issues, invalid numbers, etc.) are caught and returned as sanitized messages. The caller hears something like "I'm sorry, I wasn't able to complete the transfer. Would you like to try again or leave a message?" — never a stack trace or internal error code.
- **No routing entries configured**: If the business has an empty routing list, the system prompt instructs the LLM not to offer transfers.
- **Intake-only mode**: If `agent.mode: intake_only`, `transfer_call` refuses
  before any SIP action and instructs Riley to take a callback message instead.

### Caller Identity

The `_get_caller_identity()` helper method finds the SIP participant in the LiveKit room by `ParticipantKind.PARTICIPANT_KIND_SIP`. In a typical SIP call, that remote participant is the caller. CallerID display is resolved separately from SIP participant metadata, including `sip.phoneNumber` and BYOC/Asterisk-style `sip_<digits>` identities.

### Example Interaction

```
Caller: "Can you transfer me to billing?"

→ Model calls: transfer_call(department="billing")
  → Agent announces: "Let me transfer you to our billing department."
  → Agent initiates SIP transfer to +15551234002
← Tool returns: "Transferring you to Billing now."

[Call is transferred to the billing department]
```

### Example: Department Not Found

```
Caller: "Can I speak to the IT department?"

→ Model calls: transfer_call(department="IT")
← Tool returns: "I don't have a transfer option for IT. I can
   transfer you to Scheduling, Billing, or Clinical. Which would
   you prefer?"

Agent speaks: "I'm sorry, I don't have a direct line for IT.
I can transfer you to Scheduling, Billing, or Clinical.
Would any of those help?"
```

### Notes

`transfer_call` delegates SIP transfer logic to an internal
`_execute_transfer` helper. The DTMF auto-attendant handler (issue #16) also
uses that helper, so the intake-only refusal and SIP API failure paths behave
identically whether the transfer was triggered by the LLM tool or by a keypad
press. Public tool behavior is unchanged.

---

## take_message

### Purpose

Records a message from the caller, including their name, callback number, and the message content. The message is persisted according to the business's configured delivery method.

### Signature

```python
@function_tool()
async def take_message(self, caller_name: str, message: str, callback_number: str) -> str
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `caller_name` | str | Yes | The caller's name. |
| `message` | str | Yes | The message the caller wants to leave. |
| `callback_number` | str | Yes | The phone number to call back. |

### Return Value

Returns a confirmation message (e.g., "Your message has been recorded. Someone will call you back as soon as possible.").

### Message Storage Process

1. A `Message` dataclass is created with:
   - `caller_name`: From the tool parameter.
   - `callback_number`: From the tool parameter.
   - `message`: From the tool parameter.
   - `business_name`: From the loaded business configuration.
   - `timestamp`: Automatically set to current UTC time.

2. The per-call `Dispatcher` sends the message through `messages.channels`.

3. File and webhook channels run immediately so the caller only hears success after the message is durable or posted. Email channels are deferred until call end so the final transcript path is available and the transcript can be attached. When `email.triggers.on_call_end` is **true** (consolidated mode), the captured message content rides in the single call-end email and no separate per-message email fires. When `on_call_end` is **false** (legacy mode), a separate message email fires at call-end when `triggers.on_message` is true.

### File Storage Details

**File naming**: `message_YYYYMMDD_HHMMSS_ffffff_<random>.json`
- Format uses UTC timestamp plus a short random suffix to avoid collisions.
- Example: `message_20260302_143025_123456_a1b2c3d4.json`

**File content**:
```json
{
  "caller_name": "Jane Doe",
  "callback_number": "555-867-5309",
  "message": "I need to reschedule my appointment for next Tuesday. Please call me back when you get a chance.",
  "business_name": "Acme Dental",
  "timestamp": "2026-03-02T14:30:25.123456+00:00"
}
```

### Async I/O

The file channel performs disk writes through `asyncio.to_thread()` so file I/O does not block the event loop. This is critical because:

- The event loop handles real-time audio processing.
- Blocking the loop would cause audio glitches or dropped frames.
- `to_thread()` delegates the file write to a thread pool worker.

### Example Interaction

```
Caller: "Can I leave a message? This is John Smith, my number is
555-123-4567, and I need to cancel my appointment tomorrow."

→ Model calls: take_message(
    caller_name="John Smith",
    message="Needs to cancel appointment tomorrow",
    callback_number="555-123-4567"
  )
← Tool returns: "Your message has been recorded. Someone from
   Acme Dental will call you back as soon as possible."

Agent speaks: "I've taken down your message, John. Someone from
our office will call you back at 555-123-4567 as soon as possible.
Is there anything else I can help with?"
```

### Edge Cases

- **Caller won't give their name**: The LLM will pass whatever the caller provides. If the caller refuses, the LLM may pass "Anonymous" or ask again depending on the personality instructions.
- **Callback number format**: The tool accepts any string. Phone number validation is not enforced — the LLM typically captures what the caller says naturally (e.g., "555-123-4567").
- **Long messages**: No length limit is enforced. The LLM naturally summarizes long caller messages into the `message` parameter.

---

## get_business_hours

### Purpose

Returns the current open/closed status of the business and the full weekly schedule, using the business's configured timezone for accurate time calculations.

### Signature

```python
@function_tool()
async def get_business_hours(self) -> str
```

### Parameters

None. This tool takes no parameters — it uses the business configuration and current time.

### Return Value

Returns a formatted string containing:
1. Current open/closed status.
2. If open: today's closing time.
3. If closed: when the business next opens.
4. Full weekly schedule.

### Timezone Handling

The tool uses Python's `zoneinfo` module (standard library in Python 3.9+) to determine the current time in the business's configured timezone:

```python
from zoneinfo import ZoneInfo
from datetime import datetime

tz = ZoneInfo(config.business.timezone)  # e.g., "America/New_York"
now = datetime.now(tz)
current_day = now.strftime("%A").lower()  # e.g., "monday"
current_time = now.strftime("%H:%M")      # e.g., "14:30"
```

### Open/Closed Determination

The tool uses **lexicographic string comparison** on HH:MM formatted times:

```python
day_hours = getattr(config.hours, current_day)

if day_hours is None:
    # Business is closed today
    status = "closed"
elif day_hours.open <= current_time <= day_hours.close:
    # Business is currently open
    status = "open"
else:
    # Outside of today's hours
    status = "closed"
```

**Why lexicographic comparison works**: In HH:MM 24-hour format, string comparison produces the correct temporal ordering. `"08:00" < "14:30" < "17:00"` is both alphabetically and temporally true.

### Example Returns

**When open**:
```
Acme Dental is currently OPEN.
Today's hours: 8:00 AM to 5:00 PM (Eastern Time)

Weekly schedule:
  Monday:    8:00 AM - 5:00 PM
  Tuesday:   8:00 AM - 5:00 PM
  Wednesday: 8:00 AM - 5:00 PM
  Thursday:  8:00 AM - 5:00 PM
  Friday:    8:00 AM - 3:00 PM
  Saturday:  Closed
  Sunday:    Closed
```

**When closed (after hours)**:
```
Acme Dental is currently CLOSED.
We reopen Monday at 8:00 AM (Eastern Time)

Weekly schedule:
  Monday:    8:00 AM - 5:00 PM
  Tuesday:   8:00 AM - 5:00 PM
  ...
```

### Example Interaction

```
Caller: "What time do you close today?"

→ Model calls: get_business_hours()
← Tool returns: "Acme Dental is currently OPEN. Today's hours:
   8:00 AM to 5:00 PM (Eastern Time). [full schedule]"

Agent speaks: "We're currently open! Today we're here until
5 PM Eastern. Would you like to schedule an appointment?"
```

### Edge Cases

- **Timezone not found**: If the configured timezone is invalid, `ZoneInfo` will raise an exception. This is caught during config validation.
- **Daylight Saving Time**: `zoneinfo` handles DST transitions automatically. The tool always reports the correct local time.
- **Midnight crossing**: The current implementation assumes business hours do not cross midnight (e.g., no "22:00 to 02:00" schedules). This is a reasonable constraint for most small businesses.

---

## end_call

### Purpose

Ends the call after a brief goodbye when the caller has clearly finished the conversation. Issue #10 added this so businesses don't pay for SIP and Realtime time when the caller has said goodbye but stayed on the line.

### Signature

```python
@function_tool()
async def end_call(self, ctx: RunContext, reason: str = "caller_goodbye") -> str
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reason` | str | No (default `caller_goodbye`) | Short label recording *why* the agent ended the call. Must be one of `caller_goodbye`, `silence_timeout`, `unproductive_turns_exhausted`, `max_duration_reached`. Any other value is silently replaced with `caller_goodbye` so the metadata field stays a closed vocabulary. The non-default reasons are typically not invoked from the LLM directly - they are recorded by the silence/duration/unproductive watchers configured under [`voice.idle`](configuration-reference.md#voiceidle-issue-11-safety-nets), including the optional absolute silence fallback. |

### Return Value

A short string the LLM uses as the tool response (e.g. `"Agent ending the call (reason=caller_goodbye)."`). The actual goodbye sentence is generated and spoken via a parallel `generate_reply` call, so the caller hears a natural goodbye even though the tool itself returns immediately.

### When to Call (Prompt Guidance)

The system prompt instructs the LLM:
- DO call when the caller says "goodbye", "thanks, bye", "that's all I needed", or you've already said you can't help and they have nothing else.
- DO NOT call just because the caller is quiet for a moment, mid-question, or asking for something you haven't tried yet.
- NEVER call as the very first reply to a caller; greet them and let them state their need first.

### Hangup Sequence

1. The tool records the `agent_ended` outcome and `agent_end_reason` on the call lifecycle **first** so even if the hangup races the LiveKit close event, the call summary already shows agent-ended with the reason.
2. The tool schedules a background task that calls `ctx.session.generate_reply(...)` with goodbye instructions and stores the resulting `SpeechHandle`.
3. That background task finalizes `lifecycle.on_call_ended()` immediately, before waiting for goodbye playout. This keeps transcript writing, deferred message emails, and call-end emails ahead of LiveKit job teardown even if the caller hangs up during the goodbye.
4. The task then awaits `handle.wait_for_playout()` (with a 10-second hard timeout so a stuck TTS never wedges the call open), then calls the module-level `_terminate_room` helper.
5. The tool returns a short string immediately so the LLM doesn't block its own turn.

`_terminate_room` prefers SIP BYE via `RoomService.remove_participant`, which drops just the caller and leaves the agent's close handler to fire normally. If `remove_participant` fails (token missing `room_admin`, participant already gone), it falls back to `RoomService.delete_room`, which closes the entire room and triggers the participant-disconnect close path. If even `delete_room` fails, the error is logged and the close handler eventually fires from natural disconnect.

### Tracking on the Call Summary

When `end_call` succeeds, the call summary records:
- `outcomes`: includes `"agent_ended"` (in addition to any other outcomes from the same call, e.g. `"transferred"` if the caller was transferred earlier in the same session).
- `agent_end_reason`: short label, rendered in the call-end email subject (`Agent ended`), the call-end email body (`Agent end reason: caller_goodbye`), the HTML email row (`Agent end reason | caller_goodbye`), and the Markdown transcript header.

### Example Interaction

```
Caller: "Great, thanks for your help. Goodbye!"

→ Model calls: end_call(reason="caller_goodbye")
  → Agent says: "Thanks for calling, have a great day!"
  → Background task finalizes call artifacts/emails, waits for playout, then sends SIP BYE to caller
← Tool returns: "Agent ending the call (reason=caller_goodbye)."

[Call disconnects.]
```

### Negative Example (LLM Restraint)

```
Caller: [pauses for 4 seconds]

# Model should NOT call end_call here. The caller is just thinking.
# Issue #11 adds explicit silence-timeout paths so the agent can end
# the call when the caller has been quiet long enough that they've
# clearly walked away, including a wall-clock fallback for SIP comfort noise.
```

---

## record_intake_answer

### Purpose

Record one answer in an in-progress structured intake. Available when the
business has an `intakes:` block with `enabled: true`. Called once per
answered question; the partial intake is persisted to disk and queued for
call-end email after every call so a mid-call disconnect still leaves a
structured record on the receiving team's side.

### Signature

```python
@function_tool()
async def record_intake_answer(
    self, ctx: RunContext,
    case_type: str,
    question_key: str,
    spoken_text: str,
    language: str = "en",
    english_summary: str = "",
) -> str
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `case_type` | str | Yes | Case-type key from the configured `intakes.case_types` (e.g. `"workers_comp"`). |
| `question_key` | str | Yes | Question key from that case type's `questions` list. |
| `spoken_text` | str | Yes | Caller's answer verbatim, in the language they used. Not translated. |
| `language` | str | No | ISO 639-1 code of `spoken_text`. Defaults to `"en"`. |
| `english_summary` | str | No | Concise English rendering of the answer for English-only readers. For English calls this may equal `spoken_text`. |

### Return Value

Short confirmation string ("Answer recorded for `<key>`. Proceed to the next question.") or a structured error string when `case_type` / `question_key` is unknown.

### Side Effects

1. Updates in-memory intake state on the `Receptionist` instance.
2. Writes (or overwrites) a partial JSON file at
   `intakes.submission.file_path/intake_<call_id>.partial.json`.
3. Queues the latest partial submission for the call-end intake email. If
   `finalize_intake` runs later, the final submission replaces the partial.
4. Logs the action via the structured `receptionist` logger.

### Validation

- If `intakes` is missing or `enabled: false`, returns a friendly error
  instructing the LLM to use `take_message` instead.
- If `case_type` is not in `intakes.case_types`, returns an error listing
  the valid keys.
- If `question_key` is not in that case type's `questions`, returns an
  error listing the valid question keys.
- If the caller switched case type mid-call (rare but possible), prior
  in-memory answers are cleared so cross-case-type answer sets don't mix.
- `spoken_text` and `english_summary` are truncated at 4000 and 2000
  characters respectively via the existing `_cap` mechanism.

---

## finalize_intake

### Purpose

Promote the in-progress intake to a final submission. Called exactly once
at the end of an intake, after every required question has been answered
and Riley has confirmed the critical fields with the caller.

### Signature

```python
@function_tool()
async def finalize_intake(
    self, ctx: RunContext,
    caller_name: str,
    callback_number: str,
    english_overview: str = "",
) -> str
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `caller_name` | str | Yes | Caller's full legal name, after Riley read it back letter-by-letter and the caller confirmed. |
| `callback_number` | str | Yes | Callback phone number, after Riley read it back digit-by-digit and the caller confirmed. |
| `english_overview` | str | No | 1–3 sentence English summary of the case in the caller's own framing. Helps the intake team triage without reading every answer. |

### Return Value

Short confirmation string the LLM uses to wrap up the call.

### Side Effects

1. Writes a final JSON file at
   `intakes.submission.file_path/intake_<ts>_<call_id>.final.json`.
2. Removes the partial JSON file (best-effort; leftover partials log a
   warning but don't fail the tool).
3. Queues the intake submission for email at call-end via the lifecycle.
4. Records the `intake_submitted` outcome on `CallMetadata.outcomes`.

### Error Paths

- If `intakes` is disabled or no answers have been recorded yet, returns
  an error string and does NOT write a final file.
- If the final-file write fails, returns a fallback prompt suggesting
  `take_message` instead; the partial file remains on disk for the
  receiving team.

When `info_packets.enabled: true`, the success string also tells Riley to ask
whether the caller wants an approved packet emailed. Riley must call
`send_info_packet` only after permission and the destination email are
confirmed.

---

## send_info_packet

### Purpose

Send a configured, pre-approved information packet to a caller by email. This
tool is consent-gated AND destination-gated. Riley must ask permission first;
beyond that, the tool enforces a two-step destination confirmation (mirroring
the check-before-book pattern used for calendar slots):

1. **First call** — Riley passes the spelled address with
   `consent_confirmed=true`. The tool does NOT send. It stores the parsed
   address and returns an instruction to read that exact address back to the
   caller letter by letter.
2. **Second call** — only after the caller explicitly confirms, Riley calls
   again with the same `destination` and `destination_confirmed=true`. The
   send happens only when the confirmed address matches the stored pending
   address (case-insensitive). A mismatched or out-of-the-blue confirmation
   re-issues the read-back instruction instead of sending.

V1 supports email only and configured text/links only; no SMS, attachments,
or model-generated packet copy are sent.

### Signature

```python
@function_tool()
async def send_info_packet(
    self, ctx: RunContext,
    packet_key: str,
    channel: str = "email",
    destination: str = "",
    consent_confirmed: bool = False,
    destination_confirmed: bool = False,
) -> str
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `packet_key` | str | Yes | Key from `info_packets.packets[*].key`. |
| `channel` | str | No | Must be `"email"` in v1. Other values are refused. |
| `destination` | str | Yes | Caller-confirmed email address. |
| `consent_confirmed` | bool | Yes | Must be `true` only after the caller gives permission to send the packet. Passed on the first call, before the address read-back. |
| `destination_confirmed` | bool | No (default `false`) | Must be `true` only on the second call, after the caller heard the read-back of the exact address the tool returned and explicitly confirmed it. |

### Return Value

- First call (or confirmation for a different address): a read-back
  instruction — "Do not send yet. Read this email address back to the caller
  letter by letter exactly as written: `<destination>`. After the caller
  explicitly confirms it is correct, call send_info_packet again with the
  same destination and destination_confirmed=true. ..." No email is sent.
- Success (second call, matching address): confirms the packet was sent to
  the destination address. The pending address is cleared, so a third call
  with a stale `destination_confirmed=true` restarts the read-back instead
  of sending a duplicate.
- No consent: tells Riley to ask permission and confirm the address first.
- Unsupported channel: refuses and states email is the only supported channel.
- Unknown packet or invalid email: returns a safe corrective instruction.
- Transport failure: logs the full exception and tells Riley the office will
  follow up. The pending address is kept, so a retry with the same confirmed
  address attempts the send again.

### Side Effects

1. Builds the email from `info_packets.packets[*].email_subject`,
   `email_body`, and configured links.
2. Sends through the existing top-level `email.sender` transport with retry.
3. Records success or transport failure on `CallMetadata.info_packet_sends`.
4. Call-end summary emails include packet name, channel, destination, and
   status.

---

## Tool Interaction Patterns

### Sequential Tool Calls

The model may call multiple tools in sequence during a single conversation turn:

```
Caller: "Are you open, and can I speak to someone about insurance?"

→ Model calls: get_business_hours()
← Returns: "Currently OPEN, closes at 5 PM"

→ Model calls: lookup_faq(question="insurance")
← Returns: "We accept Delta Dental, Cigna, ..."

Agent speaks: "Yes, we're open until 5 PM today. Regarding insurance,
we accept Delta Dental, Cigna, Aetna, and several other major plans.
Would you like me to transfer you to our billing department for
specific coverage questions?"
```

### Tool Call After Conversational Context

The model gathers information conversationally before calling a tool:

```
Agent: "I'd be happy to take a message. May I have your name?"
Caller: "It's Sarah Johnson."
Agent: "And what's the best number to reach you?"
Caller: "555-987-6543"
Agent: "What message would you like to leave?"
Caller: "I need to reschedule my cleaning for next week."

→ Model calls: take_message(
    caller_name="Sarah Johnson",
    callback_number="555-987-6543",
    message="Needs to reschedule cleaning for next week"
  )
```

### Tool Call Declined

The model may decide not to call a tool even when one seems relevant, relying on system prompt knowledge instead:

```
Caller: "Do you do teeth whitening?"

# The model may answer from its system prompt knowledge about the
# dental office without calling lookup_faq, if the personality
# instructions or FAQ content in the prompt already covers this.
```

---

## Error Handling

### General Principles

1. **Sanitize all error messages**: Never expose internal details (file paths, stack traces, API errors) to the caller.
2. **Provide helpful alternatives**: When a tool fails, suggest what the caller can do instead.
3. **Log full errors internally**: While the caller gets a sanitized message, the full error is logged for debugging.

### Per-Tool Error Behavior

| Tool | Error Scenario | Caller Hears |
|------|---------------|-------------|
| `lookup_faq` | No match found | LLM falls back to system prompt knowledge |
| `transfer_call` | Department not found | Available departments listed |
| `transfer_call` | `agent.mode: intake_only` | Cannot transfer from this intake line; take a message for callback |
| `transfer_call` | SIP transfer fails | Apology + offer to take a message instead |
| `take_message` | File write fails | Apology + ask to try again |
| `get_business_hours` | Config error | General hours from system prompt |
| `send_info_packet` | Missing consent | Ask permission and confirm the email address before sending |
| `send_info_packet` | Destination not yet confirmed (first call, mismatched address, or stale confirmation) | Read the parsed address back letter by letter, then call again with `destination_confirmed=true` |
| `send_info_packet` | Unsupported channel or invalid email | Email-only / ask caller to spell the address again |
| `send_info_packet` | Email transport fails | Generic follow-up message; full error logged internally |
| `end_call` | `remove_participant` fails | Falls back to `delete_room`; caller is disconnected either way |
| `end_call` | `delete_room` also fails | Logged; close handler fires on natural disconnect (caller eventually drops) |

---

## Extending the Tool Set

To add a new function tool, follow the pattern established by the existing four. See the [Development Guide](development-guide.md#adding-a-new-function-tool) for step-by-step instructions.

### Planned Future Tools

| Tool | Purpose | Status |
|------|---------|--------|
| `check_appointment` | Look up caller's existing appointments | Planned |
| `schedule_appointment` | Book a new appointment | Planned |
| `get_wait_time` | Estimate current hold/wait times | Planned |
| `escalate_to_human` | Connect to a live operator | Planned |

These would require additional integrations (calendar API, queue system, etc.) beyond the current scope.
