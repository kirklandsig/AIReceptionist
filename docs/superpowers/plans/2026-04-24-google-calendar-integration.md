# Google Calendar Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `check_availability` and `book_appointment` function tools that query and write to a per-business Google Calendar during live calls, with both service-account and OAuth auth paths.

**Architecture:** New `receptionist/booking/` subpackage mirroring the PR #2 subpackage-per-capability pattern. Auth, client wrapper, availability logic (pure), booking logic, and setup CLI are separate modules. `agent.py` adds two new `@function_tool` methods with a session-scoped "offered slots" cache that enforces `check_availability → book_appointment` ordering in code, not prompt. Bundles one breaking change: `CallMetadata.outcome: str | None` → `CallMetadata.outcomes: set[str]` so multi-outcome calls (e.g. transferred AND booked) retain both data points.

**Tech Stack:** Python 3.11+, Pydantic v2, `google-api-python-client>=2.140`, `google-auth>=2.32`, `google-auth-oauthlib>=1.2`, `python-dateutil>=2.9`. Tests use `pytest` + `pytest-mock`.

**Reference spec:** `docs/superpowers/specs/2026-04-24-google-calendar-integration-design.md`

---

## Global conventions

- **Activate venv before every commit:** the project pre-commit hook runs pytest and requires it on PATH. First step of any session: `cd /c/Users/MDASR/Desktop/Projects/AIReceptionist && source venv/Scripts/activate`.
- **Never `--no-verify`.** If the hook fails, fix the failure, re-stage, create a NEW commit (don't amend).
- **Commit message style:** Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`). End every commit with:
  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- **File style:** `from __future__ import annotations` at top of every new module. Prefer `str | None` over `Optional[str]`. Use `logging.getLogger("receptionist")`. Stdlib-first imports, then third-party, then local, separated by blank lines.
- **Async:** any blocking I/O inside tool methods or lifecycle hooks wraps in `asyncio.to_thread`. Google API Python client is synchronous — ALL calls through `GoogleCalendarClient` use `asyncio.to_thread` internally.
- **TDD:** every implementation task is preceded by a failing test task. If committing tests standalone would fail the pre-commit pytest gate, bundle tests + implementation into one commit (same pattern PR #2 used).
- **Calendar scope:** `https://www.googleapis.com/auth/calendar.events` (narrower than full `calendar`). Hardcoded everywhere it's referenced.
- **Event notification behavior:** `sendUpdates="none"` on every `events().insert` call. The AI receptionist is booking on behalf of a caller; Google should NOT email the organizer's account about its own bookings.
- **Secrets path convention:** `secrets/<business-slug>/<file>.json`. Gitignored. `business-slug` is the YAML filename stem (e.g. `mdasr` for `config/businesses/mdasr.yaml`).

---

## Phase 0: Foundation

### Task 0.1: Add production and dev dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml`**

Replace the `dependencies` list (merging with the existing deps) and leave `optional-dependencies.dev` unchanged. The final `dependencies` block:

```toml
dependencies = [
    "livekit-agents>=1.5.0",
    "livekit-plugins-openai>=1.5.0",
    "livekit-plugins-noise-cancellation>=0.2.3",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "aiosmtplib>=3.0",
    "resend>=2.0",
    "httpx>=0.27",
    "aioboto3>=13.0",
    "aiofiles>=23.0",
    "google-api-python-client>=2.140",
    "google-auth>=2.32",
    "google-auth-oauthlib>=1.2",
    "python-dateutil>=2.9",
]
```

- [ ] **Step 2: Install the new deps**

Run:
```bash
source venv/Scripts/activate
pip install -e ".[dev]"
```
Expected: new Google libraries install; existing packages unchanged.

- [ ] **Step 3: Verify baseline tests still pass**

Run: `pytest -q`
Expected: all tests pass (current baseline on main is 124).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add dependencies for Google Calendar integration

Adds google-api-python-client (Calendar API client), google-auth
(service account + OAuth credentials), google-auth-oauthlib
(installed-app OAuth flow for the setup CLI), python-dateutil
(relative-date parsing in check_availability).

All Apache 2.0 licensed — AGPL-compatible. No new dev dependencies;
pytest-mock (already present) handles googleapiclient mocking.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 0.2: Create `secrets/` directory scaffold

**Files:**
- Create: `secrets/.gitkeep` (empty file)
- Modify: `.gitignore`

- [ ] **Step 1: Create `secrets/.gitkeep`**

```bash
mkdir -p secrets
touch secrets/.gitkeep
```

- [ ] **Step 2: Append to `.gitignore`**

Add these lines at the end:
```
# Per-business calendar credentials (service-account keys, OAuth tokens, OAuth client JSON)
secrets/*
!secrets/.gitkeep
```

- [ ] **Step 3: Verify the ignore rule works**

```bash
# Create a test file; it should be ignored
touch secrets/test.json
git status --short
# Should show .gitignore modified + secrets/.gitkeep new, but NOT secrets/test.json

rm secrets/test.json
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore secrets/.gitkeep
git commit -m "chore: ignore secrets/ except .gitkeep (for calendar credentials)

Per-business calendar credentials (service-account keys, OAuth refresh
tokens, OAuth client JSON) live in secrets/<business>/ and must never
be committed. Pattern uses a negation so the directory itself is
tracked via .gitkeep.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 1: Outcomes breaking change (spec §2.6)

**Phase intent:** Before any calendar code lands, convert `CallMetadata.outcome: str | None` to `CallMetadata.outcomes: set[str]`. The valid outcomes set gets a new member (`"appointment_booked"`) later, but this phase lands the SHAPE change so the rest of the plan targets the final shape. All existing tests must stay green.

### Task 1.1: Convert `CallMetadata` to use `outcomes: set[str]`

**Files:**
- Modify: `receptionist/transcript/metadata.py`
- Modify: `tests/transcript/test_metadata.py`

- [ ] **Step 1: Rewrite `CallMetadata` in `receptionist/transcript/metadata.py`**

Replace the current `CallMetadata` dataclass with:

```python
# receptionist/transcript/metadata.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# Valid outcome labels. Membership-checked in lifecycle._add_outcome to prevent
# silent typos; new outcomes must be added here AND in the _OUTCOME_LABELS map
# in receptionist/email/templates.py for their human-readable display.
VALID_OUTCOMES = {"hung_up", "message_taken", "transferred", "appointment_booked"}


@dataclass
class CallMetadata:
    call_id: str
    business_name: str
    caller_phone: str | None = None
    start_ts: str = ""
    end_ts: str | None = None
    duration_seconds: float | None = None
    outcomes: set[str] = field(default_factory=set)  # was `outcome: str | None`
    transfer_target: str | None = None
    message_taken: bool = False
    appointment_booked: bool = False  # NEW — convenience mirror of "appointment_booked" in outcomes
    appointment_details: dict | None = None  # NEW — {event_id, start_iso, end_iso, html_link}
    faqs_answered: list[str] = field(default_factory=list)
    languages_detected: set[str] = field(default_factory=set)
    recording_failed: bool = False
    recording_artifact: str | None = None

    def __post_init__(self):
        if not self.start_ts:
            self.start_ts = datetime.now(timezone.utc).isoformat()

    def mark_finalized(self) -> None:
        if self.end_ts is None:
            self.end_ts = datetime.now(timezone.utc).isoformat()
        if not self.outcomes:
            self.outcomes.add("hung_up")
        try:
            start = datetime.fromisoformat(self.start_ts)
            end = datetime.fromisoformat(self.end_ts)
            self.duration_seconds = (end - start).total_seconds()
        except ValueError:
            pass

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "business_name": self.business_name,
            "caller_phone": self.caller_phone,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "duration_seconds": self.duration_seconds,
            "outcomes": sorted(self.outcomes),  # sorted list for stable JSON
            "transfer_target": self.transfer_target,
            "message_taken": self.message_taken,
            "appointment_booked": self.appointment_booked,
            "appointment_details": self.appointment_details,
            "faqs_answered": list(self.faqs_answered),
            "languages_detected": sorted(self.languages_detected),
            "recording_failed": self.recording_failed,
            "recording_artifact": self.recording_artifact,
        }
```

- [ ] **Step 2: Update `tests/transcript/test_metadata.py`**

Replace the file contents with:

```python
# tests/transcript/test_metadata.py
from __future__ import annotations

from receptionist.transcript.metadata import CallMetadata, VALID_OUTCOMES


def test_metadata_defaults():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    assert md.start_ts
    assert md.end_ts is None
    assert md.outcomes == set()
    assert md.appointment_booked is False
    assert md.appointment_details is None
    assert md.faqs_answered == []
    assert md.languages_detected == set()


def test_metadata_finalize_sets_end_and_hung_up():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.mark_finalized()
    assert md.end_ts is not None
    assert md.outcomes == {"hung_up"}
    assert md.duration_seconds is not None
    assert md.duration_seconds >= 0


def test_metadata_finalize_preserves_existing_outcomes():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.outcomes.add("transferred")
    md.mark_finalized()
    assert md.outcomes == {"transferred"}  # hung_up NOT added when outcomes non-empty


def test_metadata_multi_outcome():
    """A call can be both transferred AND have an appointment booked."""
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.outcomes.add("transferred")
    md.outcomes.add("appointment_booked")
    md.mark_finalized()
    assert md.outcomes == {"transferred", "appointment_booked"}


def test_metadata_duration_computed_from_iso_timestamps():
    md = CallMetadata(
        call_id="room-1", business_name="Acme",
        start_ts="2026-04-23T14:30:00+00:00",
        end_ts="2026-04-23T14:32:30+00:00",
    )
    md.mark_finalized()
    assert md.duration_seconds == 150.0


def test_metadata_to_dict_outcomes_sorted_list():
    md = CallMetadata(call_id="room-1", business_name="Acme")
    md.outcomes.add("transferred")
    md.outcomes.add("appointment_booked")
    d = md.to_dict()
    assert d["outcomes"] == ["appointment_booked", "transferred"]  # alphabetically sorted


def test_metadata_to_dict_sorts_languages():
    md = CallMetadata(
        call_id="room-1", business_name="Acme",
        languages_detected={"es", "en"},
        faqs_answered=["Where are you located?"],
    )
    d = md.to_dict()
    assert d["languages_detected"] == ["en", "es"]
    assert d["faqs_answered"] == ["Where are you located?"]
    assert d["call_id"] == "room-1"


def test_metadata_to_dict_includes_new_fields():
    md = CallMetadata(
        call_id="room-1", business_name="Acme",
        appointment_booked=True,
        appointment_details={"event_id": "abc", "start_iso": "2026-04-24T14:00:00-04:00"},
    )
    d = md.to_dict()
    assert d["appointment_booked"] is True
    assert d["appointment_details"]["event_id"] == "abc"


def test_valid_outcomes_is_expected_set():
    """Regression: ensure the allowed outcome vocabulary matches the design spec."""
    assert VALID_OUTCOMES == {"hung_up", "message_taken", "transferred", "appointment_booked"}
```

- [ ] **Step 3: DO NOT commit yet**

This change breaks callers in `lifecycle.py`, `email/templates.py`, `transcript/formatter.py`, and several tests. Those updates happen in Tasks 1.2 through 1.6 which all bundle into a single commit. **Leave changes uncommitted and proceed to Task 1.2.**

### Task 1.2: Update `CallLifecycle` to use `_add_outcome`

**Files:**
- Modify: `receptionist/lifecycle.py`

- [ ] **Step 1: Rewrite `receptionist/lifecycle.py`**

Replace the current file with:

```python
# receptionist/lifecycle.py
from __future__ import annotations

import logging
from typing import Any

from receptionist.config import BusinessConfig
from receptionist.messaging.models import DispatchContext
from receptionist.recording.egress import (
    RecordingArtifact, RecordingHandle, start_recording, stop_recording,
)
from receptionist.transcript.capture import TranscriptCapture
from receptionist.transcript.metadata import CallMetadata, VALID_OUTCOMES
from receptionist.transcript.writer import (
    TranscriptWriteResult, write_transcript_files,
)

logger = logging.getLogger("receptionist")


class CallLifecycle:
    """Owns per-call state and the disconnect-time fan-out.

    Multi-outcome capable: a call that both transfers AND books an appointment
    records both in metadata.outcomes. No priority-based "winner" selection.
    """

    def __init__(
        self,
        *,
        config: BusinessConfig,
        call_id: str,
        caller_phone: str | None,
    ) -> None:
        self.config = config
        self.metadata = CallMetadata(
            call_id=call_id,
            business_name=config.business.name,
            caller_phone=caller_phone,
        )
        self.transcript_capture: TranscriptCapture | None = None
        self.recording_handle: RecordingHandle | None = None

    # --- tool-path recorders (called by Receptionist methods) ---

    def record_faq_answered(self, question: str) -> None:
        self.metadata.faqs_answered.append(question)

    def record_transfer(self, department_name: str) -> None:
        self.metadata.transfer_target = department_name
        self._add_outcome("transferred")

    def record_message_taken(self) -> None:
        self.metadata.message_taken = True
        self._add_outcome("message_taken")

    def record_appointment_booked(self, details: dict) -> None:
        """Called by the book_appointment tool after a successful event.insert.

        `details` must contain: event_id, start_iso, end_iso, html_link.
        """
        self.metadata.appointment_booked = True
        self.metadata.appointment_details = details
        self._add_outcome("appointment_booked")

    def _add_outcome(self, outcome: str) -> None:
        # Explicit membership check prevents silent drops if a future outcome
        # is added without updating VALID_OUTCOMES.
        if outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"Unknown outcome {outcome!r}; add it to VALID_OUTCOMES in "
                f"receptionist/transcript/metadata.py"
            )
        self.metadata.outcomes.add(outcome)

    # --- artifact wiring ---

    def attach_transcript_capture(self, session: Any) -> None:
        if self.config.transcripts and self.config.transcripts.enabled:
            self.transcript_capture = TranscriptCapture(session, self.metadata)

    async def start_recording_if_enabled(self, room_name: str) -> None:
        if self.config.recording is None or not self.config.recording.enabled:
            return
        self.recording_handle = await start_recording(
            room_name=room_name,
            config=self.config.recording,
            call_id=self.metadata.call_id,
        )
        if self.recording_handle is None:
            self.metadata.recording_failed = True

    # --- disconnect ---

    async def on_call_ended(self) -> None:
        self.metadata.mark_finalized()

        artifact: RecordingArtifact | None = None
        if self.recording_handle is not None:
            artifact = await stop_recording(self.recording_handle)
            if artifact is not None:
                self.metadata.recording_artifact = artifact.url

        transcript_result: TranscriptWriteResult | None = None
        segments = self.transcript_capture.segments if self.transcript_capture else []
        if self.config.transcripts is not None:
            transcript_result = await write_transcript_files(
                self.config.transcripts, self.metadata, segments
            )

        # Fan out email triggers
        if self.config.email:
            if self.config.email.triggers.on_call_end:
                await self._fire_call_end_email(artifact, transcript_result)
            if self.config.email.triggers.on_booking and self.metadata.appointment_booked:
                await self._fire_booking_email(artifact, transcript_result)

    async def _fire_call_end_email(
        self,
        artifact: RecordingArtifact | None,
        transcript_result: TranscriptWriteResult | None,
    ) -> None:
        """Call-end email goes to every EmailChannel target in messages.channels."""
        from receptionist.config import EmailChannel as EmailChannelConfig
        from receptionist.messaging.channels.email import EmailChannel

        email_channels = [c for c in self.config.messages.channels if isinstance(c, EmailChannelConfig)]
        if not email_channels or self.config.email is None:
            logger.info("on_call_end trigger configured but no email channel in messages.channels")
            return

        context = self._build_dispatch_context(artifact, transcript_result)
        for ch_cfg in email_channels:
            channel = EmailChannel(ch_cfg, self.config.email)
            try:
                await channel.deliver_call_end(self.metadata, context)
            except Exception as e:
                logger.error(
                    "Call-end email failed: %s", e,
                    extra={
                        "call_id": self.metadata.call_id,
                        "business_name": self.metadata.business_name,
                        "component": "lifecycle.call_end_email",
                    },
                )

    async def _fire_booking_email(
        self,
        artifact: RecordingArtifact | None,
        transcript_result: TranscriptWriteResult | None,
    ) -> None:
        """Booking email — fires only when metadata.appointment_booked is true."""
        from receptionist.config import EmailChannel as EmailChannelConfig
        from receptionist.messaging.channels.email import EmailChannel

        email_channels = [c for c in self.config.messages.channels if isinstance(c, EmailChannelConfig)]
        if not email_channels or self.config.email is None:
            logger.info("on_booking trigger configured but no email channel in messages.channels")
            return

        context = self._build_dispatch_context(artifact, transcript_result)
        for ch_cfg in email_channels:
            channel = EmailChannel(ch_cfg, self.config.email)
            try:
                await channel.deliver_booking(self.metadata, context)
            except Exception as e:
                logger.error(
                    "Booking email failed: %s", e,
                    extra={
                        "call_id": self.metadata.call_id,
                        "business_name": self.metadata.business_name,
                        "component": "lifecycle.booking_email",
                    },
                )

    def _build_dispatch_context(
        self,
        artifact: RecordingArtifact | None,
        transcript_result: TranscriptWriteResult | None,
    ) -> DispatchContext:
        return DispatchContext(
            transcript_json_path=str(transcript_result.json_path) if transcript_result and transcript_result.json_path else None,
            transcript_markdown_path=str(transcript_result.markdown_path) if transcript_result and transcript_result.markdown_path else None,
            recording_url=artifact.url if artifact else None,
            call_id=self.metadata.call_id,
            business_name=self.metadata.business_name,
        )
