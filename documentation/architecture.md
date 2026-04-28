# Architecture

## Overview

AIReceptionist is a voice-based phone receptionist built on **OpenAI Realtime API** (speech-to-speech) and **LiveKit Agents SDK**. This document describes the internal architecture after the 2026-04-23 Call Artifacts and Delivery refactor.

## Package layout

```
receptionist/
├── agent.py                 Thin session orchestrator
├── config.py                Pydantic v2 models, YAML loader, env-var interpolation
├── prompts.py               System prompt builder (includes LANGUAGE block)
├── lifecycle.py             CallLifecycle: per-call metadata owner, close-event fan-out
│
├── booking/                 Google Calendar integration (NEW)
│   ├── models.py            SlotProposal, BookingResult dataclasses
│   ├── auth.py              build_credentials (service_account OR OAuth)
│   ├── client.py            GoogleCalendarClient wrapper (async over sync google-api-python-client)
│   ├── availability.py      Pure find_slots: business hours + busy intervals -> slots
│   ├── booking.py           book_appointment with race detection + UNVERIFIED tagging
│   ├── setup_cli.py         python -m receptionist.booking setup <business>
│   └── __main__.py          CLI dispatcher
│
├── messaging/               Message delivery
│   ├── models.py            Message dataclass, DispatchContext
│   ├── dispatcher.py        Multi-channel fan-out (sync file + background others)
│   ├── retry.py             retry_with_backoff + RetryPolicy
│   ├── failures.py          .failures/ record writer, resolve_failures_dir
│   ├── failures_cli.py      list-failures implementation
│   ├── __main__.py          python -m receptionist.messaging list-failures
│   └── channels/
│       ├── file.py          FileChannel
│       ├── webhook.py       WebhookChannel (httpx + retry)
│       └── email.py         EmailChannel (builds subject/body, sends via email/*)
│
├── email/                   Email transport
│   ├── sender.py            EmailSender protocol, EmailSendError, EmailAttachment
│   ├── smtp.py              SMTPSender (aiosmtplib)
│   ├── resend.py            ResendSender (httpx → Resend API)
│   └── templates.py         build_message_email / build_call_end_email
│
├── recording/               Call recording
│   ├── storage.py           resolve_destination (local path or S3 URL)
│   └── egress.py            start_recording / stop_recording (LiveKit Egress API)
│
├── transcript/              Transcripts
│   ├── metadata.py          CallMetadata dataclass
│   ├── capture.py           TranscriptCapture + SpeakerRole + TranscriptSegment
│   ├── formatter.py         to_json / to_markdown
│   └── writer.py            write_transcript_files
│
└── retention/               Retention sweeper
    ├── sweeper.py           sweep_directory / sweep_business
    └── __main__.py          python -m receptionist.retention sweep
```

## Call flow

### 1. Arrival
1. Caller dials number → SIP trunk routes to LiveKit Cloud
2. LiveKit Cloud creates a room and dispatches to the registered agent
3. `@server.rtc_session()` fires `handle_call(ctx)`

### 2. Session initialization
1. `load_business_config(ctx)` picks a YAML based on `job.metadata["config"]` (or first YAML as fallback)
2. `CallLifecycle(config, call_id, caller_phone)` is constructed; `caller_phone` is pulled from the SIP participant's `sip.phoneNumber` attribute when available, and filled later from the `participant_connected` event if the SIP participant had not joined yet
3. `AgentSession` created with `openai.realtime.RealtimeModel(model=config.voice.model, voice=config.voice.voice_id)`
4. `lifecycle.attach_transcript_capture(session)` subscribes to `user_input_transcribed`, `conversation_item_added`, `function_tools_executed` events
5. `session.on("close", _handle_close)` registered — schedules `lifecycle.on_call_ended()` and resolves a future
6. `lifecycle.start_recording_if_enabled(ctx.room.name)` starts LiveKit Egress if `config.recording.enabled`

### 3. Greeting flow
- If `config.recording.consent_preamble.enabled`: speak the preamble FIRST (two-party consent jurisdictions require notification before recording)
- Then speak `config.greeting`

### 4. Conversation loop
- Caller speaks → `user_input_transcribed` → `TranscriptCapture` appends segment; `metadata.languages_detected` updated
- Agent speaks → `conversation_item_added` (item.role=="assistant") → segment appended
- Tool invocations → `function_tools_executed` → tool segments appended
  - `lookup_faq` → `lifecycle.record_faq_answered(question)`
  - `transfer_call` → `lifecycle.record_transfer(department)` → `transfer_target` + outcome="transferred"
  - `take_message` → `Dispatcher.dispatch_message(...)` (sync file + background email/webhook) → `lifecycle.record_message_taken()` → outcome="message_taken"
  - `get_business_hours` → no metadata change

