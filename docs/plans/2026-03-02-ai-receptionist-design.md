# AI Receptionist Design

## Problem

Existing AI receptionist products deliver poor conversational fidelity in production environments. This is primarily a cost-driven problem — vendors use cheap cascaded STT-LLM-TTS pipelines with budget models at each stage, resulting in high latency, awkward turn-taking, and unnatural speech.

## Goal

Build the highest-fidelity open-source AI phone receptionist using the best available voice model (OpenAI Realtime API, speech-to-speech). Target: small businesses (dental offices, law firms, etc.) that need inbound call handling with FAQ answering and call transfers.

## Architecture

```
Phone Network (PSTN)
        │ SIP
SIP Trunk Provider (Twilio / Telnyx)
        │ SIP
LiveKit Server (self-hosted or cloud)
  - WebRTC transport
  - Room management
  - SIP bridge
        │ WebRTC audio
LiveKit Agent (Python)
  ├── Noise Cancellation (BVC Telephony)
  ├── OpenAI Realtime API (speech-to-speech)
  └── Receptionist Agent
        ├── Business config (YAML)
        ├── FAQ knowledge
        ├── Call routing / transfer
        └── Message taking
```

### Key Architectural Decisions

- **OpenAI Realtime API** as the single voice model — no STT/TTS pipeline. Highest fidelity, ~$0.20-0.30/min.
- **LiveKit Agents SDK (Python)** handles real-time audio transport, SIP bridging, turn detection, interruption handling. This is the same infrastructure OpenAI uses for ChatGPT Advanced Voice.
- **LiveKit noise cancellation (BVC Telephony)** cleans phone audio before it reaches the model.
- **File-based configuration (YAML)** — no database required. Each business has one config file.
- **Multi-business support** — one running agent process serves multiple businesses, selected by inbound phone number metadata.

## Agent Structure

The receptionist is a LiveKit `Agent` subclass with function tools:

```python
class Receptionist(Agent):
    def __init__(self, config: BusinessConfig):
        super().__init__(instructions=build_system_prompt(config))
        self.config = config

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=f"Greet the caller with: '{self.config.greeting}'"
        )

    @function_tool()
    async def lookup_faq(self, ctx, question: str):
        """Look up the answer to a frequently asked question"""

    @function_tool()
    async def transfer_call(self, ctx, department: str):
        """Transfer the caller to a specific department or person"""

    @function_tool()
    async def take_message(self, ctx, caller_name: str, message: str, callback_number: str):
        """Take a message when no one is available"""

    @function_tool()
    async def get_business_hours(self, ctx):
        """Check current business hours and whether the business is open"""
```

### Function Tool Details

- **lookup_faq**: Searches the business config's FAQ list. The full FAQ list is included in the system prompt so the LLM can reason over it directly. This tool exists for structured logging of which FAQs were accessed.
- **transfer_call**: Maps department name to phone number from config, uses LiveKit's `transfer_sip_participant` API for cold transfer. Informs caller before transferring.
- **take_message**: Captures caller name, message, and callback number. Stores via configurable delivery (file, webhook, or email in future).
- **get_business_hours**: Checks current time against configured hours to determine if business is open/closed and what hours apply today.

## Business Configuration

Each business is defined by a YAML file:

