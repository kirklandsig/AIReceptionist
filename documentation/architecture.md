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
├── info_packets.py          Consent-gated caller packet email helper
├── voice_auth.py            Per-business Realtime bearer resolver (`voice.auth`)
├── voice/                   OpenAI voice auth setup CLI
│   ├── setup_cli.py         python -m receptionist.voice setup <business>
│   └── __main__.py          CLI dispatcher
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
│   └── templates.py         message / call-end / intake / info-packet email templates
│
├── intakes/                 Structured intake persistence
│   ├── models.py            IntakeAnswer / IntakeSubmission dataclasses
│   └── storage.py           Atomic partial/final JSON writers
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
2. LiveKit Cloud creates a room and dispatches to the registered agent name (`RECEPTIONIST_AGENT_NAME`, default `receptionist`)
3. `@server.rtc_session(agent_name=...)` fires `handle_call(ctx)`

### 2. Session initialization
1. `load_business_config(ctx)` picks a YAML based on `job.metadata["config"]` (or first YAML as fallback)
2. The process has already started an idempotent generation watchdog before LiveKit worker registration when the restart launcher provides a worker generation token. The watchdog exits if `agent.generation` changes or disappears, preventing stale local LiveKit `dev` workers from handling later calls after a restart.
3. `CallLifecycle(config, call_id, caller_phone)` is constructed; `caller_phone` is pulled from SIP participant metadata when available (`sip.phoneNumber`, `sip.fromUser`, `sip.from`, or `sip_<digits>` identity fallback), and filled later from the `participant_connected` event if the SIP participant had not joined yet
4. `AgentSession` created with `openai.realtime.RealtimeModel(model=config.voice.model, voice=config.voice.voice_id, api_key=await resolve_voice_bearer_async(config.voice.auth))`; explicit `oauth_codex` tokens refresh before session construction when needed. **Deprecated (2026-06-03):** the `oauth_codex` auth type no longer works against the GA Realtime API — OpenAI sunset the Realtime Beta endpoint and the GA endpoint rejects ChatGPT/Codex OAuth tokens (the handshake fails with HTTP 500, so the call connects but the caller hears dead air). Use `voice.auth.type: api_key` with a standard `sk-` key in `OPENAI_API_KEY` and a GA model such as `gpt-realtime`. The refresh path is retained only for historical context; see `documentation/troubleshooting.md` ("Realtime handshake fails with 500 / Beta API sunset"). `voice.idle.away_seconds` feeds `AgentSession.user_away_timeout`, and `voice.idle.absolute_silence_seconds` can add a wall-clock final-transcript fallback for SIP trunks that send comfort noise.
5. `Receptionist(config, lifecycle)` is constructed and its local tool contract is verified before `session.start()`. Enabled intakes require `record_intake_answer` and `finalize_intake`; enabled info packets require `send_info_packet`.
6. `lifecycle.attach_transcript_capture(session)` subscribes to `user_input_transcribed`, `conversation_item_added`, `function_tools_executed` events
7. `session.on("close", _handle_close)` registered — cancels idle timers and schedules `lifecycle.on_call_ended()`
8. `lifecycle.start_recording_if_enabled(ctx.room.name)` starts LiveKit Egress if `config.recording.enabled`
9. After `session.start()`, the agent explicitly refreshes the Realtime tool registry with the full local tool list.

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
  - `record_intake_answer` → validates case/question keys, updates in-memory intake state, writes a partial intake JSON after each answer, and queues the latest partial for structured call-end email
  - `finalize_intake` → writes the final intake JSON, replaces the queued partial with the final structured intake email, records outcome="intake_submitted", and nudges Riley to offer a configured packet when `info_packets.enabled`
  - `send_info_packet` → after caller consent and confirmed email, sends a configured packet through the existing email sender stack and records success/failure in call metadata
  - `get_business_hours` → no metadata change
  - `end_call` → `lifecycle.record_agent_ended(reason)` → outcome="agent_ended" + `agent_end_reason`, then background goodbye. The background task finalizes `lifecycle.on_call_ended()` before waiting for goodbye playout or SIP BYE/delete-room termination, so deferred emails fire before LiveKit job teardown.
- Idle safety nets run outside the LLM tool path:
  - Silence timeout (`voice.idle.away_seconds + silence_grace_seconds`) → reason="silence_timeout"
  - Optional wall-clock silence fallback (`voice.idle.absolute_silence_seconds`) → same `silence_timeout` reason when no non-empty final user transcript arrives before the threshold
  - Max-duration cap (`voice.idle.max_call_duration_seconds`, when set) → reason="max_duration_reached"
  - Consecutive unproductive replies (`voice.idle.unproductive_turn_threshold`) → reason="unproductive_turns_exhausted"
- DTMF keypress (when `dtmf.enabled`) → LiveKit room emits `sip_dtmf_received`
  → handler resolves the digit against `dtmf.digits`, debounces and suppresses
  in-flight repeats, speaks a brief acknowledgment, then dispatches the
  configured action (transfer via the shared `_execute_transfer` helper,
  take_message via a collection prompt, end_call, or repeat_menu). Each press
  is recorded via `lifecycle.record_dtmf_event(...)`.