```

Key changes vs. the previous version:
- `_OUTCOME_PRIORITY` dict deleted
- `_set_outcome` renamed to `_add_outcome` (just `.add()`, no priority check)
- Membership validation points to `VALID_OUTCOMES` in metadata module (single source of truth)
- New `record_appointment_booked(details)` method
- `on_call_ended` now fires TWO email triggers independently (`on_call_end` and `on_booking`), both guarded by their respective conditions
- New `_fire_booking_email` helper, `_build_dispatch_context` extracted to avoid duplication

**DO NOT commit yet** — continue to Task 1.3.

### Task 1.3: Update `email/templates.py` for multi-outcome rendering

**Files:**
- Modify: `receptionist/email/templates.py`

- [ ] **Step 1: Rewrite `receptionist/email/templates.py`**

```python
# receptionist/email/templates.py
from __future__ import annotations

import html

from receptionist.messaging.models import Message, DispatchContext
from receptionist.transcript.metadata import CallMetadata


# Human-readable display labels for outcome values. Keep in sync with
# VALID_OUTCOMES in receptionist/transcript/metadata.py.
_OUTCOME_LABELS = {
    "hung_up": "Hung up",
    "message_taken": "Message taken",
    "transferred": "Transferred",
    "appointment_booked": "Appointment booked",
}


def _outcomes_display(outcomes: set[str] | list[str]) -> str:
    """Render a set of outcomes as a sorted human-readable string.

    Example: {"transferred", "appointment_booked"} -> "Appointment booked + Transferred"
    """
    if not outcomes:
        return "Unknown"
    labels = [_OUTCOME_LABELS.get(o, o) for o in sorted(outcomes)]
    return " + ".join(labels)


def build_message_email(
    message: Message, context: DispatchContext
) -> tuple[str, str, str]:
    """Return (subject, body_text, body_html)."""
    subject = f"New message from {message.caller_name} — {message.business_name}"

    body_text = (
        f"A caller left a message for {message.business_name}.\n"
        f"\n"
        f"Caller: {message.caller_name}\n"
        f"Callback: {message.callback_number}\n"
        f"Received: {message.timestamp}\n"
        f"\n"
        f"Message:\n"
        f"{message.message}\n"
    )
    if context.recording_url:
        body_text += f"\nRecording: {context.recording_url}\n"
    if context.transcript_markdown_path:
        body_text += f"Transcript: {context.transcript_markdown_path}\n"

    def e(s: str | None) -> str:
        return html.escape(s or "", quote=True)

    body_html = (
        f"<p>A caller left a message for <strong>{e(message.business_name)}</strong>.</p>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Caller</strong></td><td>{e(message.caller_name)}</td></tr>"
        f"<tr><td><strong>Callback</strong></td><td>{e(message.callback_number)}</td></tr>"
        f"<tr><td><strong>Received</strong></td><td>{e(message.timestamp)}</td></tr>"
        f"</table>"
        f"<h3>Message</h3>"
        f"<blockquote>{e(message.message)}</blockquote>"
    )
    if context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"
    if context.transcript_markdown_path:
        body_html += f"<p><strong>Transcript:</strong> {e(context.transcript_markdown_path)}</p>"

    return subject, body_text, body_html


def build_call_end_email(
    metadata: CallMetadata, context: DispatchContext
) -> tuple[str, str, str]:
    outcomes_str = _outcomes_display(metadata.outcomes)
    subject = f"Call from {metadata.caller_phone or 'Unknown'} — {outcomes_str} [{metadata.business_name}]"

    duration_str = _format_duration(metadata.duration_seconds)

    body_text = (
        f"Call summary for {metadata.business_name}.\n"
        f"\n"
        f"Caller: {metadata.caller_phone or 'Unknown'}\n"
        f"Start: {metadata.start_ts}\n"
        f"End: {metadata.end_ts or '(in progress)'}\n"
        f"Duration: {duration_str}\n"
        f"Outcomes: {outcomes_str}\n"
    )
    if metadata.transfer_target:
        body_text += f"Transferred to: {metadata.transfer_target}\n"
    if metadata.appointment_details:
        body_text += (
            f"Appointment: {metadata.appointment_details.get('start_iso', '?')}\n"
            f"  {metadata.appointment_details.get('html_link', '')}\n"
        )
    if metadata.faqs_answered:
        body_text += f"FAQs answered: {', '.join(metadata.faqs_answered)}\n"
    if metadata.languages_detected:
        body_text += f"Languages: {', '.join(sorted(metadata.languages_detected))}\n"
    if context.recording_url:
        body_text += f"\nRecording: {context.recording_url}\n"
    if context.transcript_markdown_path:
        body_text += f"Transcript: {context.transcript_markdown_path}\n"

    def e(s) -> str:
        return html.escape(str(s) if s is not None else "", quote=True)

    body_html = (
        f"<h2>Call summary — {e(metadata.business_name)}</h2>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Caller</strong></td><td>{e(metadata.caller_phone or 'Unknown')}</td></tr>"
        f"<tr><td><strong>Start</strong></td><td>{e(metadata.start_ts)}</td></tr>"
        f"<tr><td><strong>End</strong></td><td>{e(metadata.end_ts or '(in progress)')}</td></tr>"
        f"<tr><td><strong>Duration</strong></td><td>{e(duration_str)}</td></tr>"
        f"<tr><td><strong>Outcomes</strong></td><td>{e(outcomes_str)}</td></tr>"
        f"</table>"
    )
    if context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"

    return subject, body_text, body_html


def build_booking_email(
    metadata: CallMetadata, context: DispatchContext
) -> tuple[str, str, str]:
    """Build email fired by the on_booking trigger. Requires metadata.appointment_details."""
    details = metadata.appointment_details or {}
    start_iso = details.get("start_iso", "?")
    html_link = details.get("html_link", "")
    caller = metadata.caller_phone or "Unknown"

    subject = f"New appointment booked: {caller} — {start_iso} [{metadata.business_name}]"

    body_text = (
        f"A new appointment has been booked for {metadata.business_name}.\n"
        f"\n"
        f"Caller: {caller}\n"
        f"Start: {start_iso}\n"
        f"End: {details.get('end_iso', '?')}\n"
        f"Event: {html_link}\n"
        f"Call ID: {metadata.call_id}\n"
        f"\n"
        f"Note: The caller's identity was NOT verified. Please confirm by calling "
        f"back at {caller} before relying on this booking.\n"
    )
    if context.transcript_markdown_path:
        body_text += f"\nCall transcript: {context.transcript_markdown_path}\n"
    if context.recording_url:
        body_text += f"Recording: {context.recording_url}\n"

    def e(s) -> str:
        return html.escape(str(s) if s is not None else "", quote=True)

    body_html = (
        f"<h2>New appointment booked — {e(metadata.business_name)}</h2>"
        f"<table cellpadding='4'>"
        f"<tr><td><strong>Caller</strong></td><td>{e(caller)}</td></tr>"
        f"<tr><td><strong>Start</strong></td><td>{e(start_iso)}</td></tr>"
        f"<tr><td><strong>End</strong></td><td>{e(details.get('end_iso', '?'))}</td></tr>"
        f"<tr><td><strong>Call ID</strong></td><td>{e(metadata.call_id)}</td></tr>"
        f"</table>"
    )
    if html_link:
        body_html += f"<p><a href='{e(html_link)}'>Open in Google Calendar</a></p>"
    body_html += (
        f"<p><em>The caller's identity was NOT verified. Please confirm by calling back "
        f"at {e(caller)} before relying on this booking.</em></p>"
    )
    if context.transcript_markdown_path:
        body_html += f"<p><strong>Transcript:</strong> {e(context.transcript_markdown_path)}</p>"
    if context.recording_url:
        body_html += f"<p><strong>Recording:</strong> <a href='{e(context.recording_url)}'>{e(context.recording_url)}</a></p>"

    return subject, body_text, body_html


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
```

Key additions vs. previous version:
- New `_outcomes_display(outcomes)` helper — single source of truth for outcome → human label translation
- `_OUTCOME_LABELS` dict — keep in sync with `VALID_OUTCOMES` in metadata.py
- `build_call_end_email` now uses `_outcomes_display(metadata.outcomes)` instead of the old single-outcome logic; body renders appointment details when present
- New `build_booking_email(metadata, context)` function — the on_booking trigger template

**DO NOT commit yet** — continue to Task 1.4.

### Task 1.4: Update `transcript/formatter.py` for multi-outcome rendering

**Files:**
- Modify: `receptionist/transcript/formatter.py`

- [ ] **Step 1: Open `receptionist/transcript/formatter.py` and locate the Markdown header section**

Find the block that currently reads (approximately):
```python
    if metadata.outcome:
        lines.append(f"- Outcome: {metadata.outcome}")
```

- [ ] **Step 2: Replace that block with multi-outcome logic**

Replace the `if metadata.outcome:` block with:

```python
    if metadata.outcomes:
        lines.append(f"- Outcomes: {', '.join(sorted(metadata.outcomes))}")
    if metadata.appointment_details:
        lines.append(f"- Appointment: {metadata.appointment_details.get('start_iso', '?')}")
```

That replaces the single "Outcome:" line with a comma-joined "Outcomes:" line and adds an appointment line when applicable. Everything else in `to_markdown` stays the same.

**DO NOT commit yet** — continue to Task 1.5.

### Task 1.5: Update existing tests that asserted on `metadata.outcome`

**Files:**
- Modify: `tests/test_lifecycle.py`
- Modify: `tests/transcript/test_formatter.py`
- Modify: `tests/email/test_templates.py`
- Modify: `tests/integration/test_call_flow.py`

**Note:** The current tests assert on a scalar `metadata.outcome`. They need to become `in metadata.outcomes` set-membership checks. Each file is updated below exhaustively.

- [ ] **Step 1: Rewrite `tests/test_lifecycle.py`**

Replace the entire file with:

```python
# tests/test_lifecycle.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.lifecycle import CallLifecycle
from receptionist.transcript.metadata import CallMetadata


@pytest.fixture
def config(v2_yaml):
    from receptionist.config import BusinessConfig
    return BusinessConfig.from_yaml_string(v2_yaml)


def test_lifecycle_constructs_metadata_with_call_id(config):
    lifecycle = CallLifecycle(config=config, call_id="room-abc", caller_phone="+15551112222")
    assert lifecycle.metadata.call_id == "room-abc"
    assert lifecycle.metadata.business_name == "Test Dental"
    assert lifecycle.metadata.caller_phone == "+15551112222"


def test_lifecycle_record_faq_populates_metadata(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_faq_answered("hours")
    lifecycle.record_faq_answered("insurance")
    assert lifecycle.metadata.faqs_answered == ["hours", "insurance"]


def test_lifecycle_record_transfer_adds_outcome(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_transfer("Front Desk")
    assert lifecycle.metadata.transfer_target == "Front Desk"
    assert "transferred" in lifecycle.metadata.outcomes


def test_lifecycle_record_message_taken_adds_outcome(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_message_taken()
    assert lifecycle.metadata.message_taken is True
    assert "message_taken" in lifecycle.metadata.outcomes


def test_lifecycle_record_appointment_booked_adds_outcome(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    details = {
        "event_id": "evt123",
        "start_iso": "2026-04-28T14:00:00-04:00",
        "end_iso": "2026-04-28T14:30:00-04:00",
        "html_link": "https://calendar.google.com/event?eid=abc",
    }
    lifecycle.record_appointment_booked(details)
    assert lifecycle.metadata.appointment_booked is True
    assert lifecycle.metadata.appointment_details == details
    assert "appointment_booked" in lifecycle.metadata.outcomes


def test_lifecycle_multi_outcome_transfer_and_booking(config):
    """A call can be both transferred AND book an appointment. Both outcomes recorded."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_transfer("Front Desk")
    lifecycle.record_appointment_booked({
        "event_id": "e", "start_iso": "t1", "end_iso": "t2", "html_link": "url",
    })
    assert lifecycle.metadata.outcomes == {"transferred", "appointment_booked"}


def test_lifecycle_add_outcome_rejects_unknown(config):
    """Regression: _add_outcome must raise on outcomes not in VALID_OUTCOMES."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    with pytest.raises(ValueError, match="Unknown outcome"):
        lifecycle._add_outcome("abducted_by_aliens")


def test_outcomes_is_a_set_not_a_string(config):
    """Regression guard against reverting to the old priority-based single-outcome shape."""
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    assert isinstance(lifecycle.metadata.outcomes, set)
    # Must support multi-element population
    lifecycle.record_transfer("Front Desk")
    lifecycle.record_message_taken()
    assert len(lifecycle.metadata.outcomes) == 2


@pytest.mark.asyncio
async def test_lifecycle_on_call_ended_finalizes_metadata(config):
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    await lifecycle.on_call_ended()
    assert lifecycle.metadata.end_ts is not None
    assert lifecycle.metadata.outcomes == {"hung_up"}
    assert lifecycle.metadata.duration_seconds is not None


@pytest.mark.asyncio
async def test_lifecycle_on_call_ended_writes_transcript(tmp_path, config):
    from receptionist.config import TranscriptsConfig, TranscriptStorageConfig
    config = config.model_copy(update={
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path)),
            formats=["json", "markdown"],
        ),
    })
    lifecycle = CallLifecycle(config=config, call_id="room-x", caller_phone=None)
    await lifecycle.on_call_ended()
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert len(list(tmp_path.glob("*.md"))) == 1
```

- [ ] **Step 2: Update `tests/transcript/test_formatter.py`**

Find the test(s) that assert on outcome content. They currently use `metadata.outcome = "X"`. Update them to add to the set.

Open the file and look for any line that sets or asserts `outcome` (singular). Example transformations:

- `md.outcome = "hung_up"` becomes `md.outcomes.add("hung_up")`
- `assert "Outcome: hung_up" in out` becomes `assert "Outcomes: hung_up" in out`

The existing `_metadata()` fixture in the file needs updating too — the test data builds a `CallMetadata` object. After Task 1.1, that object uses `outcomes: set[str]`. Any fixture that currently does `CallMetadata(..., outcome="foo")` must change to either (a) omit the outcome at construction and `.outcomes.add("foo")` after, or (b) pass `outcomes={"foo"}` if the constructor accepts it (it does — `outcomes` is a field).

Specifically: find the fixture `_metadata()` in this file and ensure any outcome references use the set shape. If a test asserts `"Outcome: message_taken" in out`, change to `"Outcomes: message_taken" in out` (note the 's').

- [ ] **Step 3: Update `tests/email/test_templates.py`**

Same pattern. Find outcome references and update:

- `outcome="message_taken"` in `CallMetadata(...)` constructor → `outcomes={"message_taken"}`
- Any assertion like `"message_taken" in subject` or `"Message taken" in subject` stays — the `_outcomes_display` helper still produces those labels
- Add new test for multi-outcome subject:

```python
def test_call_end_email_subject_multi_outcome():
    from receptionist.email.templates import build_call_end_email
    from receptionist.messaging.models import DispatchContext
    md = CallMetadata(
        call_id="r", business_name="Acme", caller_phone="+1",
        start_ts="2026-04-23T14:30:00+00:00",
        end_ts="2026-04-23T14:32:00+00:00",
        duration_seconds=120.0,
        outcomes={"transferred", "appointment_booked"},
    )
    subject, body_text, _ = build_call_end_email(md, DispatchContext())
    # Rendered alphabetically: appointment_booked first, then transferred
    assert "Appointment booked + Transferred" in subject


def test_build_booking_email_includes_event_link():
    from receptionist.email.templates import build_booking_email
    from receptionist.messaging.models import DispatchContext
    md = CallMetadata(
        call_id="r", business_name="Acme", caller_phone="+15551112222",
        appointment_booked=True,
        appointment_details={
            "event_id": "evt1",
            "start_iso": "2026-04-28T14:00:00-04:00",
            "end_iso": "2026-04-28T14:30:00-04:00",
            "html_link": "https://calendar.google.com/event?eid=abc",
        },
    )
    subject, body_text, body_html = build_booking_email(md, DispatchContext())
    assert "appointment booked" in subject.lower()
    assert "+15551112222" in subject
    assert "https://calendar.google.com/event?eid=abc" in body_text
    assert "UNVERIFIED" in body_text or "was NOT verified" in body_text  # UNVERIFIED disclaimer
    assert "calendar.google.com" in body_html
```

The existing `_metadata()` fixture in this file should keep working after the `outcome="..."` → `outcomes={"..."}` rename.

- [ ] **Step 4: Update `tests/integration/test_call_flow.py`**

Find any assertion on `lifecycle.metadata.outcome` (singular) and change to set-membership. Specifically the test `test_call_end_writes_transcript_and_fires_call_end_email` currently asserts:

```python
assert lifecycle.metadata.outcome == "hung_up"
```

Change to:

```python
assert lifecycle.metadata.outcomes == {"hung_up"}
```

Also `assert "hung_up" in kwargs["subject"].lower() or "Hung up" in kwargs["subject"]` — keep that assertion as-is (the display label is still "Hung up").

Look for any other `metadata.outcome` references in the file and apply the same set transformation.

- [ ] **Step 5: Commit ALL of Phase 1**

Now commit the full Phase 1 change (Tasks 1.1-1.5 as one atomic change). First verify tests pass:

```bash
source venv/Scripts/activate
pytest -q
```
Expected: all tests green (124 or so — same as before the refactor, plus the new tests in `test_metadata.py` and `test_lifecycle.py` and `test_templates.py`).

If anything fails, debug before committing. Common failure modes:
- Typo in `outcomes` (plural) vs `outcome` (singular) somewhere
- A test still passes `outcome="x"` to `CallMetadata(...)` — change to `outcomes={"x"}`
- A Markdown/email template still references `metadata.outcome` — should be `metadata.outcomes`

Then commit:

```bash
git add receptionist/transcript/metadata.py \
        receptionist/lifecycle.py \
        receptionist/email/templates.py \
        receptionist/transcript/formatter.py \
        tests/test_lifecycle.py \
        tests/transcript/test_metadata.py \
        tests/transcript/test_formatter.py \
        tests/email/test_templates.py \
        tests/integration/test_call_flow.py
git commit -m "refactor: CallMetadata.outcome (str) -> outcomes (set[str])

A call can have multiple outcomes: transferred AND book an appointment,
for example. The previous priority-based _OUTCOME_PRIORITY dict picked
one winner and lost the other. This refactor changes the field to a
set and records every event, so operators and email summaries see the
complete picture.

Also lands the appointment_booked outcome + metadata.appointment_details
field + metadata.appointment_booked bool (in preparation for the
Calendar integration — nothing populates these yet in this commit).
Also lands CallLifecycle.record_appointment_booked and the on_booking
email trigger fan-out in on_call_ended (still no callers in this
commit — wiring only).

Breaking change: metadata.to_dict()[\"outcome\"] is now
metadata.to_dict()[\"outcomes\"] (sorted list). Bundled now rather than
in a later calendar-only commit because a set of outcomes is the
right shape for THIS call-end summary too, not just bookings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2: Config schema

### Task 2.1: Add calendar Pydantic models to `receptionist/config.py`

**Files:**
- Modify: `receptionist/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Open `receptionist/config.py`** and find the `EmailTriggers` class.

Add a new field to `EmailTriggers`:

```python
class EmailTriggers(BaseModel):
    on_message: bool = True
    on_call_end: bool = False
    on_booking: bool = False  # NEW — email staff when an appointment is booked
```

- [ ] **Step 2: Add the calendar models** — insert after the existing `RetentionConfig` class (near the bottom of the file, before `BusinessConfig`):

```python
# ---------------------------------------------------------------------------
# Calendar — Google Calendar integration
# ---------------------------------------------------------------------------

class ServiceAccountAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["service_account"]
    service_account_file: str


class OAuthAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["oauth"]
    oauth_token_file: str


CalendarAuth = Annotated[
    Union[ServiceAccountAuth, OAuthAuth],
    Field(discriminator="type"),
]


class CalendarConfig(BaseModel):
    enabled: bool
    calendar_id: str = "primary"
    auth: CalendarAuth
    appointment_duration_minutes: int = Field(default=30, gt=0)
    buffer_minutes: int = Field(default=15, ge=0)
    buffer_placement: Literal["before", "after", "both"] = "after"
    booking_window_days: int = Field(default=30, gt=0)
    earliest_booking_hours_ahead: int = Field(default=2, ge=0)

    @model_validator(mode="after")
    def validate_auth_file_exists(self) -> CalendarConfig:
        """If enabled, require the configured auth file to exist on disk.

        Fail fast at agent startup, not at first call.
        """
        if not self.enabled:
            return self
        path_str = (
            self.auth.service_account_file
            if isinstance(self.auth, ServiceAccountAuth)
            else self.auth.oauth_token_file
        )
        path = Path(path_str)
        if not path.exists():
            raise ValueError(
                f"calendar auth file not found: {path_str}. "
                f"Did you run `python -m receptionist.booking setup {{business-slug}}`?"
            )
        return self
```

- [ ] **Step 3: Update `BusinessConfig`** — add a new field and extend the cross-section validator:

```python
class BusinessConfig(BaseModel):
    business: BusinessInfo
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    languages: LanguagesConfig = Field(default_factory=LanguagesConfig)
    greeting: str
    personality: str
    hours: WeeklyHours
    after_hours_message: str
    routing: list[RoutingEntry]
    faqs: list[FAQEntry]
    messages: MessagesConfig
    recording: RecordingConfig | None = None
    transcripts: TranscriptsConfig | None = None
    email: EmailConfig | None = None
    calendar: CalendarConfig | None = None  # NEW
    retention: RetentionConfig = Field(default_factory=RetentionConfig)

    @model_validator(mode="after")
    def validate_cross_section(self) -> BusinessConfig:
        needs_email = any(c.type == "email" for c in self.messages.channels)
        if self.email:
            if self.email.triggers.on_call_end:
                needs_email = True
            if self.email.triggers.on_booking:
                needs_email = True
        if needs_email and self.email is None:
            raise ValueError(
                "email channel or on_call_end/on_booking trigger is configured but "
                "no top-level `email` section is present"
            )
        # NEW: on_booking trigger requires calendar enabled
        if self.email and self.email.triggers.on_booking and (
            self.calendar is None or not self.calendar.enabled
        ):
            raise ValueError(
                "email.triggers.on_booking is true but calendar is not enabled. "
                "Enable calendar or disable the on_booking trigger."
            )
        return self
```

- [ ] **Step 4: Add new tests** to `tests/test_config.py` — append at the end:

```python
# ---- calendar config tests ----


def _calendar_yaml_fragment(auth_block: str) -> str:
    """Returns a full v2 YAML with calendar enabled and the given auth block."""
    return f"""
business: {{ name: "X", type: "x", timezone: "America/New_York" }}
voice: {{ voice_id: "marin" }}
languages: {{ primary: "en", allowed: ["en"] }}
greeting: "Hi"
personality: "Nice"
hours: {{ monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }}
after_hours_message: "Closed"
routing: []
faqs: []
messages: {{ channels: [{{type: "file", file_path: "./m/"}}] }}
calendar:
  enabled: true
  calendar_id: "primary"
  {auth_block}
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
"""


def test_calendar_service_account_auth_requires_file(tmp_path, monkeypatch):
    """calendar.enabled=True + service_account auth: file must exist."""
    # File does not exist yet — should fail
    nonexistent = tmp_path / "sa.json"
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"service_account\", service_account_file: \"{nonexistent}\" }}"
    )
    with pytest.raises(Exception, match="calendar auth file not found"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_calendar_service_account_auth_with_existing_file(tmp_path):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text('{"dummy": "content"}', encoding="utf-8")
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"service_account\", service_account_file: \"{sa_file}\" }}"
    )
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.calendar.enabled is True
    assert config.calendar.auth.type == "service_account"
    assert config.calendar.auth.service_account_file == str(sa_file)
    assert config.calendar.buffer_placement == "after"


def test_calendar_oauth_auth_with_existing_file(tmp_path):
    token_file = tmp_path / "oauth.json"
    token_file.write_text('{"token": "x"}', encoding="utf-8")
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"oauth\", oauth_token_file: \"{token_file}\" }}"
    )
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.calendar.auth.type == "oauth"


def test_calendar_extra_fields_rejected(tmp_path):
    """ConfigDict(extra=forbid) on auth variants: extra fields cause ValidationError."""
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"service_account\", "
        f"service_account_file: \"{sa_file}\", "
        f"oauth_token_file: \"/fake/path\" }}"  # bogus extra field
    )
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(yaml_text)