### 5. Disconnect
1. `session` emits `close` event
2. `_handle_close` schedules `lifecycle.on_call_ended()` via `asyncio.create_task`, then resolves `close_work_done`
3. `on_call_ended`:
   - `metadata.mark_finalized()` (sets end_ts, duration, outcome="hung_up" if none)
   - If recording: `stop_recording(handle)` returns artifact URL (local path or s3://)
   - If transcripts: `write_transcript_files(...)` writes JSON + Markdown
   - If `email.triggers.on_call_end`: `EmailChannel.deliver_call_end(metadata, context)` for each configured email channel
4. `handle_call` awaits `close_work_done` (30s timeout) before returning — guarantees artifacts land before worker releases the call

## Key design decisions

### Sync-file, background-others dispatch
`take_message` awaits the **file channel synchronously** — guarantees a durable copy exists before the LLM tells the caller "message saved." Email and webhook fire as background tasks; on exhausted retries, failure records land in `.failures/`.

If no file channel is configured, the dispatcher falls back to syncing `webhook` (preferred) or `email`, preserving the "something durable exists before confirmation" invariant.

### Consent preamble before greeting
Two-party consent states require caller notification BEFORE recording. Recording starts at call pickup (step 2.6), but the preamble is the first thing the caller hears — and it's captured on the recording, which is correct proof of disclosure.

### Close-event handler
`livekit.rtc.EventEmitter.on()` requires plain (non-async) callbacks. We register a sync handler that schedules async work via `asyncio.create_task(_run())`. The `@rtc_session` framework keeps the job — and therefore the event loop — alive until the underlying room actually closes, which is what gives the scheduled task time to run.

An earlier version of `handle_call` also awaited a `close_work_done` future with a 30-second timeout, on the incorrect assumption that `AgentSession.start()` blocked for the call duration. It actually returns after session initialization, so the future-await ran in parallel with the ongoing call and fired a spurious timeout warning on every call longer than 30 seconds. Removed in commit `159f5ba`.

### Subpackage per capability
`messaging/`, `email/`, `recording/`, `transcript/`, `retention/` each have one clear purpose and a small mockable surface. `agent.py` stays thin; `lifecycle.py` is the only cross-subpackage coordinator.

### Calendar integration — session-scoped slot cache

`check_availability` populates `Receptionist._offered_slots: set[str]` with the
ISO start strings of every slot returned to the LLM. `book_appointment`
validates its `proposed_start_iso` argument against that set and rejects any
string that wasn't offered. This makes the "check-before-book" ordering
architecturally enforceable — the LLM cannot book a time it didn't offer,
even if it hallucinates. Separately, `book_appointment` does a last-second
free/busy re-check and raises `SlotNoLongerAvailableError` if the slot was
taken between offer and book, so the LLM can relay alternatives.

All Google API calls go through `booking/client.py`, which wraps the
synchronous `google-api-python-client` in `asyncio.to_thread`. This keeps
the agent's event loop unblocked during Google calls (which can run
hundreds of milliseconds on first-call auth).

## Known upstream limitations

### `CallMetadata.languages_detected` always empty

`CallMetadata.languages_detected` is intended to capture the set of languages the caller used during the call. It is populated in `transcript/capture.py::_on_user_input` from `UserInputTranscribedEvent.language`.

**As of `livekit-plugins-openai==1.5.6`, the OpenAI Realtime transcription path does not populate that field.** The plugin emits `llm.InputTranscriptionCompleted(item_id, transcript, is_final, confidence)` — no language — and the SDK's subsequent `UserInputTranscribedEvent` construction leaves `language=None`. Our handler does the right thing (`if lang: self.metadata.languages_detected.add(lang)`) but `lang` is always `None`, so the set stays empty.

Impact is cosmetic: all consumers (`email/templates.py`, `transcript/formatter.py`) already guard with `if metadata.languages_detected:` so empty sets never leak into user-visible output. The only visible effect is that the JSON transcript metadata contains `"languages_detected": []` instead of the detected set, and the field is omitted from email/Markdown summaries.

The language-switching behavior itself works correctly — the LLM detects and adapts on its own. Only the reporting metadata is missing.

If this becomes a real operational need (e.g., a language-distribution dashboard), a post-hoc detector over the accumulated transcript segments is a small addition. Tracked as issue #5.

## Testing boundaries

- **Unit tests** cover every subpackage's public surface (~120 tests total)
- **One integration test** (`tests/integration/test_call_flow.py`) exercises Dispatcher + CallLifecycle wiring without LiveKit
- **`agent.py` and `Receptionist` tool methods** are validated manually (`tests/MANUAL.md`) — mocking LiveKit's session machinery is not cost-effective
- **`on_enter`** is unit-tested via a class-level property patch on `Agent.session` (`monkeypatch.setattr(Agent, "session", property(...))`)
