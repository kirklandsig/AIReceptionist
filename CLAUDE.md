# CLAUDE.md — Instructions for Claude Code Agents

> This file is read automatically by Claude Code at the start of every session.
> It defines project conventions, mandatory workflows, and guardrails.

---

## Project Overview

**AIReceptionist** is a voice-based AI phone receptionist built on the **OpenAI Realtime API** (speech-to-speech) and the **LiveKit Agents SDK** (Python). It answers inbound calls for small businesses, provides FAQ answers, checks business hours, transfers calls, and takes messages.

### Key Facts

- **Language:** Python 3.11+ (development environment uses 3.14.2; production should target 3.11 or 3.12)
- **Package manager:** pip with `pyproject.toml` (hatchling build backend)
- **Validation:** Pydantic v2 for all configuration models
- **Agent framework:** LiveKit Agents SDK (`livekit-agents >= 1.0.0`)
- **Voice AI:** OpenAI Realtime API (speech-to-speech, not cascaded STT/TTS)
- **Config format:** YAML files in `config/businesses/`, validated through Pydantic

---

## Repository Structure

```
AIReceptionist/
├── CLAUDE.md                    # THIS FILE — agent instructions
├── HANDOFF.md                   # Full project context for handoffs (KEEP UPDATED)
├── README.md                    # Setup guide and configuration reference
├── pyproject.toml               # Project metadata and dependencies
├── .env.example                 # Environment variable template
│
├── receptionist/                # Main application package
│   ├── __init__.py
│   ├── agent.py                 # Agent server, session handler, Receptionist class
│   ├── config.py                # Pydantic v2 models, YAML loading, validation
│   ├── prompts.py               # System prompt builder from BusinessConfig
│   └── messages.py              # Message dataclass, file/webhook save logic
│
├── config/businesses/           # Per-business YAML configuration files
│   └── example-dental.yaml
│
├── tests/                       # Test suite (pytest)
│   ├── test_config.py
│   ├── test_prompts.py
│   └── test_messages.py
│
├── documentation/               # Public-facing documentation (open-source docs)
│   ├── index.md
│   ├── architecture.md
│   ├── CHANGELOG.md
│   └── ... (additional docs)
│
├── docs/plans/                  # Internal design documents and plans
│
├── scripts/                     # Developer tooling
│   ├── install-hooks.sh         # Installs git pre-commit hook
│   └── pre-commit               # The pre-commit hook script
│
└── messages/                    # Runtime message storage (gitignored)
```

---

## Conventions

### Code Style

- Use `from __future__ import annotations` at the top of every module.
- Use type hints everywhere. Prefer `str | None` over `Optional[str]` in new code.
- Use Pydantic v2 `BaseModel` for data models with validation. Use `@field_validator` and `@model_validator` for custom validation logic.
- Use `dataclasses.dataclass` for simple data containers without validation (e.g., `Message`).
- Use `logging.getLogger("receptionist")` for all logging. Never `print()`.
- Imports: standard library first, then third-party, then local. Separated by blank lines.

### Async Patterns

- The agent runs on an asyncio event loop. **Never block the event loop.**
- For any synchronous I/O (file writes, HTTP requests), wrap in `asyncio.to_thread()`.
- All agent tool functions are `async def` and decorated with `@function_tool()`.

### Security Conventions

- **Path validation:** Any user-supplied or metadata-supplied strings used in file paths MUST be validated against `^[a-zA-Z0-9_-]+$` before use. Never construct file paths from raw external input.
- **Error sanitization:** Tool functions must log full errors server-side but return only generic, safe messages to the LLM. Never expose stack traces, file paths, or internal details through tool return values.
- **Safe YAML loading:** Always use `yaml.safe_load()`, never `yaml.load()`.
- **Explicit encoding:** Always use `encoding="utf-8"` when reading/writing files.
- **Async I/O for blocking ops:** Wrap all blocking I/O in `asyncio.to_thread()` to avoid audio glitches.

### Configuration

- Business configs live in `config/businesses/*.yaml`.
- The `agent_name` is currently `""` (empty string) for development — this makes the agent accept all dispatches. In production, set `agent_name="receptionist"` and configure LiveKit dispatch rules.
- Environment variables are loaded from `.env.local` (takes priority) then `.env`.