def test_calendar_disabled_skips_file_check():
    """If calendar.enabled is False, auth file existence is not checked."""
    yaml_text = """
business: { name: "X", type: "x", timezone: "America/New_York" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
calendar:
  enabled: false
  auth:
    type: "service_account"
    service_account_file: "/does/not/exist/sa.json"
"""
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.calendar.enabled is False


def test_on_booking_trigger_requires_calendar_enabled(tmp_path):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")
    yaml_text = f"""
business: {{ name: "X", type: "x", timezone: "America/New_York" }}
voice: {{ voice_id: "marin" }}
languages: {{ primary: "en", allowed: ["en"] }}
greeting: "Hi"
personality: "Nice"
hours: {{ monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }}
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./m/"
    - type: "email"
      to: ["a@b.c"]
email:
  from: "noreply@example.com"
  sender:
    type: "smtp"
    smtp: {{ host: "h", port: 587, username: "u", password: "p", use_tls: true }}
  triggers:
    on_booking: true
# NO calendar section — validation should fail
"""
    with pytest.raises(Exception, match="on_booking"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_buffer_placement_validator_accepts_valid():
    # already covered structurally by the other calendar tests; this explicit test
    # is cheap and guards against accidental Literal narrowing.
    from receptionist.config import CalendarConfig, ServiceAccountAuth
    cfg = CalendarConfig(
        enabled=False,  # avoids file check
        calendar_id="primary",
        auth=ServiceAccountAuth(type="service_account", service_account_file="/tmp/sa.json"),
        buffer_placement="both",
    )
    assert cfg.buffer_placement == "both"
```

- [ ] **Step 5: Run tests**

```bash
source venv/Scripts/activate
pytest tests/test_config.py -v
```
Expected: all tests pass (existing + 7 new calendar tests).

Also run the full suite:

```bash
pytest -q
```
Expected: full suite passes.

- [ ] **Step 6: Commit**

```bash
git add receptionist/config.py tests/test_config.py
git commit -m "feat: Pydantic models for calendar integration config

Adds CalendarConfig + discriminated auth union (ServiceAccountAuth |
OAuthAuth) + on_booking EmailTrigger. ConfigDict(extra=\"forbid\") on
auth variants catches misconfigured copy-paste (leaving an
oauth_token_file in a service_account block, etc.).

Cross-section validator: on_booking trigger requires calendar enabled.
Auth file existence check at config load (fail fast at agent startup,
not at first call).

Nothing uses this yet — booking/ subpackage lands in later phases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.2: Update `example-dental.yaml` with commented calendar section

**Files:**
- Modify: `config/businesses/example-dental.yaml`

- [ ] **Step 1: Append to the file** (after the existing `retention:` block at the bottom):

```yaml

# Google Calendar integration (appointment booking). Requires setup:
# 1. Google Cloud: enable Calendar API, create a service account OR OAuth client
# 2. Share the target calendar with the service account email (for service_account auth)
# 3. Download credentials to secrets/<business-slug>/
# 4. For OAuth auth, run `python -m receptionist.booking setup <business-slug>`
# See documentation/google-calendar-setup.md for step-by-step instructions.
#
# calendar:
#   enabled: true
#   calendar_id: "primary"                 # or a specific calendar ID
#   auth:
#     type: "service_account"              # or "oauth"
#     service_account_file: "./secrets/example-dental/google-calendar-sa.json"
#     # OR:
#     # type: "oauth"
#     # oauth_token_file: "./secrets/example-dental/google-calendar-oauth.json"
#   appointment_duration_minutes: 30
#   buffer_minutes: 15
#   buffer_placement: "after"              # "before" | "after" | "both"
#   booking_window_days: 30
#   earliest_booking_hours_ahead: 2
```

- [ ] **Step 2: Verify the file still parses**

```bash
source venv/Scripts/activate
python -c "from receptionist.config import load_config; print(load_config('config/businesses/example-dental.yaml').business.name)"
```
Expected: `Acme Dental`.

- [ ] **Step 3: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add config/businesses/example-dental.yaml
git commit -m "docs: add commented calendar section to example-dental.yaml

Shows the two auth options (service_account, oauth), booking-rule
fields, and a pointer to the setup guide.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3: Booking package skeleton + auth

### Task 3.1: Create `receptionist/booking/` package skeleton with models

**Files:**
- Create: `receptionist/booking/__init__.py`
- Create: `receptionist/booking/models.py`

- [ ] **Step 1: Create `receptionist/booking/__init__.py`** (empty file)

- [ ] **Step 2: Create `receptionist/booking/models.py`**

```python
# receptionist/booking/models.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SlotProposal:
    """A proposed time slot returned by availability.find_slots().

    start_iso / end_iso are RFC 3339 strings including timezone offset
    (e.g. "2026-04-28T14:00:00-04:00"). These are exactly what we hand to
    the LLM, hand back for booking validation, and send to Google as
    event.start.dateTime / end.dateTime.
    """

    start_iso: str
    end_iso: str


@dataclass
class BookingResult:
    """Returned by booking.book_appointment() after a successful event creation."""

    event_id: str
    start_iso: str
    end_iso: str
    html_link: str
```

- [ ] **Step 3: Smoke-test import**

```bash
source venv/Scripts/activate
python -c "from receptionist.booking.models import SlotProposal, BookingResult; print(SlotProposal(start_iso='a', end_iso='b'))"
```
Expected: `SlotProposal(start_iso='a', end_iso='b')`

- [ ] **Step 4: Run full suite**

```bash
pytest -q
```
Expected: all pass (no new tests yet; sanity check).

- [ ] **Step 5: Commit**

```bash
git add receptionist/booking/__init__.py receptionist/booking/models.py
git commit -m "feat: add receptionist/booking/ package with SlotProposal, BookingResult

Tiny scaffold — dataclasses used as return types in later tasks. Named
\`booking\` not \`calendar\` to avoid stdlib shadowing (we hit that
trap with \`email/\` in PR #2).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3.2: Implement `booking/auth.py` with tests

**Files:**
- Create: `tests/booking/__init__.py`
- Create: `tests/booking/test_auth.py`
- Create: `receptionist/booking/auth.py`

- [ ] **Step 1: Create `tests/booking/__init__.py`** (empty)

- [ ] **Step 2: Write `tests/booking/test_auth.py`**

```python
# tests/booking/test_auth.py
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from receptionist.booking.auth import (
    CalendarAuthError, build_credentials, SCOPES,
)
from receptionist.config import OAuthAuth, ServiceAccountAuth


def test_scopes_is_events_only():
    """Least-privilege: only calendar.events scope, not full calendar."""
    assert SCOPES == ["https://www.googleapis.com/auth/calendar.events"]


def test_build_credentials_service_account(tmp_path):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps({
        "type": "service_account",
        "project_id": "test",
        "private_key_id": "x",
        "private_key": "-----BEGIN FAKE KEY-----\n...\n",
        "client_email": "test@example.iam.gserviceaccount.com",
        "client_id": "123",
    }), encoding="utf-8")

    fake_creds = MagicMock(name="service_account_creds")
    with patch(
        "receptionist.booking.auth.service_account.Credentials.from_service_account_file",
        return_value=fake_creds,
    ) as mock_from_file:
        auth = ServiceAccountAuth(type="service_account", service_account_file=str(sa_file))
        creds = build_credentials(auth)

    assert creds is fake_creds
    mock_from_file.assert_called_once_with(str(sa_file), scopes=SCOPES)


def test_build_credentials_service_account_missing_file(tmp_path):
    """Missing file raises CalendarAuthError, not a cryptic FileNotFoundError."""
    auth = ServiceAccountAuth(
        type="service_account",
        service_account_file=str(tmp_path / "does-not-exist.json"),
    )
    with pytest.raises(CalendarAuthError, match="not found"):
        build_credentials(auth)


def test_build_credentials_oauth_loads_saved_token(tmp_path):
    token_file = tmp_path / "oauth.json"
    token_file.write_text(json.dumps({
        "token": "access",
        "refresh_token": "refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "c",
        "client_secret": "s",
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
    }), encoding="utf-8")

    fake_creds = MagicMock(name="oauth_creds", valid=True)
    with patch(
        "receptionist.booking.auth.Credentials.from_authorized_user_file",
        return_value=fake_creds,
    ) as mock_from_file:
        auth = OAuthAuth(type="oauth", oauth_token_file=str(token_file))
        creds = build_credentials(auth)

    assert creds is fake_creds
    mock_from_file.assert_called_once_with(str(token_file), SCOPES)


def test_build_credentials_oauth_refreshes_expired(tmp_path):
    """If the loaded Credentials are expired but have a refresh_token, refresh them."""
    token_file = tmp_path / "oauth.json"
    token_file.write_text('{"refresh_token": "r"}', encoding="utf-8")

    fake_creds = MagicMock(
        name="oauth_creds", valid=False, expired=True, refresh_token="r",
    )
    with patch(
        "receptionist.booking.auth.Credentials.from_authorized_user_file",
        return_value=fake_creds,
    ):
        auth = OAuthAuth(type="oauth", oauth_token_file=str(token_file))
        build_credentials(auth)

    fake_creds.refresh.assert_called_once()


def test_build_credentials_oauth_missing_file(tmp_path):
    auth = OAuthAuth(
        type="oauth",
        oauth_token_file=str(tmp_path / "missing.json"),
    )
    with pytest.raises(CalendarAuthError, match="not found"):
        build_credentials(auth)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows does not enforce POSIX mode bits")
def test_build_credentials_oauth_rejects_loose_permissions(tmp_path):
    """0600 required on Unix — looser perms fail to prevent shared-host leakage."""
    token_file = tmp_path / "oauth.json"
    token_file.write_text('{"refresh_token": "r"}', encoding="utf-8")
    os.chmod(token_file, 0o644)  # world-readable — should be rejected

    auth = OAuthAuth(type="oauth", oauth_token_file=str(token_file))
    with pytest.raises(CalendarAuthError, match="permissions"):
        build_credentials(auth)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows does not enforce POSIX mode bits")
def test_build_credentials_oauth_accepts_0600(tmp_path):
    token_file = tmp_path / "oauth.json"
    token_file.write_text('{"refresh_token": "r"}', encoding="utf-8")
    os.chmod(token_file, 0o600)

    fake_creds = MagicMock(valid=True)
    with patch(
        "receptionist.booking.auth.Credentials.from_authorized_user_file",
        return_value=fake_creds,
    ):
        auth = OAuthAuth(type="oauth", oauth_token_file=str(token_file))
        build_credentials(auth)  # no exception
```

- [ ] **Step 3: Run — expect ImportError**

```bash
pytest tests/booking/test_auth.py -v
```
Expected: ImportError on `receptionist.booking.auth`.

- [ ] **Step 4: Create `receptionist/booking/auth.py`**

```python
# receptionist/booking/auth.py
from __future__ import annotations

import logging
import stat
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

from receptionist.config import CalendarAuth, OAuthAuth, ServiceAccountAuth

logger = logging.getLogger("receptionist")

# Least-privilege: we read free/busy and create events. Not full calendar.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class CalendarAuthError(Exception):
    """Raised when calendar credentials can't be loaded or refreshed."""


def build_credentials(auth: CalendarAuth):
    """Build a google-auth Credentials object from a CalendarAuth config.

    Raises CalendarAuthError with a clear message on any failure.
    """
    if isinstance(auth, ServiceAccountAuth):
        return _build_service_account(auth)
    if isinstance(auth, OAuthAuth):
        return _build_oauth(auth)
    raise CalendarAuthError(f"Unknown calendar auth type: {type(auth).__name__}")


def _build_service_account(auth: ServiceAccountAuth):
    path = Path(auth.service_account_file)
    if not path.exists():
        raise CalendarAuthError(
            f"Service account key not found: {auth.service_account_file}"
        )
    try:
        return service_account.Credentials.from_service_account_file(
            str(path), scopes=SCOPES,
        )
    except Exception as e:
        raise CalendarAuthError(f"Failed to load service account key: {e}") from e


def _build_oauth(auth: OAuthAuth):
    path = Path(auth.oauth_token_file)
    if not path.exists():
        raise CalendarAuthError(
            f"OAuth token file not found: {auth.oauth_token_file}. "
            f"Run `python -m receptionist.booking setup <business-slug>` first."
        )
    _check_token_permissions(path)
    try:
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    except Exception as e:
        raise CalendarAuthError(f"Failed to load OAuth token: {e}") from e

    # Refresh if expired and we have a refresh token
    if not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            raise CalendarAuthError(f"Failed to refresh OAuth token: {e}") from e

    return creds


def _check_token_permissions(path: Path) -> None:
    """Reject OAuth token files with world/group-readable permissions on Unix."""
    if sys.platform == "win32":
        return  # Windows doesn't have POSIX mode bits
    mode = path.stat().st_mode
    # Bits we care about: group + other read/write/exec. Owner bits are fine.
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CalendarAuthError(
            f"OAuth token file has overly permissive permissions: {oct(mode & 0o777)}. "
            f"Run `chmod 0600 {path}` and try again."
        )
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/booking/test_auth.py -v
```
Expected: 7 tests pass (6 on Windows where 2 POSIX tests are skipped).

- [ ] **Step 6: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add receptionist/booking/auth.py tests/booking/__init__.py tests/booking/test_auth.py
git commit -m "feat: booking.auth.build_credentials for service account + OAuth

Single entry point: build_credentials(CalendarAuth) -> Credentials.
Dispatches on discriminated union. Service account path uses
from_service_account_file; OAuth path uses from_authorized_user_file
and refreshes expired tokens automatically when refresh_token is
available.

Unix-only: rejects OAuth token files with group/world-readable
permissions (shared-host leak protection). Skipped on Windows which
lacks POSIX mode bits.

Uses the narrower calendar.events scope (read free/busy + create
events) rather than full calendar access.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4: Google Calendar client wrapper

### Task 4.1: Implement `booking/client.py` with tests

**Files:**
- Create: `tests/booking/test_client.py`
- Create: `receptionist/booking/client.py`

- [ ] **Step 1: Write `tests/booking/test_client.py`**

```python
# tests/booking/test_client.py
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from receptionist.booking.client import GoogleCalendarClient


def _fake_service(freebusy_response=None, insert_response=None):
    """Construct a MagicMock that looks enough like googleapiclient's service.

    service.freebusy().query(body=...).execute() -> freebusy_response
    service.events().insert(...).execute() -> insert_response
    """
    svc = MagicMock()
    svc.freebusy.return_value.query.return_value.execute.return_value = (
        freebusy_response or {"calendars": {"primary": {"busy": []}}}
    )
    svc.events.return_value.insert.return_value.execute.return_value = (
        insert_response or {"id": "evt123", "htmlLink": "https://cal.example/evt123"}
    )
    return svc


@pytest.mark.asyncio
async def test_free_busy_builds_request_body(mocker):
    fake_service = _fake_service(freebusy_response={
        "calendars": {"primary": {"busy": [
            {"start": "2026-04-28T14:00:00Z", "end": "2026-04-28T15:00:00Z"},
        ]}},
    })
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)

    creds = MagicMock()
    client = GoogleCalendarClient(creds, calendar_id="primary")

    t_min = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    t_max = datetime(2026, 4, 28, 17, 0, tzinfo=timezone.utc)
    busy = await client.free_busy(t_min, t_max)

    assert len(busy) == 1
    start, end = busy[0]
    assert start == datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc)

    # Inspect the request body
    call_kwargs = fake_service.freebusy.return_value.query.call_args.kwargs
    body = call_kwargs["body"]
    assert body["items"] == [{"id": "primary"}]
    assert body["timeMin"].startswith("2026-04-28T09:00")
    assert body["timeMax"].startswith("2026-04-28T17:00")


