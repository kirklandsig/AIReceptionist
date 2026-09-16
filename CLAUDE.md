# CLAUDE.md — Instructions for Claude Code Agents

> This file is read automatically by Claude Code at the start of every session.
> It defines project conventions, mandatory workflows, and guardrails.

---

## Project Overview

**AIReceptionist** is a voice-based AI phone receptionist built on the **OpenAI Realtime API** (speech-to-speech) and the **LiveKit Agents SDK** (Python). It answers inbound SIP calls for small businesses: FAQ answers, business hours, call transfer, message taking, structured phone intakes (speech or keypad/DTMF), Google Calendar booking, emailed info packets, call recording/transcripts, and a consolidated call-end email with an AI summary.

### Key Facts

- **Language:** Python 3.11+ (dev environment uses 3.14.2; production VM runs 3.12)
- **Package manager:** pip with `pyproject.toml` (hatchling build backend); the virtualenv lives at the repo root in `venv/`
- **Validation:** Pydantic v2 for all configuration models
- **Agent framework:** LiveKit Agents SDK (`livekit-agents >= 1.8.2`, `AgentServer` + `@server.rtc_session`)
- **Voice AI:** OpenAI Realtime API (speech-to-speech, not cascaded STT/TTS). Default model `gpt-realtime-2.1`; production also runs `gpt-realtime-2.1` with `reasoning_effort: low` and `max_response_output_tokens: 1200`.
- **Config format:** YAML files in `config/businesses/`, validated through Pydantic
- **Production:** one worker on a DigitalOcean droplet under systemd (`receptionist.service`, `python -m receptionist.agent start`). Tenant YAML, `secrets/`, `.env` and `handoff.md` are gitignored and live only on the VM / laptop.

---

## Repository Structure

```
AIReceptionist/
├── CLAUDE.md                    # THIS FILE — agent instructions
├── handoff.md                   # Full project context (gitignored; local + VM only). READ FIRST.
├── README.md                    # Setup guide and configuration overview
├── pyproject.toml               # Project metadata and dependencies
├── .env.example                 # Environment variable template
├── .github/workflows/ci.yml     # pytest on Python 3.11 / 3.12
│
├── receptionist/                # Main application package
│   ├── agent.py                 # AgentServer entrypoint, handle_call, Receptionist (function tools), DTMF dispatch, idle timers, Realtime recovery
│   ├── config.py                # Pydantic v2 models, YAML loading, validation
│   ├── prompts.py               # System prompt builder from BusinessConfig
│   ├── lifecycle.py             # CallLifecycle: transcript capture, outcomes, call-end fan-out
│   ├── info_packets.py          # Emailed info packets (consent-gated, two-step destination confirm)
│   ├── voice_auth.py            # Realtime bearer resolution (api_key / oauth_static; oauth_codex is dead-but-retained)
│   ├── booking/                 # Google Calendar availability + booking
│   ├── email/                   # Email senders (SMTP, Resend) + templates
│   ├── intakes/                 # Structured intake questions, answers, storage (speech + DTMF)
│   ├── messaging/               # Message model + channels (file, webhook, email) + failure records
│   ├── recording/               # Call recording (local / S3)
│   ├── retention/               # Artifact retention sweeper
│   ├── transcript/              # Transcript writers + metadata
│   └── voice/                   # Voice auth setup CLI
│
├── config/businesses/           # Per-business YAML configuration files
│   ├── example-dental.yaml
│   └── example-workers-comp.yaml
│
├── tests/                       # pytest suite (~670 tests; mirrors the package layout)
├── documentation/               # Public-facing docs (architecture, config reference, troubleshooting, CHANGELOG, ...)
├── scripts/                     # Developer tooling (pre-commit hook, restart/status helpers)
└── messages/, recordings/, transcripts/, secrets/   # Runtime artifacts (gitignored)
```

---

## Conventions

### Code Style

- Use `from __future__ import annotations` at the top of every module.
- Use type hints everywhere. Prefer `str | None` over `Optional[str]` in new code.
- Use Pydantic v2 `BaseModel` for data models with validation. Use `@field_validator` and `@model_validator` for custom validation logic.
- Use `dataclasses.dataclass` for simple data containers without validation (e.g., `Message`).
- Use `logging.getLogger("receptionist")` for all logging. Never `print()` outside CLI entrypoints.
- Imports: standard library first, then third-party, then local. Separated by blank lines.

### Async Patterns

- The agent runs on an asyncio event loop. **Never block the event loop.**
- For any synchronous I/O (file writes, HTTP requests), wrap in `asyncio.to_thread()`.
- All agent tool functions are `async def` and decorated with `@function_tool()`.

### Security Conventions

- **Path validation:** Any user-supplied or metadata-supplied strings used in file paths MUST be validated against `^[a-zA-Z0-9_-]+$` (or stripped with `[^a-zA-Z0-9_-]+`) before use. Never construct file paths from raw external input.
- **Error sanitization:** Tool functions must log full errors server-side but return only generic, safe messages to the LLM. Never expose stack traces, file paths, or internal details through tool return values.
- **Safe YAML loading:** Always use `yaml.safe_load()`, never `yaml.load()`.
- **Explicit encoding:** Always use `encoding="utf-8"` when reading/writing files.
- **Secrets:** tenant YAMLs, `secrets/`, `.env`, tokens are never committed, echoed or logged.

### Configuration

