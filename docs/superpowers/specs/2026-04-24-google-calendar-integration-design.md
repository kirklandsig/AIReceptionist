# Google Calendar Integration — Design Spec

> **Status:** Draft — pending user review
> **Created:** 2026-04-24
> **Originating request:** GitHub issue #3 (from @marmo-75's question in #1)
> **Scope:** First-pass appointment booking during a call via Google Calendar, with both service-account and OAuth auth paths.

---

## 1. Summary

The agent gains two function tools — `check_availability` and `book_appointment` — that let it query and write to a per-business Google Calendar during a live call. Callers can request a time slot, hear the agent confirm the specific parsed time, say yes, and have an event created on the calendar before the call ends. Staff get notified via the existing email channel when a booking lands.

The design targets small-business appointment scheduling (dental offices, salons, therapists) as the primary use case but remains generic enough for consultation-style bookings (law firms like MDASR).

Architecture follows the subpackage-per-capability pattern from PR #2: a new `receptionist/booking/` subpackage holds all calendar-specific code; `agent.py`, `lifecycle.py`, `config.py`, and `prompts.py` get small targeted additions.

**One breaking change to an existing data field** is bundled with this work (see §2.6): `CallMetadata.outcome: str | None` becomes `CallMetadata.outcomes: set[str]` to support multi-outcome calls (e.g. transferred AND booked). Now is the right window for this change — PR #2 shipped yesterday and no external consumers have locked onto the old shape.

---

## 2. Configuration schema

### 2.1 New `calendar:` section

```yaml
calendar:
  enabled: true
  calendar_id: "primary"                       # or a specific ID like "foo@group.calendar.google.com"

  # Auth — discriminated union on `type`
  auth:
    type: "service_account"
    service_account_file: "./secrets/mdasr/google-calendar-sa.json"
    # OR:
    # type: "oauth"
    # oauth_token_file: "./secrets/mdasr/google-calendar-oauth.json"

  # Booking rules
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"                    # "before" | "after" | "both" (default: "after")
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
```

### 2.2 New `email.triggers.on_booking`

```yaml
email:
  triggers:
    on_message: true
    on_call_end: false
    on_booking: true                           # NEW — email staff when an appointment is booked
```

### 2.3 New Pydantic models (in `receptionist/config.py`)

- `ServiceAccountAuth(type: Literal["service_account"], service_account_file: str)` with `ConfigDict(extra="forbid")`
- `OAuthAuth(type: Literal["oauth"], oauth_token_file: str)` with `ConfigDict(extra="forbid")`
- `CalendarAuth = Annotated[Union[ServiceAccountAuth, OAuthAuth], Field(discriminator="type")]`
- `CalendarConfig`:
  - `enabled: bool`
  - `calendar_id: str = "primary"`
  - `auth: CalendarAuth`
  - `appointment_duration_minutes: int = 30`
  - `buffer_minutes: int = 15`
  - `buffer_placement: Literal["before", "after", "both"] = "after"`
  - `booking_window_days: int = 30`
  - `earliest_booking_hours_ahead: int = 2`
- `EmailTriggers` gains `on_booking: bool = False`
- `BusinessConfig` gains `calendar: CalendarConfig | None = None`

### 2.4 Validation rules

- `buffer_minutes >= 0`
- `booking_window_days > 0`
- `earliest_booking_hours_ahead >= 0`
- `appointment_duration_minutes > 0`
- At config load time, verify the configured auth key file exists (service_account_file or oauth_token_file) when `calendar.enabled: true`. Fail fast at agent startup, not at first call.
- `ConfigDict(extra="forbid")` on both auth variants rejects silent misconfiguration (user leaves `oauth_token_file:` in a `service_account` block by accident → clear validation error).

### 2.5 Cross-section validator (on `BusinessConfig`)

If `calendar.enabled` is true AND `email.triggers.on_booking` is true, the top-level `email` section must be present. Same pattern as PR #2's email-channel-requires-email-section validator.

### 2.6 Breaking change: `CallMetadata.outcomes` (set, not string)

