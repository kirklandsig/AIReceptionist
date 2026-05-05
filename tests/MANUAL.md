# Manual Validation Checklist

These scenarios cannot be fully automated — they require a live LiveKit playground (or a real phone number) and credentials for OpenAI Realtime. Run through this list before declaring a release ready.

Each checkbox should be checked off in the PR description or release notes; unchecked items are blocking.

## Prerequisites
- [ ] Virtualenv active and deps installed (`pip install -e ".[dev]"`)
- [ ] `.env` populated with `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, and either `OPENAI_API_KEY` or per-business `voice.auth`
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
- `sip.phoneNumber` attribute may be absent on non-standard SIP trunks; CallerID falls back to SIP metadata and `sip_<digits>` identities when present
- `S3` storage for transcripts is NOT supported (local only)

---

## OpenAI Realtime OAuth

Requires Codex CLI installed (`codex --version`) and a ChatGPT account with
Realtime model access.

### Setup

- [ ] Run `python -m receptionist.voice setup example-dental`
- [ ] Browser/Codex login completes using the intended ChatGPT account
- [ ] Token file exists at `secrets/example-dental/openai_auth.json`
- [ ] `config/businesses/example-dental.yaml` contains `voice.auth.type: oauth_codex`
- [ ] Agent starts with `RECEPTIONIST_CONFIG=example-dental python -m receptionist.agent dev`

### Live call smoke test

- [ ] Connect from LiveKit Playground
- [ ] Greeting is heard using `gpt-realtime-1.5` and the configured voice
- [ ] Complete at least two conversational turns without `401`, `Invalid bearer token`, or `insufficient_scope`

### Refresh smoke test

- [ ] Preserve the real `tokens.refresh_token` in `secrets/example-dental/openai_auth.json`
- [ ] Replace only `tokens.access_token` with an expired JWT-shaped test token
- [ ] Start the agent and place a LiveKit Playground call
- [ ] Agent refreshes the token before session construction; auth file is rewritten with a fresh `tokens.access_token`
- [ ] Call proceeds normally after refresh

---

## Calendar integration (issue #3)

Requires a test Google Workspace calendar or a personal gmail.com calendar
set aside for testing. Do NOT test against a production firm calendar.

### Setup

- [ ] **Service account setup:**
  - Create service account in Google Cloud Console
  - Download JSON key
  - Share test calendar with service account email
  - Place key at `secrets/<test-business>/google-calendar-sa.json`
  - Agent starts cleanly: `python -m receptionist.agent dev`

- [ ] **OAuth setup:**
  - Create OAuth client (Desktop app) in Google Cloud Console
  - Download client JSON
  - Place at `secrets/<test-business>/google-calendar-oauth-client.json`
  - Run: `python -m receptionist.booking setup <test-business>`
  - Browser opens, consent flow completes
  - Token file written at `secrets/<test-business>/google-calendar-oauth.json`
  - Verify permissions are `0600` on Unix: `ls -la secrets/<test-business>/google-calendar-oauth.json`
  - Agent starts cleanly

### Happy path

- [ ] Place a call, ask "Can I book an appointment for Tuesday at 2 PM?"
- [ ] Agent speaks back: "I found these available times..." with 1-3 options
- [ ] Caller picks one: "2 PM works"
- [ ] Agent confirms: "I'm booking you for <Tuesday> at 2:00 PM — can I confirm?"
- [ ] Caller says yes
- [ ] Agent says "You're all set" + confirms callback number
- [ ] Event appears on the configured Google Calendar
- [ ] Event summary: "Appointment: <caller name>"
- [ ] Event description contains: "[via AI receptionist / UNVERIFIED]", caller
      name, callback number, booked-at timestamp, call ID, Notes line

### Race condition

- [ ] On a fresh window, open Google Calendar UI manually
- [ ] During a call, get to step "agent offers 3 slots"
- [ ] While the agent is waiting for caller confirmation, manually create a
      conflicting event on the calendar at one of the offered slots
- [ ] Caller confirms that slot
- [ ] Agent says "Unfortunately that slot just got taken — here are the
      nearest alternatives" and lists new options
- [ ] Caller picks a new one → books successfully

### Constraints

- [ ] Ask for a time less than `earliest_booking_hours_ahead` from now:
      agent politely declines with the earliest-allowed time
- [ ] Ask for a time outside business hours (e.g. Sunday): agent offers a
      nearby weekday slot
- [ ] Ask for a time beyond `booking_window_days`: agent politely declines

### Multi-outcome

- [ ] During a call, book an appointment AND ask to be transferred
- [ ] After disconnect, check `transcripts/<business>/*.json`:
      `metadata.outcomes` is `["appointment_booked", "transferred"]`
      (sorted list)

### on_booking email trigger

- [ ] Enable `email.triggers.on_booking: true` in the test business YAML
      (also ensure the `email:` section is populated)
- [ ] Place a booking call end-to-end
- [ ] Staff inbox receives "New appointment booked: +1555... — <time>"
      email with the Google Calendar event link and UNVERIFIED disclaimer
- [ ] Also enable `email.triggers.on_call_end: true` — verify BOTH emails
      arrive (booking + call summary)

### Error paths

- [ ] Delete `secrets/<business>/google-calendar-sa.json` while agent is
      running. Place a call, ask for availability. Agent should pivot to
      "Can I take a message about your preferred time?" (calendar auth
      error handled gracefully).
- [ ] Block outbound HTTPS to Google. Ask for availability. Agent pivots
      to take_message.
- [ ] Revoke the service account's calendar sharing. Ask for availability.
      Agent pivots to take_message (403 error path).

### Cleanup

- [ ] Delete the test events from Google Calendar after validation
- [ ] Remove the test business config + secrets if desired
