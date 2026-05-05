# AI Receptionist — Documentation

An open-source, high-fidelity AI phone receptionist built on the **OpenAI Realtime API** (speech-to-speech) and the **LiveKit Agents SDK** (Python). Designed for small businesses — dental offices, law firms, medical clinics, and more — that need reliable inbound call handling with FAQ answering, call transfers, and message taking.

---

## Why AI Receptionist?

Traditional IVR systems frustrate callers with rigid menus. Human receptionists are expensive and unavailable 24/7. AI Receptionist bridges the gap:

- **Natural conversation** — powered by OpenAI's speech-to-speech Realtime API, callers interact with a human-sounding voice, not a robotic menu.
- **Config-driven** — every aspect of the receptionist's behavior (greeting, personality, hours, FAQs, routing) is defined in a single YAML file. No code changes needed.
- **Multi-business** — run one deployment that serves multiple businesses, each with its own configuration and phone number.
- **Open-source** — MIT-licensed, extensible, and built on well-supported foundations (LiveKit, OpenAI, Pydantic).

---

## Documentation Map

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | How the system works end-to-end: call flow, component responsibilities, data model, and design decisions. |
| [Configuration Reference](configuration-reference.md) | Complete reference for the YAML business configuration file — every field, every validation rule, every default. |
| [ChatGPT OAuth Setup](chatgpt-oauth-setup.md) | Use a ChatGPT/Codex login token for OpenAI Realtime so businesses can run from ChatGPT subscription entitlements instead of an API key. |
| [Deployment Guide](deployment-guide.md) | Step-by-step instructions for deploying with LiveKit Cloud or self-hosted LiveKit, including SIP trunk setup with Twilio and Telnyx. |
| [Development Guide](development-guide.md) | Local development setup, running tests, code organization, and contribution guidelines. |
| [Function Tools Reference](function-tools-reference.md) | Detailed reference for each of the four agent function tools: `lookup_faq`, `transfer_call`, `take_message`, and `get_business_hours`. |
| [Troubleshooting](troubleshooting.md) | Common issues, error messages, and their solutions. |
| [Multi-Business Setup](multi-business-setup.md) | How to run a single deployment that handles calls for multiple businesses with different phone numbers and configurations. |

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/your-org/ai-receptionist.git
cd ai-receptionist

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -e .

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your LiveKit and OpenAI credentials

# 5. Create your business config
cp config/businesses/example-dental.yaml config/businesses/my-business.yaml
# Edit my-business.yaml to match your business

# 6. Run the agent in development mode
python -m receptionist.agent dev
```

See the [Deployment Guide](deployment-guide.md) for production setup and the [Configuration Reference](configuration-reference.md) for full config details.

---

## Technology Stack

| Component | Technology | Role |
|-----------|-----------|------|
| Voice AI | OpenAI Realtime API | Speech-to-speech conversation (no separate STT/TTS) |
| Agent Framework | LiveKit Agents SDK (Python) | Agent lifecycle, session management, SIP integration |
| Noise Cancellation | LiveKit Noise Cancellation Plugin | BVCTelephony (SIP) / BVC (WebRTC) noise suppression |
| Configuration | Pydantic + PyYAML | Typed config models with validation |
| Transport | LiveKit Server + SIP | WebRTC-based media transport with PSTN bridging |
| SIP Trunking | Twilio / Telnyx | Connects PSTN phone numbers to LiveKit |

---

## Cost Estimate

| Component | Cost | Notes |
|-----------|------|-------|
| OpenAI Realtime API | ~$0.20-0.30/min | Speech-to-speech model usage |
| SIP Trunking | ~$0.01-0.02/min | Twilio or Telnyx per-minute rates |
| LiveKit Cloud | Varies | Free tier available; pay-as-you-go beyond that |
| **Typical dental office** | **~$450/month** | 30 calls/day, 2 min average call duration |

---

## Requirements

- **Python 3.11+** (tested on 3.14.2, Windows 11)
- **LiveKit Server** — Cloud account or self-hosted instance
- **OpenAI auth** — either an API key with Realtime API access or [ChatGPT OAuth](chatgpt-oauth-setup.md) through Codex CLI
- **SIP Trunk** — Twilio or Telnyx account for phone number connectivity

---

## Project Structure

```
AIReceptionist/
├── README.md                         # Project readme
├── pyproject.toml                    # Build config and dependencies
├── .env.example                      # Environment variable template
├── receptionist/
│   ├── __init__.py
│   ├── agent.py                      # Core agent logic and entry point
│   ├── config.py                     # Pydantic configuration models
│   ├── prompts.py                    # System prompt construction
│   └── messages.py                   # Message taking and delivery
├── config/businesses/
│   └── example-dental.yaml           # Example business configuration
├── tests/                            # Test suite (15 tests)
│   ├── test_config.py                # Config model tests (6)
│   ├── test_prompts.py               # Prompt generation tests (6)
│   └── test_messages.py              # Message handling tests (3)
└── docs/plans/                       # Design documents
```

---

## License

This project is open-source. See the LICENSE file in the repository root for details.

---

## Getting Help

- **Issues**: Open a GitHub issue for bugs or feature requests.
- **Discussions**: Use GitHub Discussions for questions and ideas.
- **Contributing**: See the [Development Guide](development-guide.md) for contribution guidelines.