PR #2 introduced `CallMetadata.outcome: str | None` with a priority-based `_OUTCOME_PRIORITY` dict that picked one winner when multiple events occurred in a call. This design was honest about normal cases but loses information when (for example) a call both transfers AND books an appointment.

The new shape:

- `CallMetadata.outcome: str | None` → `CallMetadata.outcomes: set[str]`
- `_OUTCOME_PRIORITY` dict is **deleted**
- `lifecycle._set_outcome(outcome)` → `lifecycle._add_outcome(outcome)` — no priority check, just `.add()`
- Valid outcomes: `{"hung_up", "message_taken", "transferred", "appointment_booked"}`. Membership-checked in `_add_outcome` to prevent silent typos (this rule was added to PR #2's `_set_outcome` as a code-review fix — preserve it).
- `CallMetadata.mark_finalized()`: if `outcomes` is still empty, add `"hung_up"`. Same fallback semantics as before.
- `metadata.to_dict()["outcomes"]` → sorted list of strings.
- Templates (`build_call_end_email`, `build_booking_email`, transcript formatter) render multi-outcome cases gracefully: "Transferred + Appointment booked" in subject lines, one line per outcome in bodies.

Affected files:

| File | Change |
|---|---|
| `receptionist/transcript/metadata.py` | Field rename + shape change. `to_dict` emits `outcomes` (sorted list). |
| `receptionist/lifecycle.py` | Delete `_OUTCOME_PRIORITY`. Rename `_set_outcome` → `_add_outcome`. Each `record_*` method calls `.add(...)`. |
| `receptionist/email/templates.py` | `outcome_display` logic becomes `outcomes_display` — joins labels with ` + `. |
| `receptionist/transcript/formatter.py` | Markdown header emits multi-outcome line. |
| Existing tests in `tests/test_lifecycle.py`, `tests/transcript/test_metadata.py`, `tests/transcript/test_formatter.py`, `tests/email/test_templates.py`, `tests/integration/test_call_flow.py` | ~30 assertions updated from `metadata.outcome == "x"` to `"x" in metadata.outcomes`. |

This change lands in rollout step 3 — before any `booking/` code is written — so subsequent work targets the new shape directly.

### 2.7 Env-var interpolation

Existing `${VAR_NAME}` interpolation from PR #2 continues to work for any string field in `calendar:`. Not used for the auth key files themselves (they're file paths, and the key contents are too multi-line to shoehorn into an env var — this was the same argument we had in PR #2 re: SMTP passwords vs. key files).

---

## 3. Package structure

```
receptionist/booking/                 # NEW — named `booking`, NOT `calendar`, to avoid stdlib shadow
├── __init__.py
├── models.py                         # Runtime dataclasses: SlotProposal, BookingResult
├── auth.py                           # build_credentials(CalendarAuth) → google.auth.Credentials
├── client.py                         # GoogleCalendarClient: free_busy, create_event
├── availability.py                   # Pure function: find_slots(business_hours, config, preferred_dt, busy, now) → list[SlotProposal]
├── booking.py                        # book_appointment(slot, caller, client, config) → BookingResult
├── setup_cli.py                      # OAuth setup wizard
└── __main__.py                       # python -m receptionist.booking

receptionist/agent.py                 # Adds check_availability + book_appointment @function_tool methods; session-scoped slot cache
receptionist/config.py                # Adds CalendarConfig + auth union + EmailTriggers.on_booking
receptionist/lifecycle.py             # record_appointment_booked; new on_booking email trigger fan-out
receptionist/prompts.py               # Emits CALENDAR system-prompt section when enabled
receptionist/email/templates.py       # Adds build_booking_email(metadata, context)
receptionist/messaging/channels/email.py # Adds EmailChannel.deliver_booking

tests/booking/
├── test_config.py
├── test_auth.py
├── test_client.py
├── test_availability.py
├── test_booking.py
└── test_setup_cli.py

tests/integration/test_booking_flow.py    # End-to-end flow without real Google API
```

### 3.1 Component responsibilities

| Module | Responsibility | Dependencies |
|---|---|---|
| `booking/auth.py` | Build Google API credentials from `CalendarAuth`. Handles both service-account and OAuth paths. Validates file permissions (0600 on Unix for OAuth token files). | `google.oauth2.service_account`, `google.oauth2.credentials` |
| `booking/client.py` | `GoogleCalendarClient(credentials, calendar_id)`. Two methods: `async free_busy(start, end) -> list[(datetime, datetime)]`, `async create_event(start, end, summary, description, location=None) -> dict`. Pure wrapper — no business logic. | `googleapiclient.discovery` |
| `booking/availability.py` | `find_slots(business_hours, calendar_config, preferred_dt, existing_busy, earliest, latest, now) -> list[SlotProposal]`. Pure function, no I/O. Caller resolves timezone and passes in datetime objects. | stdlib only |
| `booking/booking.py` | `async book_appointment(slot, caller_info, client, config, call_id) -> BookingResult`. Validates slot against current free/busy (race detection), builds event body with UNVERIFIED tag + call_id + timestamp, calls `client.create_event`, returns result. | `client`, `models` |
| `booking/setup_cli.py` | Interactive OAuth flow via `google-auth-oauthlib.flow.InstalledAppFlow`. Operator-provided client_id/client_secret (per §5 OAuth registration). Writes token file with `0600` permissions. | `google_auth_oauthlib.flow` |
| `booking/__main__.py` | Argparse-based dispatcher: `python -m receptionist.booking setup <business-slug>`. | — |

### 3.2 Key boundaries

- `availability.py` is **pure** — takes a busy list as input, returns slots. Unit-testable with synthetic inputs, no mocks of Google API.
- `client.py` is the **only** module that imports `googleapiclient`. Mockable in every other test.
- `auth.py` is the **only** module that imports `google.oauth2`. Credentials returned as opaque objects.
- `setup_cli.py` is completely isolated from runtime code — only needs auth setup, never touches availability/booking.
- `booking/` knows nothing about `Receptionist`, `CallLifecycle`, or `AgentSession`. Those call INTO booking, not the other way around.

---

## 4. Data flow

### 4.1 A booking call, end to end

```
1. Caller: "I'd like to book Tuesday at 2pm"
   └─> Receptionist.check_availability(preferred_date="Tuesday", preferred_time="2pm")
       ├─> parse caller's natural-language time into tz-aware datetime
       │   (tool parses using dateutil + business timezone; LLM is responsible for
       │    extracting "Tuesday" and "2pm" as separate string args)
       ├─> credentials = booking.auth.build_credentials(config.calendar.auth)
       ├─> client = GoogleCalendarClient(credentials, config.calendar.calendar_id)
       ├─> now = datetime.now(ZoneInfo(business.timezone))
       ├─> earliest = now + timedelta(hours=earliest_booking_hours_ahead)
       ├─> latest = now + timedelta(days=booking_window_days)
       ├─> busy = await client.free_busy(earliest, latest)
       ├─> slots = booking.availability.find_slots(
       │       business_hours=config.hours,
       │       calendar_config=config.calendar,
       │       preferred_dt=parsed_preferred_dt,
       │       existing_busy=busy,
       │       earliest=earliest,
       │       latest=latest,
       │       now=now,
       │   )
       ├─> store each slot's ISO string in self._offered_slots (set)
       └─> return up to 3 nearest slots as ISO strings to the LLM

2. Agent (LLM): "I have Tuesday April 28 at 2:00 PM, or 2:30, or 3:00. Which works?"
   Caller: "2:00."
   Agent: "Great — I'm booking you for Tuesday April 28 at 2:00 PM. Can I confirm?"
   Caller: "Yes."

3. Receptionist.book_appointment(
       caller_name="Jane Doe",
       callback_number="+15551234567",
       proposed_start_iso="2026-04-28T14:00:00-04:00",
       notes=None,
   )
   ├─> validate proposed_start_iso in self._offered_slots   [HARD ERROR IF NOT]
   ├─> re-check current free/busy for just this slot (race detection)
   │   └─> if now busy: return error with alternative slots, LLM offers them
   ├─> build event body:
   │     summary = "Appointment: Jane Doe"
   │     description = [
   │       "[via AI receptionist / UNVERIFIED]",
   │       f"Caller: {caller_name}",
   │       f"Callback: {callback_number}",
   │       f"Booked: {iso_timestamp}",
   │       f"Call ID: {lifecycle.metadata.call_id}",
   │       f"Notes: {notes or '(none)'}",
   │     ]
   ├─> await client.create_event(start, end, summary, description)
   ├─> lifecycle.record_appointment_booked({
   │       "event_id": result.event_id,
   │       "start_iso": start.isoformat(),
   │       "end_iso": end.isoformat(),
   │       "html_link": result.html_link,
   │   })
   └─> return confirmation string to LLM

4. Agent: "You're all set for Tuesday April 28 at 2pm. Anything else?"
   Caller: hangs up.

5. lifecycle.on_call_ended() runs as always:
   ├─> metadata.mark_finalized()
   │   (outcomes already contains "appointment_booked"; no fallback needed)
   ├─> transcripts written
   ├─> if email.triggers.on_booking: dispatcher fires booking email(s)
   └─> if email.triggers.on_call_end: dispatcher fires summary email(s)
```

### 4.2 Session-scoped slot cache

`Receptionist` instance holds `self._offered_slots: set[str]`. Every time `check_availability` returns slots, their ISO strings are added. `book_appointment` validates `proposed_start_iso in self._offered_slots`.

This is enforced in code, not just prompt — the LLM cannot book a fabricated slot even if hallucinating. Cache lifetime = the Receptionist instance = duration of the call. Garbage-collected on session close.

### 4.3 New `CallMetadata` fields

```python
@dataclass
class CallMetadata:
    # ... existing fields ...
    outcomes: set[str] = field(default_factory=set)        # CHANGED from `outcome: str | None`
    appointment_booked: bool = False                       # NEW
    appointment_details: dict | None = None                # NEW — {event_id, start_iso, end_iso, html_link}
```

`appointment_booked` is a boolean convenience flag that shadows `"appointment_booked" in outcomes` — kept for quick checks in email template logic and for operator-readable JSON.

`appointment_details` contains the Google Calendar event reference so staff emails + transcripts can link back to the event.

### 4.4 New outcome in the valid-outcomes set

Valid outcomes become `{"hung_up", "message_taken", "transferred", "appointment_booked"}`. Membership-checked in `_add_outcome`; typos raise `ValueError`.

### 4.5 `on_booking` email trigger

When `lifecycle.on_call_ended()` fires and `config.email.triggers.on_booking is True` and `metadata.appointment_booked is True`:

- Iterate each configured `EmailChannel` in `messages.channels`
- Call `channel.deliver_booking(metadata, context)`
- Reuses the existing retry-with-backoff logic and `.failures/` record-writing from PR #2

The **booking** email is separate from the **call-end** email — both can fire on the same call when both triggers are on. Operators get two emails if they want both. The subject lines differ clearly ("New appointment booked" vs "Call summary") so nobody's confused.

### 4.6 Template rendering: multi-outcome calls

`build_call_end_email(metadata, context)` gains a helper:

```python
def _outcomes_display(outcomes: set[str]) -> str:
    labels = {
        "hung_up": "Hung up",
        "message_taken": "Message taken",
        "transferred": "Transferred",
        "appointment_booked": "Appointment booked",
    }
    return " + ".join(labels.get(o, o) for o in sorted(outcomes)) or "Unknown"
```

Subject example: `"Call from +15551234567 — Transferred + Appointment booked [Acme Dental]"`.

Body displays all outcomes on their own line:

```
Outcomes:
  - Transferred (Front Desk)
  - Appointment booked (Tue Apr 28 2:00 PM — calendar.google.com/...)
```

Transcript Markdown header gets the same treatment.

---

## 5. Error handling

Principle (inherited from PR #2): **caller experience is never degraded by backend failures**. When degradation is unavoidable, agent offers an intelligible alternative (typically `take_message`).

### 5.1 Per-component failure behavior

| Component | Failure mode | Handling |
|---|---|---|
| `auth.build_credentials` | Key file missing, unreadable, malformed, wrong schema | Raise `CalendarAuthError`. Agent **startup** fails if `calendar.enabled: true` — fail-fast is correct for a misconfigured operator. |
| `auth.build_credentials` (OAuth) | OAuth token file exists but with too-loose permissions (>0600 on Unix) | Raise at startup. Prevents shared-host attack surface. Windows skipped (no mode bits). |
| `auth.build_credentials` (OAuth) | Refresh token expired/revoked | Raise `CalendarAuthError` at first use in a call. `check_availability` catches, logs server-side (without leaking token), returns generic message to LLM. LLM pivots to take_message fallback. |
| `client.free_busy` | Network error, 503, timeout | Retry once via `retry_with_backoff` (`initial_delay=2, max_attempts=2`). On second failure, return `None`; tool returns generic "can't check right now" + take_message offer. |
| `client.free_busy` | 403 (no permission on calendar) | No retry. Same generic message + take_message offer. Server log includes calendar ID so operator can fix. |
| `client.free_busy` | 429 (rate limit) | Retry once with doubled delay. On second 429, return generic message. |
| `availability.find_slots` | Empty result (no slots near preferred time within window) | **Not an error.** Tool returns: "No openings that week; nearest available is May 5 at 10am. Does that work?" — suggests next-available outside the preferred window. LLM decides whether to pitch it. |
| `availability.find_slots` | Preferred time outside booking window (too soon / too far) | Tool returns specific message naming the constraint: "I can only book at least 2 hours out and no more than 30 days ahead — earliest I can offer is..." |
| `book_appointment` | `proposed_start_iso` not in session `_offered_slots` cache | Tool returns: "I need to verify that time is still available — let me check first." LLM is forced to call `check_availability` again. |
| `book_appointment` | Slot now busy (race between check and book) | Re-query free/busy for just this slot. If busy: tool returns "Unfortunately that slot just got taken — here are the nearest alternatives." LLM offers from the returned list. No retry. |
| `client.create_event` | 5xx, network error | Retry once. On second failure: "I'm having trouble booking right now. Can I take a message with the time you wanted, and someone will confirm?" LLM offers take_message. |
| `client.create_event` | 403 | No retry. Generic message + take_message offer. Operator-visible 403 in server logs. |
| `setup_cli` OAuth flow | User cancels, network error, invalid client ID | Prints specific error + exits nonzero. Does NOT partially write token file. Re-running from scratch is idempotent. |
| On-booking email dispatch | SMTP / Resend / webhook failure | Reuses `retry_with_backoff` + `.failures/` record pattern from PR #2. Booking itself still succeeds; notification just lands in `.failures/` on exhaustion. |

### 5.2 What's explicitly NOT retried

- 401/403 auth errors — retries don't help, operator must fix config
- 400 bad-request errors — our bug, not transient
- 404 on calendar_id — operator config issue

### 5.3 Logging contract (same as PR #2)

Every failure log includes `call_id`, `business_name`, `component` (e.g., `"booking.client"`), `error_type`, `error_detail` (sanitized). Calendar IDs are logged in non-auth errors but NOT in auth errors (to avoid side-channel info leak if credentials are mismatched to calendar).

### 5.4 Security-adjacent behavior

- Never log service-account private keys or OAuth refresh tokens under any exception path
- Calendar IDs treated as borderline sensitive (email-shaped). Log only in non-auth contexts.
- UNVERIFIED tag in event descriptions is permanent, intentionally visible to staff viewing the event
- OAuth token files written with `0600` permissions (Unix). Startup-time check fails if existing file has looser perms.

### 5.5 What's surfaced to the caller

Nothing, with two caller-visible fallbacks:

- **Booking failures** → "I'm having trouble with the calendar right now — can I take your info and have someone call back to confirm?" (pivots to take_message)
- **Slot-taken race** → "Unfortunately that slot just got taken — here are the nearest alternatives: [list]"

Caller never hears "error" language, API codes, or anything implying system brokenness. Same UX bar as PR #2.

### 5.6 What the LLM learns via system prompt (added in rollout step 10)

- When calling `check_availability`, always confirm caller's intended date + time verbally first
- Speak the parsed time back to the caller before calling `book_appointment`
- If `book_appointment` returns an error about time no longer available, offer alternatives from the returned list
- If calendar calls fail, smoothly pivot to take_message
- NEVER fabricate a time, confirmation code, or event ID

---

## 6. Testing strategy

### 6.1 Unit tests

| Test file | Covers |
|---|---|
| `tests/booking/test_config.py` | `CalendarConfig` parsing; `ServiceAccountAuth`/`OAuthAuth` discriminator behavior; `ConfigDict(extra="forbid")` rejection; `buffer_placement` validator; cross-section validator (on_booking requires email section); auth file existence check at config load |
| `tests/booking/test_auth.py` | `build_credentials` for service_account path (loads file, constructs `Credentials`); for OAuth path (loads refresh token, refreshes if expired); `CalendarAuthError` on missing/malformed files; permission check on OAuth file (0600 required on Unix, skipped on Windows) |
| `tests/booking/test_client.py` | `GoogleCalendarClient.free_busy` calls correct API shape, maps response into `list[(datetime, datetime)]`. `create_event` sends correct event body, returns `{event_id, html_link}`. Uses `pytest-mock` patching `discovery.build` return value; no real API calls. |
| `tests/booking/test_availability.py` | `find_slots` pure-function tests: finds slots inside business hours; respects `buffer_placement` variants with existing busy; enforces `earliest_booking_hours_ahead` + `booking_window_days`; **DST-crossover test** (a call on March 8 asking for March 10 at 9am NY time); prefers near-preferred slots over far; skips closed days |
| `tests/booking/test_booking.py` | `book_appointment`: rejects proposed_start_iso not in `_offered_slots`; detects slot-now-busy race (mock client returns the slot as busy on second check); builds event body with UNVERIFIED tag + call_id; returns `BookingResult` on success |
| `tests/booking/test_setup_cli.py` | Arg parsing, graceful fail on missing business. OAuth browser flow itself NOT unit-tested (documented in `tests/MANUAL.md`). |
| `tests/test_prompts.py` (expanded) | When `config.calendar.enabled: true`, system prompt includes CALENDAR section with tool descriptions + verbal-confirmation convention |
| `tests/test_lifecycle.py` (expanded) | `record_appointment_booked(details)` adds `"appointment_booked"` to outcomes set + populates `appointment_details`. Regression test: `metadata.outcomes` is set, not string. |
| `tests/email/test_templates.py` (expanded) | `build_booking_email(metadata, context)`: subject includes caller name + time, body includes Google Calendar link + UNVERIFIED tag + call_id. Multi-outcome rendering: "Transferred + Appointment booked". |
| `tests/messaging/test_email_channel.py` (expanded) | `EmailChannel.deliver_booking(metadata, context)` — parallel to existing `deliver_call_end`, with retry on transient errors |

### 6.2 Integration test

**`tests/integration/test_booking_flow.py::test_booking_flow_end_to_end`** — exercises `check_availability` → slot cached → `book_appointment` → metadata recorded → `on_booking` email fires. All without real Google API (mocks `GoogleCalendarClient`).

Specifically:
1. Construct `Receptionist` with a full config including `calendar` + `email.triggers.on_booking: true`
2. Call `check_availability` via the tool
3. Mock client returns a specific set of slots
4. Assert session-scoped `_offered_slots` cache is populated
5. Call `book_appointment` with one of the offered ISO strings
6. Assert event was created (mock records the call), `metadata.appointment_booked is True`, `"appointment_booked" in metadata.outcomes`
7. Trigger `lifecycle.on_call_ended` → assert booking email sender was invoked

### 6.3 Regression test from the outcomes breaking change (§2.6)

`tests/test_lifecycle.py::test_outcomes_is_a_set_not_a_string` — asserts `metadata.outcomes` is `set[str]`. Multi-outcome calls produce multi-element sets. Prevents accidental revert to the priority-based single-outcome shape.

### 6.4 NOT tested automatically

| Skipped | Why |
|---|---|
| Real Google API calls | Tests mock at `GoogleCalendarClient` boundary. Manual checklist covers real API. |
| OAuth browser flow | Launches real browser — not cost-effective to mock. Manual checklist. |
| Cross-business calendar isolation | Only tested via config — each business gets its own client by construction. Noted. |
| Timezone handling in Google's API | Our code's DST logic is tested; Google's API assumed correct. |

### 6.5 Manual validation additions to `tests/MANUAL.md`

New "Calendar integration" section:

- [ ] Service-account setup: download JSON, place in `secrets/<business>/`, start agent, test call → availability returned
- [ ] OAuth setup: `python -m receptionist.booking setup <business>`, complete browser flow, verify token file written with 0600 permissions
- [ ] Place a real booking during call → event appears on calendar with UNVERIFIED tag
- [ ] Slot-already-taken race: book a slot, immediately retry same slot → agent offers alternatives
- [ ] Outside booking window: ask for time beyond `booking_window_days` → agent refuses with explanation
- [ ] After-hours: ask for Saturday when closed → agent offers next available weekday slot
- [ ] `on_booking` email trigger fires → staff inbox gets "New appointment booked" with calendar link
- [ ] Multi-outcome: during call, transfer AND book appointment → `metadata.outcomes == {"transferred", "appointment_booked"}` in transcript JSON

### 6.6 Coverage target

Same as PR #2: every public function in `booking/` has at least one unit test covering success + main failure mode. Not chasing percentage — chasing "can I change this without anxiety."

---

## 7. Dependencies

### 7.1 New production dependencies

| Package | Min version | Purpose |
|---|---|---|
| `google-api-python-client` | `>=2.140` | Google Calendar API client |
| `google-auth` | `>=2.32` | Credentials + `google.oauth2.service_account` |
| `google-auth-oauthlib` | `>=1.2` | `InstalledAppFlow` for setup CLI browser consent |
| `python-dateutil` | `>=2.9` | Relative-date parsing in `check_availability` arg handling |

All Apache 2.0 licensed — AGPL-compatible. Widely maintained, no supply-chain concerns.

### 7.2 New dev dependencies

None. `pytest-mock` handles `googleapiclient` mocking.

### 7.3 New environment variables

None. All secrets on disk under `secrets/<business>/`.

---

## 8. Operations

### 8.1 New directory structure

```
secrets/                                 # NEW, gitignored
├── .gitkeep                             # tracked — directory must exist
└── <business>/
    ├── google-calendar-sa.json          # service-account key (type == service_account)
    ├── google-calendar-oauth.json       # OAuth refresh token (type == oauth)
    └── google-calendar-oauth-client.json # OAuth client ID/secret for this operator (type == oauth)
```

`.gitignore` additions:

```
secrets/*
!secrets/.gitkeep
```

Same negation pattern as `config/businesses/*.yaml` vs. `example-*.yaml` in PR #2.

### 8.2 OAuth client ID registration (one-time operator task)

Project ships NO shared OAuth client ID. Each operator registers their own in their Google Cloud Console. Rationale: shared client IDs in OSS projects historically get rate-limited or banned when traffic patterns diverge from what Google expects.

Setup CLI prompts for (or accepts via file) the operator-specific `client_id` and `client_secret` on first-run per business. Documented in `documentation/google-calendar-setup.md` with screenshots.

### 8.3 New CLI entrypoint

```
python -m receptionist.booking setup <business-slug>   # REQUIRED for OAuth auth type
python -m receptionist.booking verify <business-slug>  # STRETCH — sanity-checks auth + calendar access
```

`setup` walks through OAuth consent. `verify` (if shipped) calls `free_busy` for tomorrow and prints the result. Ship `setup` alone if tight on time.

### 8.4 Documentation to produce

- `documentation/google-calendar-setup.md` (NEW) — service-account setup (with Google Cloud screenshots), OAuth setup, troubleshooting 403s, rotating credentials
- `documentation/architecture.md` — add `booking/` subpackage section, updated package layout
- `documentation/CHANGELOG.md` — `[Unreleased]` entry under Added
- `HANDOFF.md` — new 2026-04-DD addendum for calendar integration
- `README.md` — "Appointment booking" section linking to setup guide
- `.env.example` — comment pointing to `secrets/` for calendar credentials (no new env vars)
- `tests/MANUAL.md` — Calendar integration section (§6.5)

---

## 9. Rollout sequencing

Each step ends with `pytest -q` green and a commit. No giant WIP.

1. **Foundation** — pyproject deps, `.gitignore` additions, `secrets/.gitkeep` scaffold
2. **Config schema** — `CalendarConfig` + auth discriminated union + cross-section validators + tests. Nothing uses it yet.
3. **Outcomes breaking change (§2.6)** — convert `CallMetadata.outcome: str` → `CallMetadata.outcomes: set[str]`. Update all existing code and ~30 test assertions. Full suite green. **Must land before any `booking/` code.**
4. **`booking/auth.py`** — `build_credentials` both paths + tests
5. **`booking/client.py`** — `GoogleCalendarClient` wrapper + tests (mocked)
6. **`booking/availability.py`** — pure `find_slots` + comprehensive tests including DST crossover
7. **`booking/booking.py`** — `book_appointment` logic, session cache validation, race handling + tests
8. **Lifecycle integration** — `CallLifecycle.record_appointment_booked(...)`, adds to outcomes + populates `appointment_details`. Tests.
9. **Tool integration** — Add `check_availability` + `book_appointment` `@function_tool` methods to `Receptionist`. Session-scoped `_offered_slots` set. Receptionist constructs `GoogleCalendarClient` lazily on first use, caches for duration of call.
10. **System prompt updates** — `prompts.py` emits CALENDAR section when enabled. Tests.
11. **Booking email trigger + template** — `build_booking_email`, `EmailChannel.deliver_booking`, fired from `lifecycle.on_call_ended` when `on_booking: true`. Tests.
12. **Setup CLI** — `booking/setup_cli.py` + `__main__.py`. Minimal unit tests (arg parsing); OAuth flow itself manual validation.
13. **Integration test** — `tests/integration/test_booking_flow.py` as in §6.2.
14. **Docs + CHANGELOG + MANUAL.md + HANDOFF addendum** — all documentation at once.
15. **Manual validation** — run `tests/MANUAL.md` Calendar section live against a real test Workspace calendar. Place a call, book an event, verify it lands.

Each step is independently valuable. Step 8 leaves testable booking core; step 11 leaves working end-to-end feature; step 13 leaves everything tested except real API; step 15 is the gate for merge.

---

## 10. Out of scope (tracked for future specs)

- Cancellations (GitHub issue if/when requested)
- Rescheduling
- Recurring appointments
- Multi-provider round-robin ("any dentist")
- SMS confirmation codes / caller verification
- Payment / deposit for no-show protection
- Outlook / Microsoft 365 / Apple Calendar
- Reminders (would need SMS provider)
- Admin web UI for bookings
- Cross-business calendar discovery (each business has its own `calendar_id`; no directory service)

---

## 11. Open questions

None at spec-approval time. Record new questions here if they arise during implementation.

---

## 12. References

- Design spec for PR #2 (call artifacts and multi-channel delivery): `docs/superpowers/specs/2026-04-23-call-artifacts-and-delivery-design.md`
- PR #2 implementation plan: `docs/superpowers/plans/2026-04-23-call-artifacts-and-delivery.md`
- GitHub issue #3: https://github.com/kirklandsig/AIReceptionist/issues/3 (originating request)
- GitHub issue #1: https://github.com/kirklandsig/AIReceptionist/issues/1 (user @marmo-75's initial ask, now closed)
- Google Calendar API v3 reference: https://developers.google.com/workspace/calendar/api/v3/reference
- google-auth-oauthlib InstalledAppFlow: https://googleapis.dev/python/google-auth-oauthlib/latest/reference/google_auth_oauthlib.flow.html
