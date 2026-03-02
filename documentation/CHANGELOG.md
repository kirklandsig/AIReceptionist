# Changelog

All notable changes to the AI Receptionist project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Configurable voice model via `voice.model` field in business YAML (defaults to `"gpt-realtime"`)
- Telnyx recommended as primary SIP provider in deployment documentation
- AGPL-3.0 license
- SEO-optimized README with SaaS competitor comparison
- API key leak detection in pre-commit hook (OpenAI, LiveKit, AWS, GitHub, Stripe)
- Active development notice and badges in README
- Donation addresses (BTC, ETH)
- CLAUDE.md with project instructions and mandatory documentation update rules
- Git pre-commit hook (`scripts/pre-commit`) that warns on undocumented code changes and runs pytest
- Hook installer script (`scripts/install-hooks.sh`)
- This changelog file (`documentation/CHANGELOG.md`)

### Changed
- Agent model is now configurable per-business (was hardcoded to plugin default)

---

## [0.1.0] - 2026-03-02

Initial release of the AI Receptionist.

### Added

#### Core Agent
- `receptionist/agent.py` — LiveKit Agents SDK integration with `AgentServer` and `Receptionist` class
- `Receptionist.on_enter()` — automatic greeting on call pickup
- `Receptionist.lookup_faq()` — function tool for FAQ matching (case-insensitive substring)
- `Receptionist.transfer_call()` — function tool for SIP call transfer via LiveKit API
- `Receptionist.take_message()` — function tool for recording caller messages
- `Receptionist.get_business_hours()` — function tool for timezone-aware hours checking
- Multi-business support via job metadata routing (`load_business_config`)
- Noise cancellation (BVCTelephony for SIP, BVC for WebRTC)

#### Configuration
- `receptionist/config.py` — Pydantic v2 models for business configuration
- YAML-based business configuration (`config/businesses/example-dental.yaml`)
- Models: `BusinessInfo`, `VoiceConfig`, `DayHours`, `WeeklyHours`, `RoutingEntry`, `FAQEntry`, `DeliveryMethod`, `MessagesConfig`, `BusinessConfig`
- Time format validation (HH:MM 24-hour), cross-field validation, safe YAML loading

#### Prompt System
- `receptionist/prompts.py` — builds natural-language system prompts from business config
- Includes business identity, personality, hours, routing, FAQs, and behavioral rules

#### Message Storage
- `receptionist/messages.py` — `Message` dataclass and file-based persistence
- JSON file output with microsecond-precision timestamps
- Webhook delivery stubbed (not yet implemented)

#### Security
- Path traversal protection on config name resolution (`^[a-zA-Z0-9_-]+$`)
- Error sanitization in tool functions (generic messages to LLM, full details in server logs)
- Non-blocking I/O via `asyncio.to_thread()` for file operations
- Safe YAML loading (`yaml.safe_load`), explicit UTF-8 encoding

#### Testing
- `tests/test_config.py` — 6 tests for YAML parsing, validation, and edge cases
- `tests/test_prompts.py` — 6 tests for prompt content verification
- `tests/test_messages.py` — 3 tests for file I/O and directory creation
- Total: 15 tests, all passing

#### Documentation
- `README.md` — setup guide and configuration reference
- `HANDOFF.md` — comprehensive project handoff document
- `documentation/index.md` — documentation landing page
- `documentation/architecture.md` — system architecture and design decisions
- `docs/plans/` — design document and implementation plan