@pytest.mark.asyncio
async def test_free_busy_parses_rfc3339_z_suffix(mocker):
    """Google returns times as RFC 3339. The 'Z' suffix (UTC) must parse correctly."""
    fake_service = _fake_service(freebusy_response={
        "calendars": {"primary": {"busy": [
            {"start": "2026-04-28T14:00:00Z", "end": "2026-04-28T15:30:00Z"},
        ]}},
    })
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)

    client = GoogleCalendarClient(MagicMock(), calendar_id="primary")
    busy = await client.free_busy(
        datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 29, 0, 0, tzinfo=timezone.utc),
    )
    start, end = busy[0]
    assert start.tzinfo is not None
    assert end == datetime(2026, 4, 28, 15, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_free_busy_empty_result(mocker):
    fake_service = _fake_service(freebusy_response={
        "calendars": {"primary": {"busy": []}},
    })
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)
    client = GoogleCalendarClient(MagicMock(), calendar_id="primary")
    busy = await client.free_busy(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert busy == []


@pytest.mark.asyncio
async def test_create_event_sends_correct_body(mocker):
    fake_service = _fake_service(insert_response={
        "id": "evt-new-123",
        "htmlLink": "https://calendar.google.com/event?eid=abc",
    })
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)
    client = GoogleCalendarClient(MagicMock(), calendar_id="primary")

    result = await client.create_event(
        start=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc),
        summary="Appointment: Jane Doe",
        description="[via AI receptionist / UNVERIFIED]",
        time_zone="America/New_York",
    )

    assert result == {
        "id": "evt-new-123",
        "htmlLink": "https://calendar.google.com/event?eid=abc",
    }

    call_kwargs = fake_service.events.return_value.insert.call_args.kwargs
    assert call_kwargs["calendarId"] == "primary"
    assert call_kwargs["sendUpdates"] == "none"
    body = call_kwargs["body"]
    assert body["summary"] == "Appointment: Jane Doe"
    assert body["description"] == "[via AI receptionist / UNVERIFIED]"
    assert body["start"]["timeZone"] == "America/New_York"
    assert body["end"]["timeZone"] == "America/New_York"
    assert body["start"]["dateTime"].startswith("2026-04-28T14:00")
    assert body["end"]["dateTime"].startswith("2026-04-28T14:30")


@pytest.mark.asyncio
async def test_create_event_http_error_propagates(mocker):
    """HttpError from googleapiclient is not swallowed — the caller decides."""
    from googleapiclient.errors import HttpError
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.side_effect = (
        HttpError(resp=MagicMock(status=403), content=b'{"error": "permission denied"}')
    )
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)
    client = GoogleCalendarClient(MagicMock(), calendar_id="primary")

    with pytest.raises(HttpError):
        await client.create_event(
            start=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
            end=datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc),
            summary="x", description="x", time_zone="UTC",
        )
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/booking/test_client.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create `receptionist/booking/client.py`**

```python
# receptionist/booking/client.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build

logger = logging.getLogger("receptionist")


class GoogleCalendarClient:
    """Thin async wrapper over google-api-python-client's Calendar v3 service.

    All Google API calls are synchronous in google-api-python-client, so we
    wrap them in asyncio.to_thread to keep the event loop unblocked during
    calls.
    """

    def __init__(self, credentials, calendar_id: str) -> None:
        self.credentials = credentials
        self.calendar_id = calendar_id
        # cache_discovery=False is the documented pattern; avoids noisy
        # warnings about oauth2client absence in production.
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    async def free_busy(
        self, time_min: datetime, time_max: datetime
    ) -> list[tuple[datetime, datetime]]:
        """Query free/busy. Returns list of (start, end) tuples of busy intervals.

        time_min / time_max must be timezone-aware datetime objects.
        Returned datetimes preserve the timezone from Google's RFC 3339 response
        (typically UTC when the response uses the 'Z' suffix).
        """
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": self.calendar_id}],
        }
        response = await asyncio.to_thread(
            lambda: self._service.freebusy().query(body=body).execute()
        )
        busy_raw = response.get("calendars", {}).get(self.calendar_id, {}).get("busy", [])
        return [
            (_parse_rfc3339(b["start"]), _parse_rfc3339(b["end"]))
            for b in busy_raw
        ]

    async def create_event(
        self,
        *,
        start: datetime,
        end: datetime,
        summary: str,
        description: str,
        time_zone: str,
        location: str | None = None,
    ) -> dict[str, Any]:
        """Create a calendar event. Returns {id, htmlLink, ...}.

        `time_zone` is an IANA zone string (e.g. "America/New_York"). The start/end
        datetimes are rendered as wall-clock times in that zone in the request body
        so Google honors the configured timezone semantics.
        """
        body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": time_zone,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": time_zone,
            },
        }
        if location:
            body["location"] = location

        result = await asyncio.to_thread(
            lambda: self._service.events().insert(
                calendarId=self.calendar_id,
                body=body,
                sendUpdates="none",  # AI receptionist books silently — operator emails separately
            ).execute()
        )
        logger.info(
            "GoogleCalendarClient: created event %s (%s)",
            result.get("id"), result.get("htmlLink"),
        )
        return result


def _parse_rfc3339(s: str) -> datetime:
    """Parse Google's RFC 3339 timestamp. Handles both 'Z' suffix and '+HH:MM' offsets."""
    # Python's fromisoformat handles '+HH:MM' natively. The 'Z' suffix needs substitution.
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/booking/test_client.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add receptionist/booking/client.py tests/booking/test_client.py
git commit -m "feat: GoogleCalendarClient wrapper with async free_busy + create_event

Thin wrapper over google-api-python-client's Calendar v3 service.
All calls go through asyncio.to_thread since the Google library is
synchronous — keeps the agent's event loop unblocked during API
calls.

free_busy returns parsed (start, end) datetime tuples, handling both
RFC 3339 'Z' suffix and '+HH:MM' offsets. create_event passes
sendUpdates='none' so Google doesn't email organizers about our
bookings (business handles notifications via the existing email
trigger path).

cache_discovery=False matches documented best practice — avoids a
filesystem cache dependency and silences the oauth2client warning.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5: Pure availability logic

### Task 5.1: Implement `booking/availability.py` with comprehensive tests

**Files:**
- Create: `tests/booking/test_availability.py`
- Create: `receptionist/booking/availability.py`

**Why this is a big task:** availability is the only non-trivial business logic in the booking subpackage. It combines business hours, existing busy intervals, buffer rules, booking window, and preferred-time proximity into a sorted list of proposals. Worth getting right with comprehensive test coverage. DST crossover gets its own test.

- [ ] **Step 1: Write `tests/booking/test_availability.py`**

```python
# tests/booking/test_availability.py
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from receptionist.booking.availability import find_slots
from receptionist.booking.models import SlotProposal
from receptionist.config import (
    CalendarConfig, DayHours, ServiceAccountAuth, WeeklyHours,
)


NY = ZoneInfo("America/New_York")


def _cal_cfg(
    duration=30, buffer=15, placement="after",
    window_days=30, earliest_hours=2,
) -> CalendarConfig:
    return CalendarConfig(
        enabled=False,  # disable file-existence check
        calendar_id="primary",
        auth=ServiceAccountAuth(type="service_account", service_account_file="/tmp/fake.json"),
        appointment_duration_minutes=duration,
        buffer_minutes=buffer,
        buffer_placement=placement,
        booking_window_days=window_days,
        earliest_booking_hours_ahead=earliest_hours,
    )


def _weekly_9_to_5() -> WeeklyHours:
    """Mon-Fri 9-5, weekends closed."""
    return WeeklyHours(
        monday=DayHours(open="09:00", close="17:00"),
        tuesday=DayHours(open="09:00", close="17:00"),
        wednesday=DayHours(open="09:00", close="17:00"),
        thursday=DayHours(open="09:00", close="17:00"),
        friday=DayHours(open="09:00", close="17:00"),
        saturday=None,
        sunday=None,
    )


def test_finds_slots_in_business_hours_no_existing_busy():
    """Simple case: empty calendar, Monday morning, caller wants 10am."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)  # Mon 8am NY
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)  # Mon 10am
    earliest = now + timedelta(hours=2)  # 10am
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    assert len(slots) >= 1
    # First slot should be at or near preferred time
    first_start = datetime.fromisoformat(slots[0].start_iso)
    assert first_start.hour in (10,)  # 10:00 exact match
    assert first_start.minute == 0


def test_slots_respect_business_hours_closed_day():
    """Saturday requested — business closed — should skip to Monday."""
    now = datetime(2026, 4, 24, 8, 0, tzinfo=NY)  # Fri 8am
    preferred = datetime(2026, 4, 25, 10, 0, tzinfo=NY)  # Sat 10am
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    # All returned slots must be on a weekday
    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        assert dt.weekday() < 5, f"Slot {slot.start_iso} falls on weekend"


def test_slots_avoid_existing_busy_with_after_buffer():
    """Existing 10:00-10:30 with buffer=15 after: next slot must start >= 10:45."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    existing_busy = [
        (datetime(2026, 4, 27, 10, 0, tzinfo=NY), datetime(2026, 4, 27, 10, 30, tzinfo=NY)),
    ]

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(buffer=15, placement="after"),
        preferred_dt=preferred,
        existing_busy=existing_busy,
        earliest=earliest,
        latest=latest,
        now=now,
    )

    # No slot should start in [10:00, 10:45) — the event + trailing buffer
    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        if dt.date() == datetime(2026, 4, 27).date():
            assert not (
                datetime(2026, 4, 27, 10, 0, tzinfo=NY)
                <= dt
                < datetime(2026, 4, 27, 10, 45, tzinfo=NY)
            ), f"Slot {slot.start_iso} overlaps busy or buffer"


def test_slots_avoid_existing_busy_with_before_buffer():
    """Existing 11:00-11:30 with buffer=15 before: no slot should end >= 10:45."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    existing_busy = [
        (datetime(2026, 4, 27, 11, 0, tzinfo=NY), datetime(2026, 4, 27, 11, 30, tzinfo=NY)),
    ]

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(buffer=15, placement="before"),
        preferred_dt=preferred,
        existing_busy=existing_busy,
        earliest=earliest,
        latest=latest,
        now=now,
    )

    # No slot may END after 10:45 (since 10:45-11:00 is the pre-buffer)
    # ...on the same day
    for slot in slots:
        end = datetime.fromisoformat(slot.end_iso)
        if end.date() == datetime(2026, 4, 27).date():
            assert end <= datetime(2026, 4, 27, 10, 45, tzinfo=NY) or end >= datetime(2026, 4, 27, 11, 30, tzinfo=NY), \
                f"Slot ending {slot.end_iso} violates pre-buffer"


def test_slots_avoid_existing_busy_with_both_buffer():
    """buffer=15, placement=both: 7.5m pre + 7.5m post. Fractional math still works."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    existing_busy = [
        (datetime(2026, 4, 27, 10, 0, tzinfo=NY), datetime(2026, 4, 27, 10, 30, tzinfo=NY)),
    ]

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(buffer=15, placement="both"),
        preferred_dt=preferred,
        existing_busy=existing_busy,
        earliest=earliest,
        latest=latest,
        now=now,
    )

    # Blocked window: 9:52:30 - 10:37:30. No slot may start or end in that range.
    for slot in slots:
        start = datetime.fromisoformat(slot.start_iso)
        end = datetime.fromisoformat(slot.end_iso)
        if start.date() == datetime(2026, 4, 27).date():
            overlaps_start = datetime(2026, 4, 27, 9, 52, 30, tzinfo=NY)
            overlaps_end = datetime(2026, 4, 27, 10, 37, 30, tzinfo=NY)
            assert not (start < overlaps_end and end > overlaps_start), \
                f"Slot {slot.start_iso}-{slot.end_iso} overlaps buffer-wrapped busy"


def test_slots_enforce_earliest_booking_hours_ahead():
    """Caller wants 30 minutes from now, config says 2hr minimum lead time."""
    now = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 30, tzinfo=NY)  # only 30min away
    earliest = now + timedelta(hours=2)  # 12:00
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(earliest_hours=2),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    # Every slot must be >= earliest
    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        assert dt >= earliest, f"Slot {slot.start_iso} violates earliest_booking_hours_ahead"


def test_slots_enforce_booking_window():
    """Caller wants a time 40 days out, booking_window_days is 30."""
    now = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    preferred = datetime(2026, 6, 6, 10, 0, tzinfo=NY)  # 40 days away
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(window_days=30),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        assert dt <= latest, f"Slot {slot.start_iso} exceeds booking window"


