# Manual Validation Checklist

These scenarios cannot be fully automated — they require a live LiveKit playground (or a real phone number) and credentials for OpenAI Realtime. Run through this list before declaring a release ready.

Each checkbox should be checked off in the PR description or release notes; unchecked items are blocking.

## Prerequisites
- [ ] Virtualenv active and deps installed (`pip install -e ".[dev]"`)
- [ ] `.env` populated with `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `OPENAI_API_KEY`
- [ ] Agent starts cleanly: `python -m receptionist.agent dev` shows `starting worker` with no errors

## Core call flow
- [ ] Place a LiveKit Playground call → greeting is heard in the configured voice (default `marin`)
- [ ] Greeting matches `config.greeting` for the loaded business YAML

## Consent preamble
- [ ] With `recording.enabled: true` and `consent_preamble.enabled: true`: preamble is heard BEFORE the greeting, not after
- [ ] With `recording.enabled: true` and `consent_preamble.enabled: false`: only greeting is heard
- [ ] With `recording.enabled: false`: only greeting is heard (preamble config ignored)

## Multi-language
- [ ] With `languages.allowed: ["en", "es"]`: start in English → agent responds in English. Switch to Spanish → agent switches to Spanish for the rest of the call.
- [ ] With `languages.allowed: ["en"]`: say a few words in Spanish → agent politely redirects in English ("I can assist in English — could we continue in English?")

## Tools
- [ ] Ask about a configured FAQ → `lookup_faq` returns the answer
- [ ] Ask to be transferred → `transfer_call` is invoked; SIP transfer occurs (or is attempted — check logs)
- [ ] Leave a voice message → `take_message` acknowledges the save
- [ ] Ask about hours → `get_business_hours` returns the current day's open/close status

## Message delivery (per enabled channel)
- [ ] **file**: a JSON file appears under `file_path` after a message is taken
- [ ] **email**: inbox receives the message email with caller, callback, message body
- [ ] **webhook**: webhook endpoint receives the POST with `{"message": ..., "context": ...}` payload
- [ ] Multi-channel (all three enabled): all three destinations receive the message; file channel delivery never blocks the caller experience

## Recording
- [ ] With `storage.type: "local"`: a `.mp4` file appears under `storage.local.path`
- [ ] With `storage.type: "s3"`: the recording appears in the configured bucket/prefix
- [ ] The recording includes the consent preamble (verify by listening)

## Transcripts
- [ ] On disconnect, `transcript_<timestamp>_<callid>.json` and `.md` files appear under `transcripts.storage.path`
- [ ] JSON contains `metadata` with call_id, business_name, caller_phone, outcome, duration_seconds
- [ ] Markdown shows `**Caller:**`, `**Agent:**`, `**Tool:**` labels with correct content
- [ ] Tool segments include `arguments` and `output`

## Call-end email trigger
- [ ] With `email.triggers.on_call_end: true`: summary email arrives after every call (transferred, message_taken, hung_up)
- [ ] Subject includes the outcome
- [ ] Body mentions transcript path when transcripts enabled

## Failures handling
- [ ] Point a webhook channel at a non-existent URL → message still saves to file (sync channel) → after retries exhaust, a `.failures/*.json` record appears
- [ ] `python -m receptionist.messaging list-failures` lists the failure
- [ ] Fix the URL → no new failures; old `.failures/` files remain (not auto-cleared)

## Retention
- [ ] `python -m receptionist.retention sweep --dry-run` lists artifacts that WOULD be deleted
- [ ] Without `--dry-run`: files older than TTL are deleted; `.failures/` content is untouched

## Disconnect robustness
- [ ] Hang up mid-greeting → lifecycle fires (logs show `on_call_ended`), transcript is written
- [ ] Hang up mid-conversation → transcript captures the last exchange
- [ ] Let the call time out on silence → close event fires, artifacts written

## Known limitations to NOT flag as bugs
- Python 3.14 may print compatibility warnings (use 3.11/3.12 for production)
- `sip.phoneNumber` attribute may be absent on non-standard SIP trunks → caller appears as "Unknown" in emails (not a bug; documented fallback)
- `S3` storage for transcripts is NOT supported (local only)