---

## MANDATORY: Documentation Update Requirement

> **This is a non-negotiable rule. It applies to every code change.**

### Rule

Whenever ANY file inside `receptionist/` is created, modified, or deleted, the following documentation MUST be reviewed and updated if affected:

1. **`documentation/` directory** — Review all files in `documentation/` for accuracy. If the code change affects architecture, configuration, function tools, deployment, development workflow, or troubleshooting, update the corresponding documentation file.

2. **`HANDOFF.md`** — This file MUST be updated on every significant change. "Significant" means any change that alters module interfaces, adds/removes features, changes behavior, modifies dependencies, or affects the development/deployment workflow. Update the relevant sections (module breakdown, repository structure, testing, known issues, etc.).

3. **`documentation/CHANGELOG.md`** — Add an entry under the `[Unreleased]` section for every user-visible change. Follow the Keep a Changelog format (Added, Changed, Deprecated, Removed, Fixed, Security).

### Mapping: Code File to Documentation

| Code file changed | Documentation to review |
|---|---|
| `receptionist/agent.py` | `documentation/architecture.md`, `documentation/function-tools-reference.md`, `documentation/troubleshooting.md`, `HANDOFF.md` sections 2, 4.4, 6 |
| `receptionist/config.py` | `documentation/architecture.md`, `documentation/configuration-reference.md`, `HANDOFF.md` sections 4.1, 5 |
| `receptionist/prompts.py` | `documentation/architecture.md`, `HANDOFF.md` section 4.2 |
| `receptionist/messages.py` | `documentation/architecture.md`, `documentation/function-tools-reference.md`, `HANDOFF.md` sections 4.3 |
| `pyproject.toml` | `documentation/development-guide.md`, `HANDOFF.md` section 7 |
| `config/businesses/*.yaml` | `documentation/configuration-reference.md`, `documentation/multi-business-setup.md` |
| `tests/*` | `HANDOFF.md` section 9 |

### Workflow

1. Make the code change.
2. Run `pytest` to verify tests pass.
3. Review the mapping table above.
4. Open each affected documentation file and verify accuracy.
5. Update any stale content.
6. Add a CHANGELOG entry if applicable.
7. Update HANDOFF.md if the change is significant.
8. Stage all changed files together in the same commit.

---

## Testing

### Requirements

- **Always run `pytest` before committing.** Commits with failing tests must not be created.
- All tests must pass. There are currently 15 tests across 3 test files.
- Test files follow the naming convention `tests/test_<module>.py`.

### Running Tests

```bash
pytest                       # Run all tests
pytest -v                    # Verbose output
pytest tests/test_config.py  # Run a specific test file
```

### What to Test

- Config parsing and validation (test_config.py)
- Prompt content generation (test_prompts.py)
- Message file I/O (test_messages.py)
- Any new module should have a corresponding test file

---

## Git Conventions

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  - `feat:` new features
  - `fix:` bug fixes
  - `docs:` documentation changes
  - `chore:` maintenance, tooling, dependencies
  - `test:` test additions or changes
  - `refactor:` code restructuring without behavior change
- A pre-commit hook is installed via `scripts/install-hooks.sh`. It:
  - Warns if `receptionist/` files changed but no `documentation/` files were staged.
  - Runs `pytest` and blocks the commit if tests fail.

### Installing the Pre-Commit Hook

```bash
bash scripts/install-hooks.sh
```

---

## Development Workflow

```bash
# 1. Activate the virtual environment
source .venv/Scripts/activate   # Windows Git Bash

# 2. Make your changes

# 3. Run tests
pytest

# 4. Update documentation (if code in receptionist/ changed)

# 5. Stage and commit
git add <files>
git commit -m "feat: description of change"

# 6. Run the agent locally
python -m receptionist.agent dev
```

---

## Key Gotchas

- `livekit-agents` officially requires Python `<3.14`. The dev environment runs 3.14.2 which may cause subtle issues. Production should use 3.11 or 3.12.
- The `_send_webhook()` function in `messages.py` is stubbed (`NotImplementedError`). Do not call it in tests without mocking.
- The `messages/` directory is gitignored. It is created at runtime when the first message is saved.
- Config names from job metadata are validated against `^[a-zA-Z0-9_-]+$` — do not weaken this regex.