def test_slots_sorted_by_proximity_to_preferred():
    """Slots closer to the preferred time come first in the returned list."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 14, 0, tzinfo=NY)  # 2pm
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    assert len(slots) >= 2
    # First slot should be the closest to 2pm
    first_dist = abs(
        (datetime.fromisoformat(slots[0].start_iso) - preferred).total_seconds()
    )
    second_dist = abs(
        (datetime.fromisoformat(slots[1].start_iso) - preferred).total_seconds()
    )
    assert first_dist <= second_dist


def test_dst_crossover_spring_forward():
    """On March 8 2026, DST begins in NY. A call on March 7 asking for March 9 at 9am
    must produce a valid slot with correct UTC offset. Spring-forward means 2am -> 3am.
    """
    now = datetime(2026, 3, 7, 15, 0, tzinfo=NY)  # Sat Mar 7, still EST (-05:00)
    preferred = datetime(2026, 3, 9, 9, 0, tzinfo=NY)  # Mon Mar 9 9am, now EDT (-04:00)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )

    assert len(slots) >= 1
    first = datetime.fromisoformat(slots[0].start_iso)
    # On Mon Mar 9 NY, DST is active — offset should be -04:00
    assert first.utcoffset() == timedelta(hours=-4), \
        f"Expected EDT (-04:00), got {first.utcoffset()}"
    assert first.hour == 9


def test_no_slots_returned_when_calendar_fully_booked():
    """If every slot in the window is busy or outside hours, return empty list."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=1)  # just one day window

    # Block out the entire day
    existing_busy = [
        (datetime(2026, 4, 27, 9, 0, tzinfo=NY), datetime(2026, 4, 27, 17, 0, tzinfo=NY)),
    ]

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(window_days=1),
        preferred_dt=preferred,
        existing_busy=existing_busy,
        earliest=earliest,
        latest=latest,
        now=now,
    )

    assert slots == []


def test_returns_max_3_slots():
    """API contract: up to 3 nearest slots returned."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 12, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )
    assert len(slots) <= 3


def test_slots_are_grid_aligned():
    """Slots should align to 15-minute grid boundaries (0, 15, 30, 45)."""
    now = datetime(2026, 4, 27, 8, 0, tzinfo=NY)
    preferred = datetime(2026, 4, 27, 10, 0, tzinfo=NY)
    earliest = now + timedelta(hours=2)
    latest = now + timedelta(days=30)

    slots = find_slots(
        business_hours=_weekly_9_to_5(),
        business_timezone="America/New_York",
        calendar_config=_cal_cfg(),
        preferred_dt=preferred,
        existing_busy=[],
        earliest=earliest,
        latest=latest,
        now=now,
    )
    for slot in slots:
        dt = datetime.fromisoformat(slot.start_iso)
        assert dt.minute in (0, 15, 30, 45)
        assert dt.second == 0
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/booking/test_availability.py -v
```
Expected: ImportError on `receptionist.booking.availability`.

- [ ] **Step 3: Create `receptionist/booking/availability.py`**

```python
# receptionist/booking/availability.py
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from receptionist.booking.models import SlotProposal
from receptionist.config import CalendarConfig, WeeklyHours


_SLOT_GRID_MINUTES = 15  # slots must align to 0, 15, 30, 45 past the hour
_MAX_SLOTS_RETURNED = 3


def find_slots(
    *,
    business_hours: WeeklyHours,
    business_timezone: str,
    calendar_config: CalendarConfig,
    preferred_dt: datetime,
    existing_busy: list[tuple[datetime, datetime]],
    earliest: datetime,
    latest: datetime,
    now: datetime,
) -> list[SlotProposal]:
    """Find available appointment slots near `preferred_dt`.

    Pure function — no I/O. Caller supplies the busy list (already fetched from
    Google) and the wall-clock constraints (earliest, latest, now). Returns up
    to 3 SlotProposals sorted by proximity to `preferred_dt`.
    """
    tz = ZoneInfo(business_timezone)
    duration = timedelta(minutes=calendar_config.appointment_duration_minutes)
    buffer_total = timedelta(minutes=calendar_config.buffer_minutes)
    placement = calendar_config.buffer_placement

    # Expand each existing busy interval by the configured buffer.
    # This is the inverse of "buffer around new bookings": equivalent to widening
    # existing bookings by the same amount, which is simpler to reason about.
    buffered_busy = [
        _apply_buffer(start, end, buffer_total, placement)
        for (start, end) in existing_busy
    ]

    # Enumerate candidate slots on the 15-minute grid within the window.
    candidates: list[SlotProposal] = []
    for candidate_start in _iter_grid_slots(earliest, latest, tz):
        candidate_end = candidate_start + duration

        # Must fit entirely within business hours on its day
        if not _fits_in_business_hours(candidate_start, candidate_end, business_hours, tz):
            continue

        # Must not overlap any buffered busy interval
        if any(_overlaps(candidate_start, candidate_end, bs, be) for (bs, be) in buffered_busy):
            continue

        candidates.append(SlotProposal(
            start_iso=candidate_start.isoformat(),
            end_iso=candidate_end.isoformat(),
        ))

    # Sort by proximity to preferred time, then take top N
    candidates.sort(key=lambda s: abs(
        (datetime.fromisoformat(s.start_iso) - preferred_dt).total_seconds()
    ))
    return candidates[:_MAX_SLOTS_RETURNED]


def _apply_buffer(
    start: datetime, end: datetime, buffer: timedelta, placement: str,
) -> tuple[datetime, datetime]:
    if placement == "before":
        return (start - buffer, end)
    if placement == "after":
        return (start, end + buffer)
    if placement == "both":
        half = buffer / 2
        return (start - half, end + half)
    raise ValueError(f"Unknown buffer_placement: {placement}")


def _iter_grid_slots(earliest: datetime, latest: datetime, tz: ZoneInfo):
    """Yield grid-aligned candidate start times in `tz` between earliest and latest.

    The grid is :00/:15/:30/:45. Start by rounding `earliest` UP to the next grid boundary.
    """
    # Convert to business timezone so the grid aligns with wall-clock minutes
    current = earliest.astimezone(tz)
    # Round up to the next 15-minute boundary
    minute_mod = current.minute % _SLOT_GRID_MINUTES
    if minute_mod != 0 or current.second != 0 or current.microsecond != 0:
        current = current.replace(second=0, microsecond=0) + timedelta(
            minutes=_SLOT_GRID_MINUTES - minute_mod
        )

    step = timedelta(minutes=_SLOT_GRID_MINUTES)
    while current <= latest.astimezone(tz):
        yield current
        current = current + step


def _fits_in_business_hours(
    start: datetime, end: datetime, hours: WeeklyHours, tz: ZoneInfo,
) -> bool:
    """Check whether [start, end) fits entirely within the day's business hours."""
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)

    # Must be the same day (rule out appointments crossing midnight)
    if local_start.date() != local_end.date():
        return False

    day_name = local_start.strftime("%A").lower()
    day_hours = getattr(hours, day_name, None)
    if day_hours is None:
        return False  # business closed

    open_time = _parse_hhmm(day_hours.open)
    close_time = _parse_hhmm(day_hours.close)
    local_start_time = local_start.time().replace(second=0, microsecond=0)
    local_end_time = local_end.time().replace(second=0, microsecond=0)

    return open_time <= local_start_time and local_end_time <= close_time


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def _overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime,
) -> bool:
    """Standard half-open interval overlap check."""
    return a_start < b_end and b_start < a_end
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/booking/test_availability.py -v
```
Expected: 12 tests pass. If DST test fails, double-check that `astimezone(tz)` is consistently applied — the timezone object handles spring-forward correctly.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add receptionist/booking/availability.py tests/booking/test_availability.py
git commit -m "feat: pure find_slots function for booking availability

Takes business hours + calendar config + preferred datetime + existing
busy list + time constraints, returns up to 3 SlotProposals sorted by
proximity to the preferred time.

Slot grid is fixed at 15 minutes (spec §2 locked this in — YAGNI on
further configurability). Business hours enforced by day-of-week
lookup in the business timezone (not UTC), so DST crossover works
correctly.

Buffer placement supports before/after/both; buffer_minutes is split
evenly for \"both\" (15m -> 7.5m each side). Tested across all three
placements plus DST spring-forward.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 6: Booking core

### Task 6.1: Implement `booking/booking.py` with tests

**Files:**
- Create: `tests/booking/test_booking.py`
- Create: `receptionist/booking/booking.py`

- [ ] **Step 1: Write `tests/booking/test_booking.py`**

```python
# tests/booking/test_booking.py
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.booking.booking import (
    SlotNoLongerAvailableError, book_appointment,
)
from receptionist.booking.models import BookingResult, SlotProposal


def _slot(start_iso="2026-04-28T14:00:00-04:00", end_iso="2026-04-28T14:30:00-04:00") -> SlotProposal:
    return SlotProposal(start_iso=start_iso, end_iso=end_iso)


@pytest.mark.asyncio
async def test_book_appointment_happy_path():
    fake_client = MagicMock()
    fake_client.free_busy = AsyncMock(return_value=[])  # slot still free
    fake_client.create_event = AsyncMock(return_value={
        "id": "evt-new-999",
        "htmlLink": "https://calendar.google.com/event?eid=xyz",
    })

    result = await book_appointment(
        slot=_slot(),
        caller_name="Jane Doe",
        callback_number="+15551112222",
        call_id="playground-ABC",
        time_zone="America/New_York",
        client=fake_client,
        notes=None,
    )

    assert isinstance(result, BookingResult)
    assert result.event_id == "evt-new-999"
    assert result.html_link == "https://calendar.google.com/event?eid=xyz"
    assert result.start_iso == "2026-04-28T14:00:00-04:00"
    assert result.end_iso == "2026-04-28T14:30:00-04:00"

    # Verify the event body
    call_kwargs = fake_client.create_event.call_args.kwargs
    assert call_kwargs["summary"] == "Appointment: Jane Doe"
    description = call_kwargs["description"]
    assert "UNVERIFIED" in description
    assert "Jane Doe" in description
    assert "+15551112222" in description
    assert "playground-ABC" in description


@pytest.mark.asyncio
async def test_book_appointment_includes_notes_when_given():
    fake_client = MagicMock()
    fake_client.free_busy = AsyncMock(return_value=[])
    fake_client.create_event = AsyncMock(return_value={
        "id": "e", "htmlLink": "u",
    })

    await book_appointment(
        slot=_slot(),
        caller_name="Jane",
        callback_number="+1",
        call_id="c",
        time_zone="UTC",
        client=fake_client,
        notes="Follow-up after last visit",
    )

    description = fake_client.create_event.call_args.kwargs["description"]
    assert "Follow-up after last visit" in description


@pytest.mark.asyncio
async def test_book_appointment_detects_race_slot_now_busy():
    """Between check_availability and book_appointment, someone else booked the slot."""
    fake_client = MagicMock()
    # free_busy now returns the slot as busy
    fake_client.free_busy = AsyncMock(return_value=[
        (
            datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc),
        ),
    ])
    fake_client.create_event = AsyncMock()  # should NOT be called

    with pytest.raises(SlotNoLongerAvailableError):
        await book_appointment(
            slot=_slot("2026-04-28T14:00:00+00:00", "2026-04-28T14:30:00+00:00"),
            caller_name="Jane",
            callback_number="+1",
            call_id="c",
            time_zone="UTC",
            client=fake_client,
            notes=None,
        )

    fake_client.create_event.assert_not_called()


@pytest.mark.asyncio
async def test_book_appointment_no_notes_field_says_none():
    fake_client = MagicMock()
    fake_client.free_busy = AsyncMock(return_value=[])
    fake_client.create_event = AsyncMock(return_value={"id": "e", "htmlLink": "u"})

    await book_appointment(
        slot=_slot(),
        caller_name="Jane",
        callback_number="+1",
        call_id="c",
        time_zone="UTC",
        client=fake_client,
        notes=None,
    )
    description = fake_client.create_event.call_args.kwargs["description"]
    assert "Notes: (none)" in description


@pytest.mark.asyncio
async def test_book_appointment_description_includes_booked_timestamp():
    """The event description records WHEN it was booked, for audit/debug."""
    fake_client = MagicMock()
    fake_client.free_busy = AsyncMock(return_value=[])
    fake_client.create_event = AsyncMock(return_value={"id": "e", "htmlLink": "u"})

    await book_appointment(
        slot=_slot(),
        caller_name="Jane",
        callback_number="+1",
        call_id="c",
        time_zone="UTC",
        client=fake_client,
        notes=None,
    )
    description = fake_client.create_event.call_args.kwargs["description"]
    assert "Booked:" in description
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/booking/test_booking.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create `receptionist/booking/booking.py`**

```python
# receptionist/booking/booking.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from receptionist.booking.client import GoogleCalendarClient
from receptionist.booking.models import BookingResult, SlotProposal

logger = logging.getLogger("receptionist")


class SlotNoLongerAvailableError(Exception):
    """Raised when the proposed slot was free at check_availability time but is now busy.

    The caller (tool handler) should catch this, run availability again, and
    offer the caller new alternatives.
    """


async def book_appointment(
    *,
    slot: SlotProposal,
    caller_name: str,
    callback_number: str,
    call_id: str,
    time_zone: str,
    client: GoogleCalendarClient,
    notes: str | None,
) -> BookingResult:
    """Book the given slot on the calendar.

    Performs a last-second free/busy check for the exact slot to detect races
    between check_availability and this call. On race, raises
    SlotNoLongerAvailableError; the tool handler turns that into an LLM-facing
    message offering alternatives.
    """
    start = datetime.fromisoformat(slot.start_iso)
    end = datetime.fromisoformat(slot.end_iso)

    # Race detection: re-query free/busy for JUST this slot
    busy_now = await client.free_busy(start, end)
    if busy_now:
        logger.info(
            "Slot taken between check_availability and book_appointment: %s",
            slot.start_iso,
            extra={"call_id": call_id, "component": "booking.booking"},
        )
        raise SlotNoLongerAvailableError(slot.start_iso)

    # Build the event description. UNVERIFIED tag is permanent and intentional —
    # staff viewing the event need to see that the AI took this booking without
    # identity verification.
    booked_at = datetime.now(timezone.utc).isoformat()
    description_lines = [
        "[via AI receptionist / UNVERIFIED]",
        f"Caller: {caller_name}",
        f"Callback: {callback_number}",
        f"Booked: {booked_at}",
        f"Call ID: {call_id}",
        f"Notes: {notes or '(none)'}",
    ]
    description = "\n".join(description_lines)

    summary = f"Appointment: {caller_name}"

    result = await client.create_event(
        start=start,
        end=end,
        summary=summary,
        description=description,
        time_zone=time_zone,
    )

    logger.info(
        "Appointment booked: event_id=%s for %s at %s",
        result["id"], caller_name, slot.start_iso,
        extra={"call_id": call_id, "component": "booking.booking"},
    )

    return BookingResult(
        event_id=result["id"],
        start_iso=slot.start_iso,
        end_iso=slot.end_iso,
        html_link=result["htmlLink"],
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/booking/test_booking.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add receptionist/booking/booking.py tests/booking/test_booking.py
git commit -m "feat: book_appointment with race detection + UNVERIFIED tagging

Re-queries free/busy for the exact slot immediately before create_event
to catch races between check_availability and book. On race, raises
SlotNoLongerAvailableError — the tool handler turns that into an
LLM-facing 'that slot just got taken' message.

Event description includes the UNVERIFIED tag (permanent, staff-visible),
caller name + callback, call_id for transcript cross-reference, and the
booked-at timestamp for audit/debug.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 7: EmailChannel.deliver_booking

### Task 7.1: Add `deliver_booking` method to EmailChannel with tests

**Files:**
- Modify: `receptionist/messaging/channels/email.py`
- Modify: `tests/messaging/test_email_channel.py`

**Why this lands before tool integration:** `CallLifecycle.on_call_ended` (updated in Phase 1) already references `channel.deliver_booking(metadata, context)`. Until the method exists on `EmailChannel`, any call that booked an appointment with `on_booking: true` would raise AttributeError at lifecycle time. Landing this method stops that latent bug before calendar tools are even wired in.

- [ ] **Step 1: Append to `tests/messaging/test_email_channel.py`** — add these tests at the end:

```python
# ---- deliver_booking tests ----


def _call_metadata_for_booking() -> "CallMetadata":
    from receptionist.transcript.metadata import CallMetadata
    md = CallMetadata(
        call_id="room-1",
        business_name="Acme",
        caller_phone="+15551112222",
        appointment_booked=True,
        appointment_details={
            "event_id": "evt1",
            "start_iso": "2026-04-28T14:00:00-04:00",
            "end_iso": "2026-04-28T14:30:00-04:00",
            "html_link": "https://calendar.google.com/event?eid=abc",
        },
    )
    md.outcomes.add("appointment_booked")
    md.mark_finalized()
    return md


@pytest.mark.asyncio
async def test_email_channel_deliver_booking_sends_via_smtp(mocker):
    cfg = EmailChannelConfig(type="email", to=["owner@acme.com"])
    email_cfg = _email_config_smtp()

    sender_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg)
    md = _call_metadata_for_booking()
    from receptionist.messaging.models import DispatchContext
    await channel.deliver_booking(md, DispatchContext())

    sender_send.assert_called_once()
    kwargs = sender_send.call_args.kwargs
    assert kwargs["to"] == ["owner@acme.com"]
    assert "appointment" in kwargs["subject"].lower() or "New appointment booked" in kwargs["subject"]
    assert "calendar.google.com" in kwargs["body_text"]


@pytest.mark.asyncio
async def test_email_channel_deliver_booking_retries_on_transient(mocker):
    from receptionist.email.sender import EmailSendError
    cfg = EmailChannelConfig(type="email", to=["owner@acme.com"])
    email_cfg = _email_config_smtp()

    sender_send = AsyncMock(side_effect=[
        EmailSendError("down", transient=True),
        None,
    ])
    mocker.patch("receptionist.email.smtp.SMTPSender.send", sender_send)

    channel = EmailChannel(cfg, email_cfg, initial_delay=0.001)
    md = _call_metadata_for_booking()
    from receptionist.messaging.models import DispatchContext
    await channel.deliver_booking(md, DispatchContext())

    assert sender_send.call_count == 2