- Business configs live in `config/businesses/*.yaml`.
- `RECEPTIONIST_AGENT_NAME` controls the LiveKit agent dispatch name. It defaults to `"receptionist"` for production; set `RECEPTIONIST_AGENT_NAME=""` only for local wildcard/dev dispatch testing.
- Environment variables are loaded from `.env.local` (takes priority) then `.env`.
- `voice.auth.type: api_key` is the only working Realtime auth. `oauth_codex` is retained for history, logs a deprecation WARNING at load, and produces dead air on calls.

### SDK-version-sensitive code (check before any livekit upgrade)

- `receptionist/agent.py` `_build_realtime_model_kwargs` / `_apply_realtime_options` detect `reasoning` and `update_options(max_response_output_tokens=)` by signature inspection and WARN when absent.
- `_RECOVERABLE_REALTIME_ERROR_HINTS` and `_BENIGN_ENGINE_CLOSED_MESSAGE` match SDK error/log text by substring. Re-verify the message shapes after an upgrade (last verified against 1.8.2).

---

## MANDATORY: Documentation Update Requirement

> **This is a non-negotiable rule. It applies to every code change.**

### Rule

Whenever ANY file inside `receptionist/` is created, modified, or deleted, the following documentation MUST be reviewed and updated if affected:

1. **`documentation/` directory** — Review for accuracy. If the change affects architecture, configuration, function tools, deployment, development workflow, or troubleshooting, update the corresponding file.

2. **`handoff.md`** — Append a terse dated addendum for every significant change (module interfaces, features, behavior, dependencies, dev/deploy workflow, live incidents and their root causes). It is gitignored; it is still the authoritative project memory.

3. **`documentation/CHANGELOG.md`** — Add an entry under `[Unreleased]` for every user-visible change. Keep a Changelog format (Added, Changed, Deprecated, Removed, Fixed, Security).

### Mapping: Code File to Documentation

| Code file changed | Documentation to review |
|---|---|
| `receptionist/agent.py` | `documentation/architecture.md`, `documentation/function-tools-reference.md`, `documentation/troubleshooting.md` |
| `receptionist/config.py` | `documentation/architecture.md`, `documentation/configuration-reference.md` |
| `receptionist/prompts.py` | `documentation/architecture.md` |
| `receptionist/lifecycle.py`, `transcript/`, `recording/`, `retention/` | `documentation/architecture.md`, `documentation/configuration-reference.md` |
| `receptionist/messaging/`, `receptionist/email/` | `documentation/architecture.md`, `documentation/function-tools-reference.md`, `documentation/configuration-reference.md` |
| `receptionist/intakes/`, `receptionist/info_packets.py` | `documentation/intakes-setup.md`, `documentation/function-tools-reference.md` |
| `receptionist/booking/` | `documentation/google-calendar-setup.md`, `documentation/function-tools-reference.md` |
| `receptionist/voice_auth.py`, `receptionist/voice/` | `documentation/configuration-reference.md`, `documentation/chatgpt-oauth-setup.md` |
| `pyproject.toml` | `documentation/development-guide.md`, `documentation/deployment-guide.md` |
| `config/businesses/*.yaml` | `documentation/configuration-reference.md`, `documentation/multi-business-setup.md` |

### Workflow

1. Make the code change.
2. Run `pytest` to verify tests pass.
3. Review the mapping table above and update stale content.
4. Add a CHANGELOG entry if applicable; append to `handoff.md` if significant.
5. Stage all changed files together in the same commit.

---

## Testing

- **Always run `pytest` before committing.** Commits with failing tests must not be created.
- All tests must pass (~670 tests; 2 are skipped by design). Tests live under `tests/`, mirroring the package layout (`tests/test_<module>.py`, `tests/<subpackage>/`).
- Any new module gets a corresponding test file. Warning/log paths are asserted with `caplog` on the `receptionist` logger.

```bash
pytest                       # Run all tests
pytest -v                    # Verbose output
pytest tests/test_config.py  # Run a specific test file
```

---

## Git Conventions

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`.
- A pre-commit hook is installed via `bash scripts/install-hooks.sh`. It warns if `receptionist/` files changed without `documentation/` changes and runs `pytest`, blocking the commit on failure. Never bypass it with `--no-verify`.
- CI (`.github/workflows/ci.yml`) runs the suite on Python 3.11 and 3.12 for every push to `main` and every pull request.

---

## Development Workflow

```bash
source venv/Scripts/activate            # Windows Git Bash (venv is at the repo root)
pip install -e ".[dev]"                 # first time / after dependency changes
pytest
python -m receptionist.agent dev        # local worker (the SDK warns that `dev` is deprecated in favor of `lk agent dev`; harmless)
```

Production deploy: `ssh` to the VM as the `receptionist` user, `git pull`, `venv/bin/pip install -e .` if dependencies changed, then `systemctl restart receptionist` and watch `journalctl -u receptionist -f` for a clean registration + warmup. Details and rollback snapshots are in `handoff.md`.

---

## Key Gotchas

- `livekit-agents` requires Python `<3.15`. The dev environment runs 3.14.2; production runs 3.12.
- Config names from job metadata are validated against `^[a-zA-Z0-9_-]+$` — do not weaken this regex.
- The laptop copy of the tenant YAML (`config/businesses/licomplaw.yaml`, gitignored) is stale and does not serve calls. The VM copy is the production source of truth; never rsync the laptop copy to the VM.
- `handoff.md` and `HANDOFF.md` are the same file on Windows (case-insensitive FS). Append; do not create a second one.
- Realtime counts audio as tokens and re-sends the system prompt every turn. Mid-call dead air with `rate_limit_exceeded` in the journal is an OpenAI usage-tier problem, not a code bug.
