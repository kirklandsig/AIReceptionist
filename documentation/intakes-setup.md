# Intake Setup

This guide covers the structured new-client intake feature: how Riley conducts
an intake over the phone, how to configure the question script, and how the
completed submission lands in your file/email pipeline.

---

## Table of Contents

- [What the feature does](#what-the-feature-does)
- [Configuration overview](#configuration-overview)
- [Question schema](#question-schema)
- [Spanish-language calls](#spanish-language-calls)
- [Output: structured JSON + email](#output-structured-json--email)
- [Partial intakes (mid-call disconnects)](#partial-intakes-mid-call-disconnects)
- [Mid-intake escape hatch](#mid-intake-escape-hatch)
- [Tool reference](#tool-reference)
- [Operational tips](#operational-tips)

---

## What the feature does

When `intakes.enabled: true` is set in a business YAML, Riley is given two
new function tools — `record_intake_answer` and `finalize_intake` — plus an
INTAKES section in the system prompt listing the configured case types and
their question scripts.

A typical call looks like this:

1. Caller says they're a new client and would like to do an intake by phone.
2. Riley speaks the configured `preamble_en` (or `preamble_es` for Spanish
   callers) — a short heads-up about call length so the caller can opt in.
3. Riley confirms which case type applies, then walks through the case type's
   questions one at a time.
4. After every answer, Riley calls `record_intake_answer` with the
   `case_type`, `question_key`, `spoken_text` (verbatim, in the caller's
   language), `language`, and an inline `english_summary`. The partial intake
   is persisted to disk after each call.
5. For questions marked `critical: true`, Riley reads the answer back
   digit-by-digit or letter-by-letter and waits for explicit confirmation
   before moving on.
6. When all required questions are answered, Riley calls `finalize_intake`
   with the confirmed legal name, callback number, and a 1–3 sentence
   English overview. The final JSON file is written and the intake email is
   queued for call-end.

---

## Configuration overview

A minimal `intakes:` block looks like this:

```yaml
intakes:
  enabled: true
  preamble_en: |
    This intake usually takes 15–20 minutes. Do you have time to go through
    it now, or should I take a short message and we can complete it later?
  preamble_es: |
    Esta entrevista generalmente toma 15–20 minutos. ¿Tiene tiempo ahora,
    o prefiere dejar un mensaje breve?
  submission:
    file_path: "./messages/<slug>/intakes/"
  case_types:
    - key: workers_comp
      display_name: "Workers' Compensation"
      display_name_es: "Compensación por accidentes laborales"
      questions:
        - key: caller_full_name
          prompt_en: "Could you start with your full legal name?"
          prompt_es: "¿Podría comenzar con su nombre legal completo?"
          required: true
          critical: true
          validation: text
        - key: employer
          prompt_en: "Who was your employer at the time of the accident?"
          prompt_es: "¿Quién era su empleador al momento del accidente?"
          required: true
          critical: false
          validation: text
```

Top-level fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | bool | No (default `false`) | Master switch. When `false`, the tools are unavailable and the INTAKES prompt section is omitted. |
| `preamble_en` | string | No | Heads-up disclosure Riley speaks before starting questions. Empty string disables the preamble. |
| `preamble_es` | string | No | Spanish version. If omitted, Riley translates `preamble_en` at call time (less reliable than a pre-translated string). |
| `submission` | object | Yes | Where partial + final intake JSONs are written. |
| `submission.file_path` | string | Yes | Directory for the JSON files. Must end with `/`. Recommend a sub-directory like `messages/<slug>/intakes/` so it's easy to find. |
| `case_types` | list | Yes | At least one case type required. |

---

## Question schema

Each `case_types[*]` entry has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | Yes | Canonical identifier passed to `record_intake_answer(case_type=...)`. Stable across question rewording. |
| `display_name` | string | Yes | Human-readable label shown in the email subject and in Riley's English speech. |
| `display_name_es` | string | No | Spanish display name. Used in Spanish-language calls. |
| `google_form_id` | string | No | Used by the sync CLI only. Not consulted at call time. |
| `questions` | list | Yes (≥1) | Question script. |

Each `questions[*]` entry has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | Yes | Canonical field name (e.g. `employer`, `accident_date`). Unique within a case type. Stable across reword changes. |
| `prompt_en` | string | Yes | The English question Riley reads verbatim. |
| `prompt_es` | string | No | Spanish translation. Strongly recommended for any business that takes Spanish calls. |
| `required` | bool | No (default `true`) | If `false`, Riley may skip the question if the caller declines. Required questions must be present in the final submission. |
| `validation` | `text`/`phone`/`email`/`date`/`yes_no` | No (default `text`) | Advisory shape. Influences the phrasing of the prompt but does not strictly enforce the answer's format. |
| `critical` | bool | No (default `false`) | If `true`, Riley reads the answer back per-character and waits for explicit "yes" before moving on. Use for legal name, callback number, email, DOB. |

---

## Spanish-language calls

When a caller starts speaking Spanish, Riley conducts the intake in Spanish
using each question's `prompt_es`. For each answer, `record_intake_answer`
is called with:

- `spoken_text` — the answer verbatim in Spanish.
- `language` — `"es"`.
- `english_summary` — Riley's concise English rendering of the same answer.

The intake email shows both — the original Spanish answer plus the English
summary — so a Spanish-speaking caller still produces a record that an
English-only intake-team member can scan.

For Spanish-speaking businesses that haven't pre-translated their questions,
omit `prompt_es` and Riley will translate `prompt_en` at call time. This is
less reliable than a pre-translated string but works as a fallback.

---

## Output: structured JSON + email

When `finalize_intake` is called, two artifacts are produced.

**1. Structured JSON file** under `submission.file_path`:

```
messages/<slug>/intakes/
├── intake_20260519_184530_room-abc.final.json
```

File contents:

```json
{
  "case_type": "workers_comp",
  "business_name": "Acme Law",
  "call_id": "room-abc",
  "caller_name": "Jane Doe",
  "callback_number": "+15551112222",
  "language": "en",
  "english_overview": "New WC intake, injured on the job at Acme Construction.",
  "status": "final",
  "started_at": "2026-05-19T18:42:11+00:00",
  "completed_at": "2026-05-19T18:55:48+00:00",
  "answers": [
    {
      "question_key": "caller_full_name",
      "prompt": "Could you start with your full legal name?",
      "spoken_text": "Jane Doe",
      "language": "en",
      "english_summary": "Jane Doe",
      "captured_at": "2026-05-19T18:43:02+00:00"
    },
    ...
  ]
}
```

**2. Email** at call-end via whichever EmailChannel(s) are configured in
`messages.channels`. Subject: `"Intake: <case type display> — <caller name>
[<business name>]"`. Body contains a per-question table (Question / Caller
answer / English summary), the English overview, and the full transcript
embedded at the bottom.

---

## Partial intakes (mid-call disconnects)

After every `record_intake_answer` call, a partial JSON file is written:

```
messages/<slug>/intakes/intake_room-abc.partial.json
```

If the caller hangs up before `finalize_intake` runs, the partial file is
the record. It has `status: "partial"`, no `completed_at`, and only the
answers captured so far. The intake email is NOT fired for partial-only
intakes — operators read the partial JSON directly.

When `finalize_intake` runs successfully, the partial file is removed and
the final JSON is written under a different name. The two files never
coexist.

---

## Mid-intake escape hatch

If the caller says mid-intake that they want to be called back, want to
speak to a person, or simply don't have time to finish, Riley is instructed
in the INTAKES prompt section to:

1. Stop calling `record_intake_answer`.
2. Call `take_message` immediately with at least the caller's name and
   callback number.
3. Note in the message that the intake was started but not completed.

The partial JSON file already on disk gives the receiving team whatever was
captured before the caller bailed.

---

## Tool reference

### `record_intake_answer(case_type, question_key, spoken_text, language, english_summary)`

Called after every answered question. Validates that `case_type` and
`question_key` exist in the configured intakes block. Persists the partial
JSON after every call.

Returns a short confirmation string the LLM uses as its tool reply
("Answer recorded for `<key>`. Proceed to the next question.").

### `finalize_intake(caller_name, callback_number, english_overview)`

Called exactly once at the end of the intake, after every required question
has been answered. Writes the final JSON, removes the partial, queues the
email for call-end, and records the `intake_submitted` lifecycle outcome.

Returns a short confirmation the LLM uses to wrap up the call.

---

## Operational tips

- **Critical-field readback**: mark legal name, callback number, and email
  with `critical: true`. Riley will read these back per-character (digit by
  digit for phone, letter by letter for name/email) before moving on. This
  catches the most expensive transcription mistakes.
- **Disclose call length upfront**: the `preamble_en` exists so the caller
  can decline a long intake and just leave a message. Don't skip this — a
  surprised caller who hangs up halfway through is worse than a caller who
  knows what they're getting into.
- **One submission per call**: only one intake per call is supported.
  Re-calling `finalize_intake` replaces the prior submission; the final
  email goes out exactly once at call-end.
- **No email channel, no email**: if you enable intakes but have no email
  channel configured in `messages.channels`, the structured JSON file is
  the only artifact. That's a supported deployment (file-only) but make
  sure your intake team knows to watch the directory.
- **Stable keys**: once you set a `case_type.key` or a `question.key`, keep
  it stable across question-wording changes. Downstream consumers (the
  intake team's filtering, future CMS sync, ad-hoc grep) all rely on the
  keys, not the prompts.

---

See also:

- [`configuration-reference.md`](configuration-reference.md#intakes) — full schema reference
- [`function-tools-reference.md`](function-tools-reference.md) — `record_intake_answer` and `finalize_intake` details