```

- [ ] **Step 2: Run — expect failure**

```bash
source venv/Scripts/activate
pytest tests/messaging/test_email_channel.py::test_email_channel_deliver_booking_sends_via_smtp -v
```
Expected: AttributeError — `EmailChannel` has no `deliver_booking` method yet.

- [ ] **Step 3: Modify `receptionist/messaging/channels/email.py`** — add `deliver_booking` method

Open the file and find the existing `deliver_call_end` method. Add this new method right after it (still inside the `EmailChannel` class):

```python
    async def deliver_booking(
        self, metadata: CallMetadata, context: DispatchContext
    ) -> None:
        from receptionist.email.templates import build_booking_email
        subject, body_text, body_html = build_booking_email(metadata, context)
        await self._send_with_retry(subject, body_text, body_html)
```

Also update the imports at the top of the file to include `build_booking_email`:

```python
from receptionist.email.templates import (
    build_call_end_email, build_booking_email, build_message_email,
)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/messaging/test_email_channel.py -v
```
Expected: all tests pass (existing + 2 new deliver_booking tests).

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add receptionist/messaging/channels/email.py tests/messaging/test_email_channel.py
git commit -m "feat: EmailChannel.deliver_booking for on_booking trigger

Parallel to deliver_call_end — builds subject/body via
build_booking_email and sends through the retry-backed sender. Lifecycle
already calls this method in the on_booking branch (added in Phase 1);
this lands the method itself.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 8: Calendar tools on the Receptionist agent

### Task 8.1: Add `check_availability` and `book_appointment` tool methods to `Receptionist`

**Files:**
- Modify: `receptionist/agent.py`

**Note:** Tool methods are decorated with `@function_tool()` and live on the `Receptionist(Agent)` class. They fire at LLM tool-call time. We add a session-scoped `_offered_slots: set[str]` cache on the instance to enforce "check before book" architecturally.

- [ ] **Step 1: Open `receptionist/agent.py`** and locate the `Receptionist.__init__` method.

Currently it looks like:

```python
class Receptionist(Agent):
    def __init__(self, config: BusinessConfig, lifecycle: CallLifecycle) -> None:
        super().__init__(instructions=build_system_prompt(config))
        self.config = config
        self.lifecycle = lifecycle
```

Replace it with:

```python
class Receptionist(Agent):
    def __init__(self, config: BusinessConfig, lifecycle: CallLifecycle) -> None:
        super().__init__(instructions=build_system_prompt(config))
        self.config = config
        self.lifecycle = lifecycle
        # Session-scoped cache of slot ISO strings offered to the caller via
        # check_availability. book_appointment rejects any proposed_start_iso
        # that isn't in this set — prevents the LLM from hallucinating times.
        self._offered_slots: set[str] = set()
        # Lazily-constructed on first calendar tool call; reused for the rest
        # of the call so we don't pay Google's auth cost per tool invocation.
        self._calendar_client: "GoogleCalendarClient | None" = None
```

- [ ] **Step 2: Add a helper method** to construct the calendar client lazily. Insert right after `__init__`:

```python
    def _get_calendar_client(self) -> "GoogleCalendarClient":
        """Lazily construct and cache the Google Calendar client for this call."""
        if self._calendar_client is None:
            if self.config.calendar is None or not self.config.calendar.enabled:
                raise RuntimeError(
                    "Calendar tools were called but config.calendar is not enabled."
                )
            from receptionist.booking.auth import build_credentials
            from receptionist.booking.client import GoogleCalendarClient
            creds = build_credentials(self.config.calendar.auth)
            self._calendar_client = GoogleCalendarClient(
                creds, calendar_id=self.config.calendar.calendar_id,
            )
        return self._calendar_client
```

- [ ] **Step 3: Add the `check_availability` tool method** — insert after `get_business_hours`:

```python
    @function_tool()
    async def check_availability(
        self,
        ctx: RunContext,
        preferred_date: str,
        preferred_time: str,
    ) -> str:
        """Check the calendar for available appointment slots near a caller-requested time.

        Args:
            preferred_date: a natural-language date like "Tuesday", "April 28",
                "tomorrow", "next Monday", etc.
            preferred_time: a natural-language time like "2pm", "14:00", "afternoon".
        """
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        from dateutil import parser as dateparser

        from receptionist.booking.availability import find_slots
        from receptionist.booking.auth import CalendarAuthError

        if self.config.calendar is None or not self.config.calendar.enabled:
            return (
                "I'm sorry, we don't have online booking set up. I can take a "
                "message about your preferred time and have someone call you back."
            )

        tz = ZoneInfo(self.config.business.timezone)
        now = datetime.now(tz)

        # Parse caller's natural-language date + time into a tz-aware datetime.
        # The LLM is responsible for pre-normalizing to something dateutil can
        # handle ("Tuesday April 28" rather than "next tues"), but we tolerate
        # a range of inputs.
        try:
            combined = f"{preferred_date} {preferred_time}"
            parsed = dateparser.parse(combined, default=now.replace(
                second=0, microsecond=0,
            ))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
        except (ValueError, TypeError) as e:
            logger.info("check_availability: could not parse %r %r: %s", preferred_date, preferred_time, e)
            return (
                "I had trouble understanding that date and time. Could you say it "
                "differently — for example, 'Tuesday April 28 at 2 PM'?"
            )

        earliest = now + timedelta(hours=self.config.calendar.earliest_booking_hours_ahead)
        latest = now + timedelta(days=self.config.calendar.booking_window_days)

        # Hard constraint checks (before hitting Google)
        if parsed < earliest:
            return (
                f"I can only book appointments at least "
                f"{self.config.calendar.earliest_booking_hours_ahead} hours from now. "
                f"The earliest I can offer is {earliest.strftime('%A, %B %-d at %-I:%M %p')}."
            )
        if parsed > latest:
            return (
                f"I can only book up to {self.config.calendar.booking_window_days} "
                f"days out. Would you like a time sooner than "
                f"{latest.strftime('%A, %B %-d')}?"
            )

        try:
            client = self._get_calendar_client()
            busy = await client.free_busy(earliest, latest)
        except CalendarAuthError:
            logger.exception("check_availability: auth error")
            return (
                "I'm having trouble accessing our calendar right now. Can I take "
                "a message about your preferred time and have someone call you back?"
            )
        except Exception:
            logger.exception("check_availability: client error")
            return (
                "I can't check availability at the moment. Can I take a message "
                "about the time you wanted?"
            )

        slots = find_slots(
            business_hours=self.config.hours,
            business_timezone=self.config.business.timezone,
            calendar_config=self.config.calendar,
            preferred_dt=parsed,
            existing_busy=busy,
            earliest=earliest,
            latest=latest,
            now=now,
        )

        if not slots:
            return (
                f"I don't see any openings near {parsed.strftime('%A, %B %-d at %-I:%M %p')}. "
                f"Would you like me to take a message so someone can offer alternatives?"
            )

        # Cache the ISO strings so book_appointment can validate them
        for slot in slots:
            self._offered_slots.add(slot.start_iso)

        # Format a caller-friendly response. The LLM takes this and speaks it.
        formatted = []
        for i, slot in enumerate(slots, start=1):
            dt = datetime.fromisoformat(slot.start_iso)
            human = dt.strftime("%A, %B %-d at %-I:%M %p")
            # Also include the ISO string so the LLM can pass it back to book_appointment
            formatted.append(f"{i}. {human}  [iso={slot.start_iso}]")

        return (
            f"I found these available times near your preferred slot. "
            f"Confirm the one the caller chose, then call book_appointment with "
            f"the exact iso= string shown.\n" + "\n".join(formatted)
        )

    @function_tool()
    async def book_appointment(
        self,
        ctx: RunContext,
        caller_name: str,
        callback_number: str,
        proposed_start_iso: str,
        notes: str | None = None,
    ) -> str:
        """Book an appointment at a previously-offered time.

        Args:
            caller_name: the caller's full name
            callback_number: the caller's phone number
            proposed_start_iso: the exact ISO 8601 start datetime offered by
                a prior check_availability call. Copy from that response.
            notes: optional free-form note to include in the event description.
        """
        from receptionist.booking.booking import (
            SlotNoLongerAvailableError, book_appointment,
        )
        from receptionist.booking.models import SlotProposal
        from receptionist.booking.availability import find_slots
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        if self.config.calendar is None or not self.config.calendar.enabled:
            return "Calendar booking is not enabled for this business."

        # Enforce "must check before book" — slot must have been offered
        if proposed_start_iso not in self._offered_slots:
            return (
                "I need to verify that time is still available. Let me check "
                "first — please call check_availability before booking."
            )

        # Reconstruct the matching SlotProposal. We trust start_iso and compute
        # the end from appointment_duration_minutes (slots have uniform duration).
        start = datetime.fromisoformat(proposed_start_iso)
        duration = timedelta(minutes=self.config.calendar.appointment_duration_minutes)
        slot = SlotProposal(
            start_iso=proposed_start_iso,
            end_iso=(start + duration).isoformat(),
        )

        try:
            client = self._get_calendar_client()
            result = await book_appointment(
                slot=slot,
                caller_name=caller_name,
                callback_number=callback_number,
                call_id=self.lifecycle.metadata.call_id,
                time_zone=self.config.business.timezone,
                client=client,
                notes=notes,
            )
        except SlotNoLongerAvailableError:
            # Slot just got taken. Find fresh alternatives.
            tz = ZoneInfo(self.config.business.timezone)
            now = datetime.now(tz)
            earliest = now + timedelta(hours=self.config.calendar.earliest_booking_hours_ahead)
            latest = now + timedelta(days=self.config.calendar.booking_window_days)
            try:
                busy = await client.free_busy(earliest, latest)
                alternates = find_slots(
                    business_hours=self.config.hours,
                    business_timezone=self.config.business.timezone,
                    calendar_config=self.config.calendar,
                    preferred_dt=start,
                    existing_busy=busy,
                    earliest=earliest,
                    latest=latest,
                    now=now,
                )
            except Exception:
                logger.exception("book_appointment: failed to find alternates after race")
                alternates = []

            # Reset cache to the new set
            self._offered_slots = {s.start_iso for s in alternates}
            if alternates:
                formatted = "\n".join(
                    f"- {datetime.fromisoformat(s.start_iso).strftime('%A, %B %-d at %-I:%M %p')}  [iso={s.start_iso}]"
                    for s in alternates
                )
                return (
                    f"Unfortunately that slot just got taken. Here are the "
                    f"nearest alternatives:\n{formatted}"
                )
            return (
                "Unfortunately that slot just got taken, and I can't find "
                "nearby alternatives right now. Would you like me to take a "
                "message so someone can call you back with options?"
            )
        except Exception:
            logger.exception("book_appointment: unexpected error")
            return (
                "I had trouble booking that time. Can I take a message with "
                "the time you wanted, and someone will confirm with you?"
            )

        # Success — record on lifecycle, return confirmation
        self.lifecycle.record_appointment_booked({
            "event_id": result.event_id,
            "start_iso": result.start_iso,
            "end_iso": result.end_iso,
            "html_link": result.html_link,
        })

        confirmed = datetime.fromisoformat(result.start_iso)
        return (
            f"You're all set for {confirmed.strftime('%A, %B %-d at %-I:%M %p')}. "
            f"Someone will contact you at {callback_number} if we need to confirm."
        )
```

Note the format string `%-d` and `%-I` are Unix shorthand for "no leading zero." These work on Linux/macOS. **On Windows** the equivalent is `%#d` and `%#I`. Since the agent may run on either platform, handle this correctly:

Add this helper near the top of `agent.py` (just below the imports):

```python
import platform


def _format_friendly_date(dt) -> str:
    """Cross-platform 'Monday, April 28 at 2:00 PM'."""
    if platform.system() == "Windows":
        return dt.strftime("%A, %B %#d at %#I:%M %p")
    return dt.strftime("%A, %B %-d at %-I:%M %p")
```

Then inside the two tool methods above, **replace every `dt.strftime("%A, %B %-d at %-I:%M %p")` with `_format_friendly_date(dt)`**.

- [ ] **Step 4: Smoke-test import**

```bash
source venv/Scripts/activate
python -c "import receptionist.agent; print('OK')"
```
Expected: "OK" — no syntax errors, no import-time errors.

- [ ] **Step 5: Run full test suite**

