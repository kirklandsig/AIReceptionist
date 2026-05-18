# RingCentral + Twilio Setup

This guide covers a generic law-firm-style deployment pattern:
RingCentral RingEX rings the firm's human receptionists and a Twilio DID
in parallel; Twilio forwards that DID to LiveKit SIP; LiveKit dispatches
the call to the `receptionist` agent with the business's configured slug.

The pattern avoids RingCentral BYOC dependency. RingCentral remains the
office phone system; Twilio is only the bridge number that lets the AI
answer as another ring-group member.

Throughout this guide, `<slug>` is a placeholder for whichever business
slug the operator picks (e.g. `acme-law`, `example-workers-comp`, etc.).
Any concrete examples use `example-workers-comp` to match the tracked
template at `config/businesses/example-workers-comp.yaml`.

---

## Target Call Flow

```text
Caller
  -> RingCentral main number / reception call queue
  -> Human receptionist 1 rings
  -> Human receptionist 2 rings
  -> Twilio AI bridge DID rings
  -> Twilio SIP trunk forwards to LiveKit SIP
  -> LiveKit dispatch rule starts agentName=receptionist, metadata={"config":"<slug>"}
  -> AIReceptionist loads local config/businesses/<slug>.yaml and answers
```

RingCentral should use normal simultaneous ringing / first-answer-wins
behavior. If a human receptionist answers first, RingCentral cancels the
Twilio leg. If Twilio/AI answers first, the AI handles the call.

---

## Prerequisites

- RingEX (or equivalent) admin access.
- Twilio account with one voice-capable local DID for the AI bridge.
- LiveKit Cloud project with SIP enabled.
- AIReceptionist deployed with `RECEPTIONIST_AGENT_NAME=receptionist` or
  the default unset value.
- Local `config/businesses/<slug>.yaml` copied from
  `config/businesses/example-workers-comp.yaml` and populated with real
  claims-rep transfer numbers, real intake email, and real sender
  credentials.
- Email sender env var configured. The tracked template uses
  `EXAMPLE_RESEND_API_KEY` as the placeholder name; rename it in your
  local YAML to something tenant-specific (e.g. `ACMELAW_RESEND_API_KEY`)
  and set the value in `.env`. Or switch the local YAML's `email.sender`
  block to SMTP with a Gmail app password / SES / etc.

---

## 1. Configure AIReceptionist

Create the local config from the tracked template:

```bash
cp config/businesses/example-workers-comp.yaml config/businesses/<slug>.yaml
```

`<slug>.yaml` is gitignored by design so tenant-specific rep names, DIDs,
intake emails, and sender settings stay local.

Defaults in the tracked template (override per tenant):

| Setting | Template value | Tenant action |
|---|---|---|
| Business name | `Example Workers' Comp Law` | Replace with firm name |
| Receptionist persona name | `Alex` | Replace with chosen agent name |
| AI-disclosure language in greeting | Off | Operator choice |
| Recording | Enabled (local file storage) | Switch to S3/R2 before LiveKit Cloud production |
| Recording consent preamble | Disabled | Enable + set text in two-party-consent jurisdictions |
| Transcripts | JSON + Markdown, local storage | Keep |
| Intake email recipient | `intake@example.com` | Replace with real intake address |
| Resend env var | `EXAMPLE_RESEND_API_KEY` | Rename + set value, or switch to SMTP |
| Transfer options | 15 obvious `+1555...` placeholders | Replace before go-live |

Before go-live, replace every `+1555...` placeholder in `routing` with a
reachable E.164 number. Direct-dial DIDs are safest. Internal RingCentral
extensions usually are not enough unless your SIP trunk and RingCentral
tenant expose a dialable URI for those extensions.

Run the agent locally against this config:

```bash
RECEPTIONIST_CONFIG=<slug> python -m receptionist.agent dev
```

For LiveKit Playground-only testing without named dispatch, use:

```bash
RECEPTIONIST_AGENT_NAME="" RECEPTIONIST_CONFIG=<slug> python -m receptionist.agent dev
```

---

## 2. Create the LiveKit SIP Dispatch Rule

Create `<slug>-dispatch.json`:

```json
{
  "dispatch_rule": {
    "name": "<Display name> AI Receptionist",
    "trunk_ids": ["ST_REPLACE_WITH_LIVEKIT_INBOUND_TRUNK_ID"],
    "rule": {
      "dispatchRuleIndividual": {
        "roomPrefix": "<slug>-"
      }
    },
    "roomConfig": {
      "agents": [
        {
          "agentName": "receptionist",
          "metadata": "{\"config\": \"<slug>\"}"
        }
      ]
    }
  }
}
```

