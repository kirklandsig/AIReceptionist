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
- **No monthly SaaS fee.** Use a normal OpenAI API key or authenticate with a ChatGPT/Codex OAuth token so eligible ChatGPT subscriptions can power Realtime. No platform markup, no per-seat pricing, no "enterprise tier" upsell.
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
| **Monthly cost** | API-key usage or ChatGPT subscription auth; no platform fee | $200-500/month subscription + per-minute overages |
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
- OpenAI auth: either an API key with Realtime API access or ChatGPT OAuth via Codex CLI
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
# Edit .env with your LiveKit keys:
#   LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
# Add OPENAI_API_KEY, or configure ChatGPT OAuth in your business YAML.
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

### OpenAI Realtime Auth

The default path is still `OPENAI_API_KEY`, but each business can also use a
ChatGPT subscription login through Codex OAuth:

```yaml
voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"
  auth:
    type: "oauth_codex"
    path: "secrets/my-business/openai_auth.json"
```

Set it up with:

```bash
python -m receptionist.voice setup my-business
```

See [`documentation/chatgpt-oauth-setup.md`](documentation/chatgpt-oauth-setup.md)
for the full guide, including multi-business token files and refresh behavior.

## Message delivery channels

A business can route messages to one or more destinations simultaneously via `messages.channels`:

```yaml
messages:
  channels:
    - type: "file"
      file_path: "./messages/<business>/"
    - type: "email"
      to: ["owner@example.com"]
      include_transcript: true
      include_recording_link: true
    - type: "webhook"
      url: "https://hooks.slack.com/services/..."
      headers:
        X-Api-Key: ${SLACK_TOKEN}
```

- **file** -- writes JSON to disk; the most reliable channel and always awaited synchronously
- **email** -- requires the top-level `email` section; supports SMTP or Resend
- **webhook** -- POSTs `{"message": ..., "context": ...}` to the URL

Email and webhook run in the background with 3-attempt exponential backoff. Exhausted failures land in `<file_path>/.failures/` and can be inspected with:

```bash
python -m receptionist.messaging list-failures
```

## Call recording and transcripts

Enable in a business YAML:

```yaml
recording:
  enabled: true
  storage:
    type: "local"        # or "s3"
    local:
      path: "./recordings/<business>/"
  consent_preamble:
    enabled: true
    text: "This call may be recorded for quality purposes."

transcripts:
  enabled: true
  storage:
    type: "local"
    path: "./transcripts/<business>/"
  formats: ["json", "markdown"]
```

Recording uses LiveKit Egress; credentials for S3 come from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in the environment. The consent preamble is spoken **before** the greeting -- required for two-party consent states (CA, FL, IL, MD, MA, MT, NV, NH, PA, WA).

## Email delivery

Enable the top-level `email` section when using an email channel or `on_call_end` trigger:

```yaml
email:
  from: "receptionist@acmedental.com"
  sender:
    type: "smtp"   # or "resend"
    smtp:
      host: "smtp.gmail.com"
      port: 587
      username: ${SMTP_USERNAME}
      password: ${SMTP_PASSWORD}
      use_tls: true
  triggers:
    on_message: true    # email when take_message fires
    on_call_end: false  # email a summary after every call
```

## Multi-language

```yaml
languages:
  primary: "en"
  allowed: ["en", "es", "fr"]
```

`gpt-realtime-1.5` auto-detects the caller's language. If the caller speaks one of the allowed languages, the agent responds in that language for the rest of the call. If the caller speaks an un-whitelisted language, the agent politely redirects in `primary`.

## Retention

```yaml
retention:
  recordings_days: 90
  transcripts_days: 90
  messages_days: 0       # 0 = keep forever
```

Run on a schedule (cron / Windows Task Scheduler):

```bash
python -m receptionist.retention sweep
# or preview
python -m receptionist.retention sweep --dry-run
```

The sweeper never touches `.failures/` directories.

## Multi-Business Setup

One running agent can serve multiple businesses. Each inbound phone number maps to a business config via SIP dispatch rule metadata:

```json
{
  "metadata": "{\"config\": \"my-business\"}"
}
```

This loads `config/businesses/my-business.yaml`. Add as many business configs as you need -- one agent process handles them all.

## Cost

You can authenticate Realtime with either a normal OpenAI API key or a
ChatGPT/Codex OAuth token. API-key deployments pay OpenAI Platform usage
directly. ChatGPT OAuth deployments use the signed-in ChatGPT account's
subscription entitlements when that account has access to the configured
Realtime model. There is no AIReceptionist platform fee or markup.

**Estimated cost:** ~$0.20-0.30 per minute of conversation.

| Business type | Calls/day | Avg duration | Daily cost | Monthly cost |
|---|---|---|---|---|
| Small office | 10 | 2 min | ~$5 | ~$150 |
| Dental practice | 30 | 2 min | ~$15 | ~$450 |
| Busy front desk | 60 | 1.5 min | ~$22 | ~$660 |

Compare that to a SaaS AI receptionist at $300-500/month that sounds worse and gives you zero control. At higher call volumes the per-minute model costs more, but you get dramatically better quality and full ownership of the system. For most small-to-medium businesses, the cost is comparable or lower -- and the experience for your callers is not even close.

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
- **`book_appointment(caller_name, callback_number, proposed_start_iso, notes?, caller_email?)`** —
  books one of the offered slots. When `caller_email` is provided, the caller
  is added as an OPTIONAL Google attendee and Google sends them the standard
  `.ics` invite. Optional attendees don't impact the organizer's free/busy
  if they decline.

The agent always says the proposed time back to the caller and waits for
"yes" before booking. Events are tagged UNVERIFIED so staff know the
caller's identity wasn't verified.

See `documentation/google-calendar-setup.md` for step-by-step setup of
both auth paths (service account for Workspace, OAuth for any account).

Optional: set `email.triggers.on_booking: true` to email staff whenever a
booking lands (uses the existing email channel).

## SIP transfer URI (Asterisk + non-standard PBX)

By default, transfer-to-DID uses `tel:{number}`, which works for Twilio,
Telnyx, and most BYOC SIP trunks that translate tel-URIs to SIP. If your
trunk is **Asterisk classic `sip.conf`** (chan_sip, not pjsip), it rejects
tel-URIs — you'll see transfers fail. Add a `sip:` block to your business
config to override the URI scheme:

```yaml
sip:
  transfer_uri_template: "sip:{number}"          # local DID lookup on Asterisk
  # transfer_uri_template: "sip:{number}@asterisk.local"  # remote PBX
```

The default (`tel:{number}`) is preserved for everyone else; the field is
only needed when your trunk doesn't accept tel-URIs.

Credit to @trinicomcom (issue #6) for surfacing this.

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