```bash
pytest -q
```
Expected: all pass. There are no unit tests of these tool methods directly (testing against LiveKit's session machinery is not cost-effective — per spec §6.4). The integration test in Phase 10 covers them.

- [ ] **Step 6: Commit**

```bash
git add receptionist/agent.py
git commit -m "feat: check_availability + book_appointment tools on Receptionist

Two new @function_tool methods. check_availability parses
natural-language date + time, applies hard booking-window and
earliest-hours constraints BEFORE hitting Google, queries free/busy,
and returns up to 3 formatted slots. Caches the ISO start strings on
self._offered_slots so book_appointment can validate against them.

book_appointment rejects any proposed_start_iso not in the cache,
calls booking.book_appointment (with race detection), on success
calls lifecycle.record_appointment_booked, and returns a confirmation.
On SlotNoLongerAvailableError, fetches fresh alternatives and returns
them in the tool response.

Platform-conditional date formatting (%-d/%-I on Unix, %#d/%#I on
Windows) wrapped in _format_friendly_date.

Calendar client is lazily constructed via _get_calendar_client() and
cached for the duration of the call (avoids repeated auth cost).

No unit tests yet — the tool methods wrap already-tested pieces and
manual + integration tests in Phase 10 cover them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 9: System prompt update

### Task 9.1: Add CALENDAR section to system prompt when enabled

**Files:**
- Modify: `receptionist/prompts.py`
- Modify: `tests/test_prompts.py`

- [ ] **Step 1: Open `receptionist/prompts.py`** and locate `build_system_prompt`.

Add a helper function right before `build_system_prompt`:

```python
def _build_calendar_block(config: BusinessConfig) -> str:
    """Build the CALENDAR section of the system prompt, or empty string if disabled."""
    if config.calendar is None or not config.calendar.enabled:
        return ""
    return (
        "\nCALENDAR (appointment booking):\n"
        "You can book appointments on the business calendar using two tools:\n"
        "  1. check_availability(preferred_date, preferred_time) — call this FIRST.\n"
        "     It returns up to 3 available slots near the caller's preferred time,\n"
        "     each with a human-readable time AND an iso= string.\n"
        "  2. book_appointment(caller_name, callback_number, proposed_start_iso, notes) —\n"
        "     call this AFTER the caller confirms the specific time you offered.\n"
        "     The proposed_start_iso MUST be copied exactly from a check_availability\n"
        "     response — you cannot make one up.\n"
        "\n"
        "BOOKING CONVENTIONS (follow exactly):\n"
        "  - Before booking, always say the specific time back to the caller and wait\n"
        "    for explicit confirmation: \"I'm booking you for Tuesday April 28 at 2 PM.\n"
        "    Can I confirm?\" Do NOT book without a clear \"yes.\"\n"
        "  - If check_availability says a time is too soon or too far out, politely\n"
        "    offer the caller the earliest/latest the tool permitted.\n"
        "  - If book_appointment says the slot just got taken, offer the alternatives\n"
        "    the tool returned.\n"
        "  - If the calendar can't be reached, pivot to take_message: \"I'm having\n"
        "    trouble with the calendar — can I take your info and have someone call\n"
        "    back to confirm the time?\"\n"
        "  - NEVER fabricate a time, confirmation code, or event ID.\n"
    )
```

- [ ] **Step 2: Call the helper** inside `build_system_prompt` — locate the f-string that returns the full prompt and add `{calendar_block}` just before the FAQ section. First, compute `calendar_block = _build_calendar_block(config)` at the top of `build_system_prompt`:

Find the line `language_block = _build_language_block(config)` and add right below it:

```python
    calendar_block = _build_calendar_block(config)
```

Then inside the returned f-string, find this section:

```python
When a caller asks to be transferred, use the transfer_call tool with the department name.
When a caller wants to leave a message, use the take_message tool to record their name, message, and callback number.
When asked about business hours, use the get_business_hours tool.
```

Replace with:

```python
When a caller asks to be transferred, use the transfer_call tool with the department name.
When a caller wants to leave a message, use the take_message tool to record their name, message, and callback number.
When asked about business hours, use the get_business_hours tool.
{calendar_block}
```

The `{calendar_block}` is an f-string substitution — when calendar is disabled, it's empty and adds no content. When enabled, it adds the block described in Step 1.

- [ ] **Step 3: Add tests** to `tests/test_prompts.py` — append at the end:

```python
# ---- calendar block tests ----


CALENDAR_YAML = """
business: { name: "Test Dental", type: "dental office", timezone: "America/New_York" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Thank you for calling Test Dental."
personality: "You are a friendly receptionist."
hours:
  monday: { open: "09:00", close: "17:00" }
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "We are currently closed."
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./messages/test/"
calendar:
  enabled: false   # don't require file existence in this test
  auth:
    type: "service_account"
    service_account_file: "/tmp/fake.json"
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
"""


def test_prompt_omits_calendar_block_when_calendar_disabled():
    """When calendar.enabled is False, the prompt does NOT include the CALENDAR section."""
    config = BusinessConfig.from_yaml_string(CALENDAR_YAML)
    prompt = build_system_prompt(config)
    assert "CALENDAR" not in prompt
    assert "check_availability" not in prompt
    assert "book_appointment" not in prompt


def test_prompt_includes_calendar_block_when_enabled(tmp_path):
    """When calendar.enabled is True and the auth file exists, prompt includes CALENDAR section."""
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")
    yaml_text = CALENDAR_YAML.replace(
        "enabled: false",
        "enabled: true",
    ).replace(
        "/tmp/fake.json",
        str(sa_file),
    )
    config = BusinessConfig.from_yaml_string(yaml_text)
    prompt = build_system_prompt(config)
    assert "CALENDAR" in prompt
    assert "check_availability" in prompt
    assert "book_appointment" in prompt
    assert "confirm" in prompt.lower()  # confirmation convention
    assert "fabricate" in prompt.lower() or "never make up" in prompt.lower()  # hard rule
```

- [ ] **Step 4: Run tests**

```bash
source venv/Scripts/activate
pytest tests/test_prompts.py -v
```
Expected: all prompt tests pass (existing + 2 new calendar tests).

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add receptionist/prompts.py tests/test_prompts.py
git commit -m "feat: CALENDAR system-prompt section when calendar is enabled

Describes the two tools, the verbal-confirmation convention ('say the
time back, wait for yes'), the no-fabrication hard rule, and the
fallback-to-take_message path for calendar failures. Emitted only
when config.calendar is present and enabled — disabled businesses
get no change to their prompt.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 10: Integration test

### Task 10.1: End-to-end booking flow without real Google API

**Files:**
- Create: `tests/integration/test_booking_flow.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/test_booking_flow.py
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.config import (
    BusinessConfig, CalendarConfig, DayHours,
    EmailChannel as EmailChannelConfig, EmailConfig, EmailSenderConfig,
    EmailTriggers, FileChannel as FileChannelConfig, ServiceAccountAuth,
    SMTPConfig, TranscriptsConfig, TranscriptStorageConfig, WeeklyHours,
)
from receptionist.lifecycle import CallLifecycle


def _full_config(tmp_path, v2_yaml) -> BusinessConfig:
    """Config with calendar enabled + on_booking trigger + email channel."""
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")

    base = BusinessConfig.from_yaml_string(v2_yaml)
    return base.model_copy(update={
        "hours": WeeklyHours(
            monday=DayHours(open="09:00", close="17:00"),
            tuesday=DayHours(open="09:00", close="17:00"),
            wednesday=DayHours(open="09:00", close="17:00"),
            thursday=DayHours(open="09:00", close="17:00"),
            friday=DayHours(open="09:00", close="17:00"),
            saturday=None, sunday=None,
        ),
        "messages": base.messages.model_copy(update={
            "channels": [
                FileChannelConfig(type="file", file_path=str(tmp_path / "messages")),
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig(
            **{"from": "noreply@acme.com"},
            sender=EmailSenderConfig(
                type="smtp",
                smtp=SMTPConfig(host="h", port=587, username="u", password="p", use_tls=True),
            ),
            triggers=EmailTriggers(on_message=True, on_call_end=False, on_booking=True),
        ),
        "transcripts": TranscriptsConfig(
            enabled=True,
            storage=TranscriptStorageConfig(type="local", path=str(tmp_path / "transcripts")),
            formats=["json", "markdown"],
        ),
        "calendar": CalendarConfig(
            enabled=True,
            calendar_id="primary",
            auth=ServiceAccountAuth(type="service_account", service_account_file=str(sa_file)),
            appointment_duration_minutes=30,
            buffer_minutes=15,
            buffer_placement="after",
            booking_window_days=30,
            earliest_booking_hours_ahead=2,
        ),
    })


async def _drain_pending_tasks() -> None:
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_booking_flow_records_outcome_and_fires_on_booking_email(tmp_path, v2_yaml, mocker):
    """Full path: record_appointment_booked -> on_call_ended -> on_booking email."""
    config = _full_config(tmp_path, v2_yaml)

    smtp_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", smtp_send)

    lifecycle = CallLifecycle(config=config, call_id="room-xyz", caller_phone="+15551112222")

    # Simulate the book_appointment tool having run successfully
    lifecycle.record_appointment_booked({
        "event_id": "evt-integration-1",
        "start_iso": "2026-04-28T14:00:00-04:00",
        "end_iso": "2026-04-28T14:30:00-04:00",
        "html_link": "https://calendar.google.com/event?eid=abc",
    })

    await lifecycle.on_call_ended()
    await _drain_pending_tasks()

    # Metadata records the booking
    assert lifecycle.metadata.appointment_booked is True
    assert "appointment_booked" in lifecycle.metadata.outcomes
    assert lifecycle.metadata.appointment_details["event_id"] == "evt-integration-1"

    # Booking email fired
    smtp_send.assert_called()
    # Find the booking-email call among any other SMTP calls
    booking_calls = [
        c for c in smtp_send.call_args_list
        if "New appointment booked" in c.kwargs.get("subject", "")
        or "appointment" in c.kwargs.get("subject", "").lower()
    ]
    assert len(booking_calls) >= 1
    body_text = booking_calls[0].kwargs["body_text"]
    assert "evt-integration-1" not in body_text  # internal ID not leaked to staff
    assert "calendar.google.com" in body_text
    assert "UNVERIFIED" in body_text or "NOT verified" in body_text


@pytest.mark.asyncio
async def test_multi_outcome_transferred_and_booked(tmp_path, v2_yaml):
    """A call that both transfers AND books an appointment records both outcomes."""
    config = _full_config(tmp_path, v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)

    lifecycle.record_transfer("Front Desk")
    lifecycle.record_appointment_booked({
        "event_id": "e", "start_iso": "s", "end_iso": "e2", "html_link": "l",
    })

    await lifecycle.on_call_ended()

    assert lifecycle.metadata.outcomes == {"transferred", "appointment_booked"}


@pytest.mark.asyncio
async def test_on_booking_trigger_does_not_fire_when_no_booking(tmp_path, v2_yaml, mocker):
    """on_booking trigger is guarded by metadata.appointment_booked — no booking, no email."""
    config = _full_config(tmp_path, v2_yaml)
    smtp_send = AsyncMock()
    mocker.patch("receptionist.email.smtp.SMTPSender.send", smtp_send)

    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    # No record_appointment_booked — just a hang-up call
    await lifecycle.on_call_ended()
    await _drain_pending_tasks()

    # No email with "appointment booked" subject
    booking_calls = [
        c for c in smtp_send.call_args_list
        if "appointment" in c.kwargs.get("subject", "").lower()
    ]
    assert len(booking_calls) == 0


@pytest.mark.asyncio
async def test_disabled_calendar_skips_calendar_block_in_prompt(tmp_path, v2_yaml):
    """Regression check: disabling calendar removes the CALENDAR prompt section."""
    from receptionist.prompts import build_system_prompt
    config_enabled = _full_config(tmp_path, v2_yaml)
    config_disabled = config_enabled.model_copy(update={
        "calendar": config_enabled.calendar.model_copy(update={"enabled": False}),
    })
    # Note: CalendarConfig validator requires file existence at enabled=True.
    # Toggling enabled=False sidesteps it.
    assert "CALENDAR" in build_system_prompt(config_enabled)
    assert "CALENDAR" not in build_system_prompt(config_disabled)
```

- [ ] **Step 2: Run the integration tests**

```bash
source venv/Scripts/activate
pytest tests/integration/ -v
```
Expected: all integration tests pass (existing + 4 new booking tests).

- [ ] **Step 3: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_booking_flow.py
git commit -m "test: integration tests for booking flow + multi-outcome + on_booking trigger

Four scenarios, no real Google API:
  - record_appointment_booked -> on_call_ended -> on_booking email fires
  - multi-outcome (transferred + appointment_booked both recorded)
  - no-booking case: on_booking trigger does not fire
  - prompt regression: CALENDAR block included only when enabled

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 11: OAuth setup CLI

### Task 11.1: Implement setup CLI with minimal tests

**Files:**
- Create: `receptionist/booking/setup_cli.py`
- Create: `receptionist/booking/__main__.py`
- Create: `tests/booking/test_setup_cli.py`

**Note:** The OAuth browser-based flow itself is NOT unit-tested (launches real browser, wildly flaky in CI). Argument parsing and "no business found" error paths are unit-tested; the full OAuth flow is covered by the manual checklist in Phase 13.

- [ ] **Step 1: Write `tests/booking/test_setup_cli.py`**

```python
# tests/booking/test_setup_cli.py
from __future__ import annotations

from unittest.mock import patch

import pytest

from receptionist.booking.setup_cli import main


def test_main_missing_business_exits_nonzero(capsys, tmp_path, monkeypatch):
    """If the business-slug doesn't match any config/businesses/*.yaml, exit 2."""
    monkeypatch.chdir(tmp_path)  # isolated cwd; no config/businesses/ exists
    exit_code = main(["setup", "nonexistent-business"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "nonexistent-business" in captured.err or "not found" in captured.err.lower()


def test_main_requires_subcommand(capsys, tmp_path, monkeypatch):
    """No args -> argparse prints help + exits 2."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main([])


def test_main_unknown_subcommand_exits_nonzero(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["unknown-command"])


def test_main_setup_invokes_oauth_flow_for_existing_business(tmp_path, monkeypatch, mocker):
    """When a business config exists and has oauth auth, the CLI calls InstalledAppFlow."""
    # Build a minimal working config
    (tmp_path / "config" / "businesses").mkdir(parents=True)
    (tmp_path / "config" / "businesses" / "testbiz.yaml").write_text("""
business: { name: "Test", type: "t", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
""", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    secrets_dir = tmp_path / "secrets" / "testbiz"
    secrets_dir.mkdir(parents=True)
    client_file = secrets_dir / "google-calendar-oauth-client.json"
    client_file.write_text('{"installed": {"client_id": "x", "client_secret": "y"}}', encoding="utf-8")

    fake_creds = mocker.MagicMock()
    fake_creds.to_json.return_value = '{"token": "abc"}'
    fake_flow = mocker.MagicMock()
    fake_flow.run_local_server.return_value = fake_creds
    mocker.patch(
        "receptionist.booking.setup_cli.InstalledAppFlow.from_client_secrets_file",
        return_value=fake_flow,
    )

    exit_code = main(["setup", "testbiz"])
    assert exit_code == 0

    # Token file should have been written
    token_file = secrets_dir / "google-calendar-oauth.json"
    assert token_file.exists()
    assert token_file.read_text(encoding="utf-8") == '{"token": "abc"}'
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/booking/test_setup_cli.py -v
```
Expected: ImportError on `receptionist.booking.setup_cli`.

- [ ] **Step 3: Create `receptionist/booking/setup_cli.py`**

```python
# receptionist/booking/setup_cli.py
from __future__ import annotations

import argparse
import logging
import os
import stat
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger("receptionist")

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
DEFAULT_CONFIG_DIR = Path("config/businesses")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m receptionist.booking",
        description="Google Calendar setup utilities for AIReceptionist.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser(
        "setup",
        help="Walk through the OAuth consent flow for a business's calendar.",
    )
    setup.add_argument("business", help="Business slug (YAML filename stem in config/businesses/).")
    setup.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    if args.command != "setup":
        parser.error(f"Unknown command: {args.command}")
        return 2

    return _run_setup(args.business)


def _run_setup(business_slug: str) -> int:
    config_path = DEFAULT_CONFIG_DIR / f"{business_slug}.yaml"
    if not config_path.exists():
        print(
            f"Business config not found: {config_path}. "
            f"Available businesses: {sorted(p.stem for p in DEFAULT_CONFIG_DIR.glob('*.yaml'))}",
            file=sys.stderr,
        )
        return 2

    secrets_dir = Path("secrets") / business_slug
    secrets_dir.mkdir(parents=True, exist_ok=True)

    client_file = secrets_dir / "google-calendar-oauth-client.json"
    token_file = secrets_dir / "google-calendar-oauth.json"

    if not client_file.exists():
        print(
            f"\nOAuth client JSON not found at {client_file}.\n"
            f"\n"
            f"Before running setup, you need to:\n"
            f"  1. Go to https://console.cloud.google.com/apis/credentials\n"
            f"  2. Create an OAuth 2.0 Client ID (application type: Desktop app)\n"
            f"  3. Download the JSON (it looks like {{\"installed\": {{...}}}})\n"
            f"  4. Save it as {client_file}\n"
            f"\n"
            f"Then re-run: python -m receptionist.booking setup {business_slug}\n",
            file=sys.stderr,
        )
        return 2

    print(f"Starting OAuth flow for {business_slug}...")
    print("A browser window will open. Sign in with the Google account whose calendar")
    print("you want to use for appointment booking.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    creds = flow.run_local_server(port=0)  # port=0 -> pick an available port

    token_file.write_text(creds.to_json(), encoding="utf-8")
    _set_0600(token_file)

    print(f"\n✓ OAuth token saved to {token_file} (permissions: 0600)")
    print(f"✓ Set auth.type: \"oauth\" and auth.oauth_token_file: \"./{token_file}\" in")
    print(f"  {config_path}")
    return 0


def _set_0600(path: Path) -> None:
    """Set the file to owner-read/write only. No-op on Windows."""
    if sys.platform == "win32":
        return
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Create `receptionist/booking/__main__.py`** — one-liner delegating to setup_cli

```python
# receptionist/booking/__main__.py
from __future__ import annotations

import sys

from receptionist.booking.setup_cli import main


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests**

```bash
source venv/Scripts/activate
pytest tests/booking/test_setup_cli.py -v
```
Expected: 4 tests pass.

- [ ] **Step 6: Smoke-test the CLI help output**

```bash
python -m receptionist.booking --help 2>&1 | head -10
python -m receptionist.booking setup --help 2>&1 | head -10
```
Expected: argparse prints meaningful help. Exit 0 for `--help`.

- [ ] **Step 7: Run full suite**

```bash
pytest -q
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add receptionist/booking/setup_cli.py receptionist/booking/__main__.py \
        tests/booking/test_setup_cli.py
git commit -m "feat: python -m receptionist.booking setup <business> (OAuth wizard)

Validates the business config exists + the operator-provided OAuth
client JSON is in place (secrets/<business>/google-calendar-oauth-client.json),
then runs google-auth-oauthlib's InstalledAppFlow.run_local_server to
capture the refresh token via a browser consent flow. Writes the token
to secrets/<business>/google-calendar-oauth.json with 0600 permissions
on Unix (no-op on Windows).

Prints an actionable error if the OAuth client JSON is missing — tells
the operator exactly what to download from Google Cloud Console.

The browser flow itself is not unit-tested (too flaky to mock well).
Argument parsing + error paths + token-file write are covered.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 12: Documentation

### Task 12.1: Write the Google Calendar setup guide

**Files:**
- Create: `documentation/google-calendar-setup.md`

- [ ] **Step 1: Write the guide**

```markdown
# Google Calendar integration setup

This guide walks through configuring a business to use Google Calendar for
in-call appointment booking. There are two authentication paths:
**service account** (simpler, works for Google Workspace) and **OAuth 2.0**
(works for any account, including personal gmail.com, but requires a
browser-based consent step).

If your business uses Google Workspace (custom domain), go with **service
account**. If you're trying to integrate a personal gmail.com calendar, use
**OAuth**.

## Prerequisites

- A Google Cloud project (create one at https://console.cloud.google.com/)
- The Google Calendar API enabled on that project:
  - Go to https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
  - Click **Enable**
- The calendar you want to book on (you'll need its calendar ID — usually
  `primary` for the account's default calendar, or the full email-shaped ID
  for a shared calendar)

## Path A: Service account (Google Workspace)

### 1. Create a service account

1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts
2. Click **Create Service Account**
3. Give it a name like `aireceptionist-<business-slug>`
4. Grant no project-level roles (the service account's permissions come from
   calendar sharing, not IAM)
5. Finish. Back on the service account list, click the account you just
   created, go to the **Keys** tab, and click **Add Key → Create new key →
   JSON**. A JSON file downloads.

### 2. Save the key file

Move the downloaded JSON into the project:

```
mkdir -p secrets/<business-slug>
mv ~/Downloads/<project>-<hash>.json secrets/<business-slug>/google-calendar-sa.json
chmod 600 secrets/<business-slug>/google-calendar-sa.json
```

(Windows users: just place the file; chmod is ignored.)

### 3. Share the calendar with the service account

Take note of the service account's email address — it looks like
`aireceptionist-<biz>@<project>.iam.gserviceaccount.com`. Open the Google
Calendar UI in your browser, go to the calendar's **Settings and sharing**
page, and add the service account email under **Share with specific people**
with permission **Make changes to events**.

Without this step, the service account can authenticate but will get 403
errors on any call to the calendar.

### 4. Configure the business YAML

Add to `config/businesses/<business-slug>.yaml`:

```yaml
calendar:
  enabled: true
  calendar_id: "primary"  # or the specific calendar ID
  auth:
    type: "service_account"
    service_account_file: "./secrets/<business-slug>/google-calendar-sa.json"
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
```

### 5. Verify

Start the agent in dev mode and place a test call. Ask the AI to check
availability for a specific time. Logs should show `GoogleCalendarClient:
created event ...` on successful bookings.

## Path B: OAuth 2.0 (personal gmail, or any account)

### 1. Create an OAuth client

1. Go to https://console.cloud.google.com/apis/credentials
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name: anything memorable, e.g. `aireceptionist-desktop`
5. Click **Create**, then **Download JSON**. You'll get a file that contains
   `{"installed": {"client_id": "...", "client_secret": "..."}}`.

### 2. Save the client JSON

```
mkdir -p secrets/<business-slug>
mv ~/Downloads/client_secret_<...>.json secrets/<business-slug>/google-calendar-oauth-client.json
chmod 600 secrets/<business-slug>/google-calendar-oauth-client.json
```

### 3. Run the setup CLI

```
python -m receptionist.booking setup <business-slug>
```

This opens a browser window. Sign in with the Google account whose calendar
you want to use. Approve the requested scopes (you'll see a single scope:
"See and edit events on all your calendars"). The CLI catches the redirect,
extracts the refresh token, and writes it to
`secrets/<business-slug>/google-calendar-oauth.json` with `0600` permissions.

Example successful output:

```
Starting OAuth flow for mdasr...
A browser window will open. Sign in with the Google account whose calendar
you want to use for appointment booking.

...your browser opens...

✓ OAuth token saved to secrets/mdasr/google-calendar-oauth.json (permissions: 0600)
✓ Set auth.type: "oauth" and auth.oauth_token_file: "./secrets/mdasr/google-calendar-oauth.json" in
  config/businesses/mdasr.yaml
```

### 4. Configure the business YAML

```yaml
calendar:
  enabled: true
  calendar_id: "primary"
  auth:
    type: "oauth"
    oauth_token_file: "./secrets/<business-slug>/google-calendar-oauth.json"
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
```

### 5. Verify

Same as the service account path — place a test call.

## Troubleshooting

### `403 Forbidden` on free/busy queries

- **Service account path:** the calendar hasn't been shared with the service
  account email. Re-check step A.3.
- **OAuth path:** the account you consented with doesn't own or have edit
  access to the `calendar_id` you configured. Double-check the ID is a
  calendar the signed-in account can write to.

### `HttpError 404: Not Found` on a calendar ID

The `calendar_id` in the YAML doesn't match an accessible calendar. For a
shared calendar, find the full ID in the Google Calendar UI → calendar
settings → **Calendar ID** (a long email-shaped string).

### OAuth token file has overly permissive permissions

The agent refuses to start on Unix if the OAuth token file is readable by
group or other. Fix with:

```
chmod 600 secrets/<business>/google-calendar-oauth.json
```

### OAuth token expired / refresh failed

OAuth refresh tokens eventually expire (Google's policy varies; typically
after ~6 months of inactivity, or when the user revokes the consent). Re-run
the setup CLI to refresh:

```
rm secrets/<business>/google-calendar-oauth.json
python -m receptionist.booking setup <business-slug>
```

### The agent can see availability but can't book

Usually a scope issue. The project uses the narrow
`https://www.googleapis.com/auth/calendar.events` scope. If you accidentally
ran setup with a wider or narrower scope, the token may not have the right
permissions. Delete the token file and re-run setup.

## Rotating credentials

**Service account:**
1. Create a new key in the Google Cloud service account's Keys tab
2. Replace `secrets/<business>/google-calendar-sa.json` with the new one
3. Delete the old key from the Cloud Console (optional but recommended)
4. Restart the agent

**OAuth:**
1. Delete `secrets/<business>/google-calendar-oauth.json`
2. Re-run `python -m receptionist.booking setup <business-slug>`
3. Restart the agent

## Per-business isolation

Each business has its own `secrets/<business-slug>/` directory. Don't share
credentials between businesses — each gets its own service account or OAuth
token. This makes revocation surgical (revoking one business doesn't affect
others).

## Data & privacy notes

- The agent creates calendar events with the caller's **name** and **phone
  number** in the event description
- Events are tagged `[via AI receptionist / UNVERIFIED]` — staff viewing
  the event can see at a glance that the caller's identity was NOT verified
- The agent sets `sendUpdates=none` on every booking, so Google does NOT
  send calendar notifications to organizers. If you want to confirm bookings
  with staff, enable the `on_booking` email trigger on the business's
  `email.triggers` config
- Call IDs (LiveKit room names) are included in event descriptions so staff
  can cross-reference events with call transcripts
```

- [ ] **Step 2: Commit**

```bash
git add documentation/google-calendar-setup.md
git commit -m "docs: Google Calendar integration setup guide

Step-by-step for both service account (Workspace) and OAuth (any
account) paths. Covers Google Cloud Console clicks, file placement,
calendar sharing, YAML config, verification, troubleshooting, and
credential rotation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 12.2: Update architecture.md, CHANGELOG, HANDOFF.md, README, .env.example, MANUAL.md

**Files:**
- Modify: `documentation/architecture.md`
- Modify: `documentation/CHANGELOG.md`
- Modify: `HANDOFF.md`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `tests/MANUAL.md`

- [ ] **Step 1: `documentation/architecture.md`** — add a booking subpackage section + update the package layout

Find the package-layout ASCII diagram and update it. Specifically, find the block listing `receptionist/` directory contents and add lines for `booking/`:

```
receptionist/
├── agent.py                 Thin session orchestrator, Receptionist, tool methods
├── config.py                Pydantic v2 models (+ CalendarConfig + auth union)
├── prompts.py               System prompt builder (+ CALENDAR block)
├── lifecycle.py             CallLifecycle: per-call metadata owner, event fan-out
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
├── messaging/               ... (unchanged)
... etc
```

Then add a new "Calendar integration" subsection after the existing "Close-event handler" subsection in the "Key design decisions" area:

```markdown
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
```

- [ ] **Step 2: `documentation/CHANGELOG.md`** — find the `[Unreleased]` block and add:

```markdown
### Added
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
- `Receptionist.__init__` gains `_offered_slots: set[str]` session cache +
  lazily-constructed `_calendar_client`.
- New artifact directory: `secrets/<business>/` (gitignored) for calendar
  credentials — service account JSON keys and OAuth token files.

### Security
- OAuth token files enforced to `0600` permissions on Unix at agent startup
  (no-op on Windows).
- Calendar events tagged `[via AI receptionist / UNVERIFIED]` permanently
  so staff see the caller's identity was not verified.
- `sendUpdates="none"` on all `events.insert` calls — no side-channel
  notifications from Google.
- Calendar credentials are per-business, isolated in `secrets/<business>/`.
```

- [ ] **Step 3: `HANDOFF.md`** — append at the very end:

```markdown

---

## Addendum — 2026-04-DD: Google Calendar integration (issue #3)

Adds in-call appointment booking via Google Calendar. See
`documentation/architecture.md` for the authoritative architecture post-
this-change; this addendum summarizes what shipped.

### Summary
- Two new function tools on `Receptionist`: `check_availability` and
  `book_appointment`.
- New `receptionist/booking/` subpackage (auth, client wrapper,
  pure availability logic, booking with race detection, setup CLI).
- Both service account and OAuth 2.0 auth paths supported. Setup CLI
  (`python -m receptionist.booking setup <business>`) walks a business
  owner through the OAuth browser consent flow.
- New `on_booking` email trigger using the existing EmailChannel
  dispatcher — notifies staff when an appointment lands.
- Session-scoped slot cache (`Receptionist._offered_slots`) enforces
  "check-before-book" architecturally — the LLM cannot book a slot it
  wasn't offered.
- UNVERIFIED tag in event descriptions: staff see the caller's identity
  was not verified.

### BREAKING change bundled with this work
`CallMetadata.outcome: str | None` → `CallMetadata.outcomes: set[str]`.
Calls with multiple outcomes (e.g. transfer + book) now retain both.
Email subjects render as "Transferred + Appointment booked" when applicable.
`_OUTCOME_PRIORITY` dict deleted; `_add_outcome` replaces `_set_outcome`.

### Dependencies
Added: `google-api-python-client>=2.140`, `google-auth>=2.32`,
`google-auth-oauthlib>=1.2`, `python-dateutil>=2.9`. All Apache 2.0.

### Test coverage
Unit tests per subpackage module (~35 new tests). One integration test
(`tests/integration/test_booking_flow.py`) covering record_appointment_booked
→ on_call_ended → on_booking email fan-out. Browser OAuth flow is manual-only
(`tests/MANUAL.md` section).

### Known limitations in v1 (tracked for follow-ups)
- No cancellations (go via `take_message` for now)
- No rescheduling
- No recurring appointments
- No multi-provider round-robin
- No SMS confirmation / caller verification
- No payment integration
- No Outlook / Microsoft 365 / Apple Calendar
- No reminders (would need an SMS provider)

### Reference documents
- Design spec: `docs/superpowers/specs/2026-04-24-google-calendar-integration-design.md`
- Implementation plan: `docs/superpowers/plans/2026-04-24-google-calendar-integration.md`
- Setup guide: `documentation/google-calendar-setup.md`
```

Replace `2026-04-DD` with the actual merge date when landing this.

- [ ] **Step 4: `README.md`** — add a new section BEFORE any existing "License" or "Contributing" heading (or near the bottom if neither exists):

```markdown
## Appointment booking (Google Calendar)

Each business can optionally enable Google Calendar integration for in-call
booking:

```yaml
calendar:
  enabled: true
  calendar_id: "primary"
  auth:
    type: "service_account"  # or "oauth"
    service_account_file: "./secrets/<business>/google-calendar-sa.json"
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
```

When enabled, the agent gets two new tools:
- **`check_availability(preferred_date, preferred_time)`** — queries the
  calendar and returns up to 3 slots near the requested time
- **`book_appointment(caller_name, callback_number, proposed_start_iso, notes?)`** —
  books one of the offered slots

The agent always says the proposed time back to the caller and waits for
"yes" before booking. Events are tagged UNVERIFIED so staff know the
caller's identity wasn't verified.

See `documentation/google-calendar-setup.md` for step-by-step setup of
both auth paths (service account for Workspace, OAuth for any account).

Optional: set `email.triggers.on_booking: true` to email staff whenever a
booking lands (uses the existing email channel).
```

- [ ] **Step 5: `.env.example`** — append:

```
# --------------------------------------------------------------------------
# Google Calendar integration: credentials live in secrets/<business>/, NOT in
# env vars. See documentation/google-calendar-setup.md.
# No new env vars are required for calendar — the .env file is unaffected.
# --------------------------------------------------------------------------
```

- [ ] **Step 6: `tests/MANUAL.md`** — add a new section at the end:

```markdown

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
```

- [ ] **Step 7: Verify tests still pass**

```bash
source venv/Scripts/activate
pytest -q
```
Expected: all pass (no test changes in this task).

- [ ] **Step 8: Commit all documentation at once**

```bash
git add documentation/architecture.md documentation/CHANGELOG.md HANDOFF.md \
        README.md .env.example tests/MANUAL.md
git commit -m "docs: full docs sweep for Google Calendar integration

- architecture.md: new booking/ subpackage in package layout + new
  Calendar integration section under Key design decisions
- CHANGELOG.md: [Unreleased] entries under Added, Changed, Security
- HANDOFF.md: new addendum summarizing the feature + breaking change
- README.md: new 'Appointment booking' section with minimal YAML + pointer
  to setup guide
- .env.example: note that calendar uses secrets/ not env vars
- tests/MANUAL.md: new Calendar integration section covering setup, happy
  path, race condition, constraints, multi-outcome, on_booking trigger,
  and error paths

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 13: Manual validation + final sanity

### Task 13.1: Walk the calendar section of `tests/MANUAL.md`

This task is not automatable — it requires a live Google Calendar and a real call through LiveKit Playground. Record results in the PR description or a separate issue.

- [ ] **Step 1: Set up a test Workspace or gmail account + calendar**

Don't use a production firm calendar. Create a dedicated test account (or a dedicated test calendar on an existing account that's safe to have events land on).

- [ ] **Step 2: Walk every checkbox in the Calendar section of `tests/MANUAL.md`**

Service-account setup + OAuth setup + happy path + race + constraints + multi-outcome + on_booking email + error paths.

- [ ] **Step 3: Any discovered bugs become their own follow-up issue or commit**

If something's broken, stop and fix before declaring the feature ready for merge. Do NOT patch ad-hoc — file a followup if the bug isn't trivial.

- [ ] **Step 4: No commit from this task** — manual validation is a gate, not a code change.

### Task 13.2: Final full-suite sanity check

- [ ] **Step 1: Run everything**

```bash
source venv/Scripts/activate
pytest -q
```
Expected: full suite passes. Rough post-change count: ~155-160 tests (baseline 124 + ~35 new across booking/, test_config, test_prompts, test_email_templates, test_email_channel, test_lifecycle, test_metadata, test_booking_flow integration).

- [ ] **Step 2: Verify the CLIs still work**

```bash
python -m receptionist.retention sweep --dry-run
python -m receptionist.messaging list-failures
python -m receptionist.booking --help
```
All three should exit 0 and print meaningful output.

- [ ] **Step 3: Verify pre-commit hook is firing**

```bash
# Trivial test: edit a docstring, stage, commit, expect pytest to run as part of the hook
echo "" >> README.md
git add README.md
git commit -m "test: pre-commit hook sanity check"
# Should see [pre-commit] Running pytest... output
# Then undo:
git reset HEAD~1 && git checkout README.md
```

- [ ] **Step 4: No new commit from this task** (the hook verification is throwaway)

### Task 13.3: Spec-coverage self-review

At this point, walk the spec one more time against what shipped. File is at
`docs/superpowers/specs/2026-04-24-google-calendar-integration-design.md`.

- [ ] **Step 1: Create a spec-coverage review file**

Path: `docs/superpowers/2026-04-24-google-calendar-spec-coverage.md`

Walk the spec sections (§2, §3, §4, §5, §6, §7, §8, §9) and map each to a
commit or task. Format:

```markdown
# Spec coverage self-review — Google Calendar integration

Date: 2026-04-DD
Merge commit on main: <HEAD SHA after merge>
Final test count: <N>

## Coverage

| Spec section | Implementation | Status |
|---|---|---|
| §2.1 calendar YAML section | receptionist/config.py (CalendarConfig) | ✓ |
| §2.1 auth discriminator | receptionist/config.py (ServiceAccountAuth, OAuthAuth) | ✓ |
| §2.1 buffer_placement | receptionist/booking/availability.py::_apply_buffer | ✓ |
| §2.2 on_booking trigger | receptionist/config.py EmailTriggers + lifecycle.py | ✓ |
| §2.3 Pydantic models | receptionist/config.py | ✓ |
| §2.4 validation rules | receptionist/config.py model_validators | ✓ |
| §2.5 cross-section validator | receptionist/config.py validate_cross_section | ✓ |
| §2.6 outcomes breaking change | Phase 1 | ✓ |
| §3 package structure | receptionist/booking/*.py | ✓ |
| §3.1 component boundaries | All modules in booking/ | ✓ |
| §4.1 check_availability flow | Phase 8 tool method + Phase 5 find_slots | ✓ |
| §4.1 book_appointment flow | Phase 8 tool method + Phase 6 book_appointment | ✓ |
| §4.2 session-scoped cache | Receptionist._offered_slots | ✓ |
| §4.3 CallMetadata new fields | Phase 1 | ✓ |
| §4.5 on_booking trigger fan-out | Phase 1 lifecycle.py | ✓ |
| §4.6 multi-outcome templates | Phase 1 email/templates.py + transcript/formatter.py | ✓ |
| §5 error handling per component | Multiple — verified in test_auth, test_client, Phase 8 tool error paths | ✓ |
| §5.2 not retried list | retry.py is_transient classifiers | ✓ |
| §5.3 logging contract | Throughout — extra={call_id, component, business_name} | ✓ |
| §5.4 security behavior | booking/auth.py _check_token_permissions + never-log-keys | ✓ |
| §6 unit tests | tests/booking/*.py + tests/test_prompts.py + tests/email/test_templates.py | ✓ |
| §6 integration test | tests/integration/test_booking_flow.py | ✓ |
| §7 new deps | pyproject.toml | ✓ |
| §8 secrets directory | secrets/.gitkeep + .gitignore | ✓ |
| §8 setup CLI | receptionist/booking/setup_cli.py | ✓ |
| §8 docs | documentation/google-calendar-setup.md + architecture.md + README + HANDOFF addendum | ✓ |
| §9 rollout sequencing | 13 phases as described | ✓ |

## Code-review fixes landed during execution

<fill this in as the plan is executed — analogous to how PR #2's spec-coverage-review.md documented inline fixes>

## Outstanding items

- Task 13.1 (manual validation walkthrough) — gated on live Google Calendar test account
- Known v1 out-of-scope items remain: cancellations, rescheduling, etc. See spec §10.

## Sign-off

Spec coverage: complete. Implementation matches spec with targeted code-review fixes noted above.
Next step: Task 13.1 manual validation, then merge.
```

- [ ] **Step 2: Commit the review**

```bash
git add docs/superpowers/2026-04-24-google-calendar-spec-coverage.md
git commit -m "docs: spec-coverage self-review for Google Calendar integration

Traces every spec section to the implementation file/commit. Records
any code-review fixes that landed during execution. Gates final
merge on manual validation walkthrough.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-review checklist (run before declaring the plan done)

- **Spec coverage:** every section of the spec has a task. Cross-check §2, §3, §4, §5, §6, §7, §8, §9. If any section has no task, add it.
- **Placeholders:** grep the plan for `TBD`, `TODO`, `fill in`, `similar to Task N`, `...`. None should appear outside of legitimate code content.
- **Type consistency:** every name used in later tasks matches earlier definitions. `SlotProposal`, `BookingResult`, `CalendarAuthError`, `SlotNoLongerAvailableError`, `build_credentials`, `GoogleCalendarClient`, `find_slots`, `book_appointment`, `check_availability`, `record_appointment_booked`, `deliver_booking`, `build_booking_email`, `_offered_slots`, `_calendar_client`, `_get_calendar_client`, `_add_outcome`, `VALID_OUTCOMES`, `_OUTCOME_LABELS`.
- **Breaking-change warnings:** Phase 1 is explicitly labeled BREAKING and must land before any booking code.
- **Pre-commit hook reality:** Task 1.1 through 1.4 produce tests that fail against unchanged code — therefore bundled into one commit in Task 1.5.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-24-google-calendar-integration.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Best for this plan because 13 phases is a long sequence and fresh-context subagents make the phased approach clean.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints. Viable since the plan is meaningfully smaller than PR #2 (~35 new tests vs. ~120), but still long enough that context fatigue matters.

Which approach?