Create it with the LiveKit CLI:

```bash
lk sip dispatch create <slug>-dispatch.json
```

If using the LiveKit Cloud dashboard JSON editor, omit the outer
`dispatch_rule` wrapper and paste the inner object.

---

## 3. Configure Twilio

1. Buy or choose a voice-capable Twilio DID for the AI bridge.
2. Create an Elastic SIP Trunk for AIReceptionist with
   `TransferMode=enable-all` so SIP REFER works (without this, the
   agent's `transfer_call` tool returns 403 Forbidden).
3. In **Origination**, add the LiveKit SIP URI from your LiveKit SIP
   trunk setup. The URI format is
   `sip:<project-id>.sip.livekit.cloud;transport=tcp`, where
   `<project-id>` is your LiveKit project ID with the `p_` prefix
   removed. Find it on the LiveKit Cloud Project Settings page; it is
   **not** always the same as your vanity WSS subdomain.
4. Associate the Twilio DID with the Elastic SIP Trunk.
5. If transfers need to dial back out via Twilio (instead of via SIP
   REFER), configure Twilio Termination credentials and ensure LiveKit
   is allowed to use the trunk for outbound SIP transfer attempts.

Keep the Twilio DID dedicated to the AI bridge. RingCentral should call
this DID as an external number; callers should not dial it directly
unless you want to bypass the human receptionists.

---

## 4. Add the Twilio DID to RingCentral

In RingCentral Admin Portal:

1. Open the reception call queue / ring group that currently rings the
   human receptionists.
2. Add the Twilio AI bridge DID as an external number or external
   member.
3. Use simultaneous ringing / first-answer-wins routing if available.
4. Disable voicemail on the Twilio bridge leg; unanswered calls should
   continue through RingCentral's normal queue behavior.
5. Place a test call to the main number and confirm only one party
   answers: either a human receptionist or the AI.

RingEX UI labels vary by tenant. If RingEX Standard does not allow an
external number inside the reception queue, use a forwarding rule or a
dedicated queue member that forwards to the Twilio DID.

---

## 5. Transfer Targets

The AI can transfer only to entries in `routing`. For this deployment,
keep the list hand-curated to the 10-15 (or up to ~30) reps the firm
actually wants exposed.

Preferred transfer target order:

1. Direct DID in E.164 format, for example `+15165550123`.
2. Department or queue DID in E.164 format.
3. SIP URI only if the RingCentral/Twilio/LiveKit path is verified to
   accept it.

Avoid putting all ~50 attorney extensions in the AI config. More routes
make the model's transfer choice less deterministic, exposes people who
are not supposed to receive intake calls, and adds tokens to the system
prompt on every call.

---

## 6. Validation Checklist

- Start worker with default agent name: `python -m receptionist.agent start`.
- Confirm worker logs show it registered as `receptionist`.
- Confirm LiveKit dispatch metadata is `{"config":"<slug>"}`.
- Call the Twilio DID directly; the agent should answer with no AI or
  recording disclosure language.
- Call the RingCentral main number; verify first-answer-wins between
  humans and AI.
- Ask for a known placeholder route after replacing numbers; verify
  SIP transfer reaches the right rep.
- Leave a message; verify file storage and email to the configured
  intake address.
- Hang up; verify transcript JSON/Markdown and local recording are
  written.

---

## Open Items Before Go-Live

- Replace the placeholder business display name in `business.name`.
- Replace the placeholder receptionist persona name in `personality:`
  and `greeting:`.
- Replace all 15 claims-rep placeholder routes.
- Confirm whether your RingEX tier supports external numbers in the
  reception call queue. If not, use a forwarding rule or a dedicated
  queue member.
- Confirm the Twilio DID and LiveKit SIP trunk IDs are wired correctly
  (origination + termination).
- Set the email sender env var your local YAML references (e.g.
  `<TENANT>_RESEND_API_KEY` or SMTP credentials) and verify a real call
  produces an email at the intake address.
- Decide whether recordings stay local or move to S3/R2 for retention
  and backup. **LiveKit Cloud rejects local-file recording egress**; if
  recording on LiveKit Cloud, you must use S3-compatible storage.
