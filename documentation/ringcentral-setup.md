# RingCentral + Twilio Setup

This guide covers the current law-firm deployment path: RingEX Standard rings the two human receptionists and a Twilio DID in parallel; Twilio forwards that DID to LiveKit SIP; LiveKit dispatches the call to the `receptionist` agent with `config=licomplaw`.

The goal is to avoid RingCentral BYOC dependency for v1. RingCentral remains the office phone system; Twilio is only the bridge number that lets the AI answer as another ring-group member.

---

## Target Call Flow

```text
Caller
  -> RingCentral main number / reception call queue
  -> Human receptionist 1 rings
  -> Human receptionist 2 rings
  -> Twilio AI bridge DID rings
  -> Twilio SIP trunk forwards to LiveKit SIP
  -> LiveKit dispatch rule starts agentName=receptionist, metadata={"config":"licomplaw"}
  -> AIReceptionist loads local config/businesses/licomplaw.yaml and answers as Adriana
```

RingCentral should use normal simultaneous ringing / first-answer-wins behavior. If a human receptionist answers first, RingCentral cancels the Twilio leg. If Twilio/AI answers first, the AI handles the call.

---

## Prerequisites

- RingEX Standard admin access.
- Twilio account with one voice-capable local DID for the AI bridge.
- LiveKit Cloud project with SIP enabled.
- AIReceptionist deployed with `RECEPTIONIST_AGENT_NAME=receptionist` or the default unset value.
- Local `config/businesses/licomplaw.yaml` copied from `config/businesses/example-licomplaw.yaml` and populated with real claims-rep transfer numbers.
- Email sender env var set for intake delivery: `LICOMPLAW_RESEND_API_KEY` if using the checked-in Resend config.

---

## 1. Configure AIReceptionist

Create the local law-firm config from the tracked template:

```bash
cp config/businesses/example-licomplaw.yaml config/businesses/licomplaw.yaml
```

`licomplaw.yaml` is gitignored by design so tenant-specific rep names, DIDs, and sender settings stay local.

Current choices in that config:

| Setting | Value |
|---|---|
| Receptionist name | Adriana |
| Greeting disclosure | No AI disclosure language |
| Recording | Enabled |
| Recording consent preamble | Disabled |
| Transcripts | JSON + Markdown, local storage |
| Intake email recipient | `reception@licomplaw.com` |
| Transfer options | 15 placeholders, replace before go-live |

Before go-live, replace every `+1555...` placeholder in `routing` with a reachable E.164 number. Direct-dial DIDs are safest. Internal RingCentral extensions usually are not enough unless your SIP trunk and RingCentral tenant expose a dialable URI for those extensions.

Run the agent locally against this config:

```bash
RECEPTIONIST_CONFIG=licomplaw python -m receptionist.agent dev
```

For LiveKit Playground-only testing without named dispatch, use:

```bash
RECEPTIONIST_AGENT_NAME="" RECEPTIONIST_CONFIG=licomplaw python -m receptionist.agent dev
```

---

## 2. Create the LiveKit SIP Dispatch Rule

Create `licomplaw-dispatch.json`:

```json
{
  "dispatch_rule": {
    "name": "LICOMP Law AI Receptionist",
    "trunk_ids": ["ST_REPLACE_WITH_TWILIO_TRUNK_ID"],
    "rule": {
      "dispatchRuleIndividual": {
        "roomPrefix": "licomplaw-"
      }
    },
    "roomConfig": {
      "agents": [
        {
          "agentName": "receptionist",
          "metadata": "{\"config\": \"licomplaw\"}"
        }
      ]
    }
  }
}
```

Create it with the LiveKit CLI:

```bash
lk sip dispatch create licomplaw-dispatch.json
```

If using the LiveKit Cloud dashboard JSON editor, omit the outer `dispatch_rule` wrapper and paste the inner object.

---

## 3. Configure Twilio

1. Buy or choose a voice-capable Twilio DID for the AI bridge.
2. Create an Elastic SIP Trunk for AIReceptionist.
3. In **Origination**, add the LiveKit SIP URI from your LiveKit SIP trunk setup.
4. Associate the Twilio DID with the Elastic SIP Trunk.
5. If transfers need to dial back out to claims reps, configure Twilio Termination credentials and ensure LiveKit is allowed to use the trunk for outbound SIP transfer attempts.

Keep the Twilio DID dedicated to the AI bridge. RingCentral should call this DID as an external number; callers should not dial it directly unless you want to bypass the human receptionists.

---

## 4. Add the Twilio DID to RingCentral

In RingCentral Admin Portal:

1. Open the reception call queue / ring group that currently rings the two human receptionists.
2. Add the Twilio AI bridge DID as an external number or external member.
3. Use simultaneous ringing / first-answer-wins routing if available.
4. Disable voicemail on the Twilio bridge leg; unanswered calls should continue through RingCentral's normal queue behavior.
5. Place a test call to the main number and confirm only one party answers: either a human receptionist or Adriana.

RingEX UI labels vary by tenant. If RingEX Standard does not allow an external number inside the reception queue, use a forwarding rule or a dedicated queue member that forwards to the Twilio DID.

---

## 5. Transfer Targets

The AI can transfer only to entries in `routing`. For this deployment, keep the list hand-curated to the 10-15 claims reps the firm actually wants exposed.

Preferred transfer target order:

1. Claims rep direct DID in E.164 format, for example `+15165550123`.
2. Department or queue DID in E.164 format.
3. SIP URI only if the RingCentral/Twilio/LiveKit path is verified to accept it.

Avoid putting all ~50 attorney extensions in the AI config. More routes make the model's transfer choice less deterministic and expose people who are not supposed to receive intake calls.

---

## 6. Validation Checklist

- Start worker with default agent name: `python -m receptionist.agent start`.
- Confirm worker logs show it registered as `receptionist`.
- Confirm LiveKit dispatch metadata is `{"config":"licomplaw"}`.
- Call the Twilio DID directly; Adriana should answer with no AI or recording disclosure language.
- Call the RingCentral main number; verify first-answer-wins between humans and AI.
- Ask for a known placeholder route after replacing numbers; verify SIP transfer reaches the right claims rep.
- Leave a message; verify file storage and email to `reception@licomplaw.com`.
- Hang up; verify transcript JSON/Markdown and local recording are written.

---

## Open Items Before Go-Live

- Replace the provisional display name if the firm wants wording other than `L.I. Compensation Law`.
- Replace all 15 claims-rep placeholder routes.
- Confirm whether RingEX Standard in this tenant supports external numbers in the reception call queue.
- Confirm the Twilio DID and LiveKit SIP trunk IDs.
- Set `LICOMPLAW_RESEND_API_KEY` or switch the config to SMTP.
- Decide whether recordings stay local or move to S3/R2 for retention and backup.
