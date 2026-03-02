[![GitHub stars](https://img.shields.io/github/stars/kirklandsig/AIReceptionist?style=flat-square)](https://github.com/kirklandsig/AIReceptionist/stargazers)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)](https://www.python.org/downloads/)
[![OpenAI Realtime API](https://img.shields.io/badge/OpenAI-Realtime%20API-412991?style=flat-square)](https://platform.openai.com/docs/guides/realtime)
[![LiveKit](https://img.shields.io/badge/LiveKit-Voice%20Agent-FF6B35?style=flat-square)](https://livekit.io/)
[![Status](https://img.shields.io/badge/status-active%20development-orange?style=flat-square)](#)

> **This project is in active development.** Core functionality works (voice conversations, FAQ answering, call transfers, message taking), but expect breaking changes and rough edges. Contributions welcome.

# AI Receptionist -- Open Source, Self-Hosted, No Compromises

A production-grade, open-source AI receptionist that answers your business phone calls using OpenAI's Realtime API -- the same speech-to-speech model that powers ChatGPT Advanced Voice. Self-hosted. No vendor lock-in. No monthly SaaS fees bleeding you dry.

**This is not another cascaded STT-to-LLM-to-TTS hack.** This is a direct speech-to-speech AI voice agent built on the highest-fidelity model available today, connected to your phone system via LiveKit and SIP. It sounds like a real person because it uses the same model that makes ChatGPT's voice mode sound like a real person.

If you have been paying $200-500/month for a SaaS AI receptionist that sounds robotic, interrupts callers, and takes 2 seconds to respond -- stop. Deploy this instead.

---

## Why This Exists

The current crop of AI receptionist SaaS products -- Bland AI, Vapi, Retell AI, Smith.ai, Ruby Receptionist, and the rest -- share the same fundamental problems:

- **High latency.** Most use a cascaded pipeline: transcribe speech to text, send text to an LLM, convert the LLM response back to speech. Each hop adds latency. Callers notice. It feels like talking to a machine on a bad connection.
- **Robotic voices.** Cheap TTS engines produce output that sounds like a GPS navigator reading a script. Callers hang up.
- **Poor turn-taking.** They interrupt you. They talk over you. They go silent for awkward stretches. Real conversations have natural rhythm -- these products do not.
- **Expensive subscriptions.** $200-500/month for what amounts to a wrapper around the same APIs you can call directly. You are paying a markup for a dashboard.
- **Vendor lock-in.** Your call flows, prompts, business logic, and caller data live on someone else's servers. Want to switch providers? Start over.
- **No data privacy.** Your callers' conversations, phone numbers, and messages sit in a third-party database you do not control.
- **Limited customization.** Want to change how call transfers work? Want a custom integration? Submit a feature request and wait.

This project solves all of it:

- **OpenAI Realtime API (speech-to-speech).** No transcription chain. The model hears the caller and speaks back directly. Sub-second response times. Natural turn-taking. The same model behind ChatGPT Advanced Voice.
- **Self-hosted.** Runs on your infrastructure. Your data stays on your servers. Full control.
- **No monthly SaaS fee.** You pay OpenAI for API usage (roughly $0.20-0.30/min) and that is it. No platform markup. No per-seat pricing. No "enterprise tier" upsell.
- **Fully configurable.** Business hours, FAQs, call routing, voice selection, personality -- all defined in a simple YAML file. Change anything, redeploy in seconds.
- **Multi-business from a single deployment.** One agent process handles calls for multiple businesses. Each phone number routes to its own config.
- **Open source under AGPL-3.0.** The code is yours. Fork it, modify it, extend it. Nobody can take this and lock it behind a paywall without releasing their changes.

---

## Comparison: This vs. SaaS AI Receptionists

| | **AIReceptionist (this project)** | **Typical SaaS AI Receptionist** |
|---|---|---|
| **Voice fidelity** | OpenAI Realtime speech-to-speech -- near-human quality | Cascaded STT + LLM + TTS -- robotic, high latency |
| **Response latency** | Sub-second (direct speech-to-speech) | 1-3 seconds (multi-hop pipeline) |
| **Turn-taking** | Natural, model-native | Awkward pauses, interruptions |
| **Monthly cost** | ~$0.20-0.30/min API usage only | $200-500/month subscription + per-minute overages |
| **Data privacy** | Your servers, your data | Third-party stores your call data |
| **Customization** | Full source code, modify anything | Limited to what their dashboard exposes |
| **Vendor lock-in** | None -- open source, standard SIP | Proprietary platform, migration is painful |
| **Multi-business** | Built in, single deployment | Usually requires separate accounts/plans |
| **Self-hosted** | Yes | No |
| **Source code access** | Full | None |

---

## Features

- Natural speech-to-speech conversations via OpenAI Realtime API
- Inbound phone call handling via SIP/Twilio/Telnyx
- FAQ answering from configurable knowledge base
- Call transfers to departments and specific people
- Message taking with file-based or webhook delivery
- Multi-business support from a single running agent
- Built-in noise cancellation optimized for phone audio (LiveKit BVC Telephony)
- YAML-based configuration -- no code changes needed to customize
- After-hours detection with configurable messages

## Prerequisites

- Python 3.11+
- OpenAI API key (with Realtime API access)
- LiveKit server ([self-hosted](https://docs.livekit.io/home/self-hosting/local/) or [LiveKit Cloud](https://cloud.livekit.io))
- SIP trunk provider (Twilio or Telnyx) with a phone number

## Quick Start

1. **Clone and install:**

```bash
git clone https://github.com/kirklandsig/AIReceptionist.git
cd AIReceptionist
pip install -e .
```

2. **Configure environment:**

```bash
cp .env.example .env
# Edit .env with your keys:
#   LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
```

3. **Configure your business:**

```bash
cp config/businesses/example-dental.yaml config/businesses/my-business.yaml
# Edit with your business name, FAQs, routing numbers, hours
```

4. **Set up telephony:**

Follow the [LiveKit SIP Trunk Setup Guide](https://docs.livekit.io/telephony/start/sip-trunk-setup/) to:
- Create an inbound SIP trunk pointing to your Twilio/Telnyx number
- Create a dispatch rule to route calls to the `receptionist` agent

5. **Run:**

```bash
python -m receptionist.agent dev
```

Call your phone number -- you should hear your AI receptionist answer with your custom greeting.

## Configuration

Each business is defined by a YAML file in `config/businesses/`. See `example-dental.yaml` for a complete example.

Key sections:
- `business` -- name, type, timezone
- `voice` -- OpenAI voice selection (coral, alloy, ash, ballad, echo, sage, shimmer, verse)
- `greeting` -- what the receptionist says when answering
- `personality` -- system prompt personality instructions
- `hours` -- business hours per day of week
- `after_hours_message` -- what to say when the office is closed
- `routing` -- departments/people the receptionist can transfer to
- `faqs` -- question/answer pairs the receptionist draws from
- `messages` -- how to store messages (file or webhook)

## Multi-Business Setup

One running agent can serve multiple businesses. Each inbound phone number maps to a business config via SIP dispatch rule metadata:

```json
{
  "metadata": "{\"config\": \"my-business\"}"
}
```

This loads `config/businesses/my-business.yaml`. Add as many business configs as you need -- one agent process handles them all.

## Cost

You pay OpenAI directly for Realtime API usage. There is no platform fee, no markup, no subscription.

**Estimated cost:** ~$0.20-0.30 per minute of conversation.

| Business type | Calls/day | Avg duration | Daily cost | Monthly cost |
|---|---|---|---|---|
| Small office | 10 | 2 min | ~$5 | ~$150 |
| Dental practice | 30 | 2 min | ~$15 | ~$450 |
| Busy front desk | 60 | 1.5 min | ~$22 | ~$660 |

Compare that to a SaaS AI receptionist at $300-500/month that sounds worse and gives you zero control. At higher call volumes the per-minute model costs more, but you get dramatically better quality and full ownership of the system. For most small-to-medium businesses, the cost is comparable or lower -- and the experience for your callers is not even close.

---

## Alternatives This Replaces

This project is a direct, self-hosted, open-source alternative to:

- **Bland AI** -- AI phone calls API. Cascaded pipeline, closed source, per-minute pricing with platform markup.
- **Vapi** -- Voice AI platform. Another middleman between you and the model. Vendor lock-in.
- **Retell AI** -- Conversational voice AI. Same cascaded architecture, same latency problems.
- **Smith.ai** -- Virtual receptionist service. Expensive, limited customization, your data on their servers.
- **Ruby Receptionist** -- Live + AI receptionist. Premium pricing for a service you can run yourself.

If you are evaluating any of these, try this first. It is free to deploy, and the voice quality speaks for itself.

---

## License

**AGPL-3.0**

This project is licensed under the [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html).

This means: you can use it, modify it, self-host it, and deploy it for your business with no restrictions. But if you run a modified version of this code as a hosted service (i.e., you let other people interact with it over a network), you must release your modifications under the same license.

**Why AGPL and not MIT?** Because this license specifically prevents companies from taking this code, wrapping it in a SaaS product, and charging people a monthly fee without giving anything back. The whole point of this project is that you should not have to pay rent on software you can run yourself. AGPL ensures it stays that way.

---

## Support the Project

If this saved you from a $300/month SaaS subscription, consider buying me a coffee.

**BTC:** `bc1q573f3x6zlsh06lcfetpmrquw5jr5e26ahu4syn`

**ETH:** `0x5d48560C58b65dc7FeECa2F452c2Df817d1d61CC`