```yaml
business:
  name: "Acme Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  model: "openai-realtime"
  voice_id: "coral"

greeting: "Thank you for calling Acme Dental, how can I help you today?"

personality: |
  You are a warm, professional receptionist for a dental office.
  Be concise but friendly. If you don't know something, offer to
  take a message or transfer to the office manager.

hours:
  monday:    { open: "08:00", close: "17:00" }
  tuesday:   { open: "08:00", close: "17:00" }
  wednesday: { open: "08:00", close: "12:00" }
  thursday:  { open: "08:00", close: "17:00" }
  friday:    { open: "08:00", close: "15:00" }
  saturday:  closed
  sunday:    closed

after_hours_message: |
  Our office is currently closed. Our regular hours are Monday
  through Friday. Would you like to leave a message?

routing:
  - name: "Front Desk"
    number: "+15551234567"
    description: "General inquiries, scheduling"
  - name: "Dr. Smith"
    number: "+15551234568"
    description: "Direct line for urgent dental issues"
  - name: "Billing"
    number: "+15551234569"
    description: "Insurance and payment questions"

faqs:
  - question: "Do you accept my insurance?"
    answer: "We accept most major dental insurance plans including Delta Dental, Cigna, Aetna, and MetLife."
  - question: "How do I schedule an appointment?"
    answer: "I can transfer you to our front desk to schedule, or you can book online at acmedental.com/book."
  - question: "Where are you located?"
    answer: "We're at 123 Main Street, Suite 200, Springfield."

messages:
  delivery: "file"
  file_path: "./messages/acme-dental/"
```

Config is validated at load time using Pydantic models.

## Project Structure

```
AIReceptionist/
├── pyproject.toml
├── .env.example
├── receptionist/
│   ├── __init__.py
│   ├── agent.py          # Receptionist Agent class + function tools + server entry point
│   ├── config.py          # BusinessConfig Pydantic model + YAML loader
│   ├── prompts.py         # System prompt builder from config
│   └── messages.py        # Message storage (file / webhook delivery)
├── config/
│   └── businesses/
│       └── example-dental.yaml
├── messages/
└── tests/
    ├── test_config.py
    ├── test_prompts.py
    └── test_messages.py
```

## Entry Point

```python
server = AgentServer()

@server.rtc_session(agent_name="receptionist")
async def handle_call(ctx: agents.JobContext):
    config = load_business_config(ctx)

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(voice=config.voice.voice_id)
    )

    await session.start(
        room=ctx.room,
        agent=Receptionist(config),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        ),
    )

    await session.generate_reply(
        instructions=f"Greet the caller with: '{config.greeting}'"
    )
```

Multi-business routing: SIP dispatch rules attach metadata indicating which business config to load, keyed by the inbound phone number.

## Dependencies

- `livekit-agents` — core agent framework
- `livekit-plugins-openai` — OpenAI Realtime integration
- `livekit-plugins-noise-cancellation` — BVC telephony noise cancellation
- `pydantic` — config validation
- `pyyaml` — YAML parsing

No database, no web framework, no queue system.

## Deployment

**Prerequisites:**
1. OpenAI API key
2. LiveKit server (self-hosted via Docker, or LiveKit Cloud)
3. SIP trunk provider (Twilio/Telnyx) + phone number

**Setup:**
```bash
git clone <repo>
cd AIReceptionist
pip install -e .
cp .env.example .env
# Edit .env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
cp config/businesses/example-dental.yaml config/businesses/my-business.yaml
# Edit config, then:
python -m receptionist.agent dev
```

Target: clone to working receptionist in under 30 minutes.

## Future Additions (Post-MVP)

These are planned but not part of the initial build:

- **Call recordings** — LiveKit Egress API for room recording
- **Call transcripts** — capture text transcripts from OpenAI Realtime alongside audio
- **Email notifications** — extend message delivery to support SMTP/SendGrid
- **Cascaded pipeline mode** — alternative to OpenAI Realtime using Deepgram STT + Claude/GPT-4o + ElevenLabs TTS for cost-conscious users
- **Web widget channel** — browser-based voice widget using WebRTC directly
- **Admin dashboard** — web UI for managing configs, viewing transcripts, analytics

## Cost Estimate

Per-call cost using OpenAI Realtime API:

| Call Duration | Estimated Cost |
|---|---|
| 1 minute | ~$0.25 |
| 3 minutes | ~$0.75 |
| 5 minutes | ~$1.25 |

Plus telephony costs (~$0.01-0.02/min for SIP trunk) and LiveKit infrastructure (free if self-hosted, usage-based on cloud).

For a dental office receiving 30 calls/day averaging 2 minutes each: ~$15/day or ~$450/month in API costs. Comparable to a part-time receptionist's hourly wage for a single shift.