### 5. Disconnect
1. `session` emits `close` event
2. `_handle_close` cancels pending idle timers, then schedules `lifecycle.on_call_ended()` via `asyncio.create_task`. Agent-initiated `end_call` may have already finalized the lifecycle; the close handler is idempotent and becomes a no-op in that case.
3. `on_call_ended`:
   - `metadata.mark_finalized()` (sets end_ts, duration, outcome="hung_up" if none)
   - If recording: `stop_recording(handle)` returns artifact URL (local path or s3://)
   - If transcripts: `write_transcript_files(...)` writes JSON + Markdown
   - If a message or intake email was queued during the call, deliver those deferred emails with the final transcript context. Intake emails may be final or partial, depending on whether `finalize_intake` ran.
   - If `email.triggers.on_call_end`: `EmailChannel.deliver_call_end(metadata, context, captured_messages=...)` for each configured email channel. The lifecycle copies pending `take_message` entries before clearing the queue so the call summary email can render them above recording/transcript details. Packet send records from `CallMetadata.info_packet_sends` are rendered in the same call-end summary.
4. The LiveKit RTC job keeps the event loop alive until the room closes; close-time artifact work runs from the scheduled task

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

### Intake-only mode and packet delivery

`agent.mode` defaults to `receptionist`. When set to `intake_only`,
`build_system_prompt()` omits receptionist routing, FAQ, and business-hours
sections and focuses Riley on phone intake, callback messages, and ending the
call cleanly. The `transfer_call` tool also refuses at runtime in
`intake_only` mode, so a transfer request becomes a message/callback path even
if the model attempts the tool.

`info_packets` is intentionally configuration-driven. Packet subject, body,
and links come from YAML; the model only chooses a configured `packet_key` and
caller-confirmed destination. `send_info_packet` refuses SMS in v1, validates
the destination shape, sends through SMTP/Resend via `info_packets.py`, and
stores the result in call metadata for auditability.

### DTMF as a deterministic side channel

Keypad presses are not routed through the LLM. The handler reads the
digit→action mapping from YAML and runs the action directly off LiveKit's
`sip_dtmf_received` event. Transfers share the same `_execute_transfer` helper
as the LLM `transfer_call` tool, so the `intake_only` gate and SIP API path
exist in exactly one place. The handler debounces same-digit repeats (1.5s) and
suppresses presses while an action is in flight, and only acts on events from
the resolved SIP caller participant. Every press is recorded as a
`DtmfEventRecord` in `CallMetadata.dtmf_events` and rendered in the call-end
email's "Keypad actions" section.

### Local dev worker generation guard

`scripts/restart-agent.ps1` delegates to `scripts/_spawn_agent.py`, which writes
`secrets/<business>/runtime/agent.generation`, passes the token/path to the
spawned process, and records `agent restart generation=<token>` in `agent.log`.
The running agent starts that watchdog before LiveKit CLI worker registration
and exits if a newer restart changes the file.
`scripts/agent-status.ps1` is generation-aware: it only reports healthy when
the pidfile PID is this checkout's `python -m receptionist.agent dev`, a
`registered worker` line appears after the current generation marker, and no
unexpected same-checkout orphan agent processes are running.

## Known upstream limitations

### `CallMetadata.languages_detected` always empty

`CallMetadata.languages_detected` is intended to capture the set of languages the caller used during the call. It is populated in `transcript/capture.py::_on_user_input` from `UserInputTranscribedEvent.language`.

**As of `livekit-plugins-openai==1.5.6`, the OpenAI Realtime transcription path does not populate that field.** The plugin emits `llm.InputTranscriptionCompleted(item_id, transcript, is_final, confidence)` — no language — and the SDK's subsequent `UserInputTranscribedEvent` construction leaves `language=None`. Our handler does the right thing (`if lang: self.metadata.languages_detected.add(lang)`) but `lang` is always `None`, so the set stays empty.

Impact is cosmetic: all consumers (`email/templates.py`, `transcript/formatter.py`) already guard with `if metadata.languages_detected:` so empty sets never leak into user-visible output. The only visible effect is that the JSON transcript metadata contains `"languages_detected": []` instead of the detected set, and the field is omitted from email/Markdown summaries.

The language-switching behavior itself works correctly — the LLM detects and adapts on its own. Only the reporting metadata is missing.

If this becomes a real operational need (e.g., a language-distribution dashboard), a post-hoc detector over the accumulated transcript segments is a small addition. Tracked as issue #5.

## Testing boundaries

- **Unit tests** cover every subpackage's public surface (~380 tests total)
- **One integration test** (`tests/integration/test_call_flow.py`) exercises Dispatcher + CallLifecycle wiring without LiveKit
- **`agent.py` and `Receptionist` tool methods** are validated manually (`tests/MANUAL.md`) — mocking LiveKit's session machinery is not cost-effective
- **`on_enter`** is unit-tested via a class-level property patch on `Agent.session` (`monkeypatch.setattr(Agent, "session", property(...))`)
