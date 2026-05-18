# Telephony Setup — Paths from PSTN to AIReceptionist

This guide covers the three realistic ways a public phone number ends up
ringing the AIReceptionist agent. Pick one based on what you already have.

> **Status note** — Paths A and B are exercised by the project's own
> deployments and the [RingCentral + Twilio guide](ringcentral-setup.md).
> Path C (keep-the-landline + FXS gateway + on-premise PBX) is documented
> here as a conceptual pattern with a starter Asterisk snippet, but the
> project does not currently smoke-test FXS-gateway hardware in CI.
> Treat the Path C snippet as a starting point, not a copy-paste guarantee.

---

## Table of Contents

- [Overview](#overview)
- [Path A — Port the number to a SIP trunk provider](#path-a--port-the-number-to-a-sip-trunk-provider)
- [Path B — BYOC (Bring Your Own Carrier)](#path-b--byoc-bring-your-own-carrier)
- [Path C — Keep the landline, add an FXS gateway + PBX](#path-c--keep-the-landline-add-an-fxs-gateway--pbx)
- [Trade-offs](#trade-offs)
- [E911 and reliability caveats](#e911-and-reliability-caveats)

---

## Overview

AIReceptionist always sits at the SIP-side of the chain. It registers with
LiveKit as a named worker (`receptionist` by default) and receives calls
that LiveKit's SIP gateway dispatches into rooms. **What it does NOT do is
own a PSTN number.** Something else has to take the call from the public
phone network and deliver it to LiveKit as a SIP INVITE.

```text
Caller's phone
    |
    v
+--------------------+
|  Public phone net  |   (PSTN: copper landline, mobile, VoIP carrier)
+--------------------+
    |
    v
+--------------------+
|  Number provider   |   Twilio / Telnyx / RingCentral / your local carrier
|  (owns the DID)    |
+--------------------+
    |   SIP INVITE
    v
+--------------------+
|  LiveKit SIP       |   Inbound trunk + dispatch rule
|  gateway (Cloud or |
|  self-hosted)      |
+--------------------+
    |   AgentJob
    v
+--------------------+
|  receptionist      |   This project, running anywhere with outbound
|  agent process     |   internet to LiveKit (laptop, VM, container)
+--------------------+
    |   Realtime audio
    v
+--------------------+
|  OpenAI Realtime   |
+--------------------+
```

Every path below is just a different way to make the second box fan out
SIP to LiveKit.

---

## Path A — Port the number to a SIP trunk provider

**When this is right:** you don't have a strong reason to keep your current
carrier; you'd rather have one provider for both the number and the SIP
delivery; you want the simplest operational story.

**Tested in this project:** yes — Twilio Elastic SIP Trunk →
LiveKit Cloud is the path the [RingCentral + Twilio guide](ringcentral-setup.md)
walks through, and the [deployment guide](deployment-guide.md) covers
Telnyx as the equivalent alternative.

### Setup at a glance

1. Pick a SIP trunking provider (Twilio Elastic SIP Trunking, Telnyx,
   Signalwire, Plivo, Bandwidth, Vonage, ...).
2. Port your existing phone number to that provider, OR buy a new DID
   from them.
3. Create an outbound SIP trunk in their dashboard.
4. Set the trunk's **Origination URI** to your LiveKit SIP endpoint:
   - LiveKit Cloud: `sip:<project-id>.sip.livekit.cloud;transport=tcp`
     (find `<project-id>` on the LiveKit Cloud Project Settings page;
     it is **not** always the same as your vanity WSS subdomain).
   - Self-hosted: the SIP URI of your LiveKit SIP gateway.
5. Associate the DID with the trunk so calls to that number flow out
   to LiveKit.
6. Enable SIP REFER on the trunk so the agent's `transfer_call` tool can
   transfer callers back through the carrier. On Twilio Elastic SIP
   Trunking this is `TransferMode=enable-all`; on Telnyx it's the
   "Call Transfer" toggle. Without this you'll get
   `403 Forbidden` on every transfer attempt.

### Pros

- **One provider, one bill.** Number + SIP termination + outbound minutes
  on one invoice.
- **Modern features**: SIP REFER, IPv6, TLS signaling, automated DID
  provisioning via REST API.
- **No hardware**. Nothing to plug in, nothing to maintain.

### Cons

- **Porting takes time.** Number portability from a legacy landline
  carrier is days to weeks and occasionally hits snags.
- **You give up the legacy carrier's voicemail/forwarding features**
  (you replace them with your own setup or with provider features).
- **Some carriers charge per-channel** instead of pay-as-you-go;
  read the pricing carefully if call volume is high.

### See also

- [Deployment Guide → SIP Trunk Setup](deployment-guide.md#sip-trunk-setup)
- [RingCentral + Twilio Setup](ringcentral-setup.md)
- [LiveKit SIP trunk setup](https://docs.livekit.io/telephony/start/sip-trunk-setup/)

---

## Path B — BYOC (Bring Your Own Carrier)

**When this is right:** you already pay a carrier you like, you want to
keep that relationship, but you also want LiveKit to handle the SIP →
agent leg.

**BYOC** ("Bring Your Own Carrier") is a feature offered by some SIP
providers — Telnyx is the most common one — that lets you point your
existing carrier's SIP origination at the BYOC provider as a transit, and
they deliver to your LiveKit endpoint. Twilio does not currently offer a
true BYOC product; their Elastic SIP Trunk is Path A.

### Setup at a glance

1. Confirm your existing carrier supports SIP delivery (most regional
   CLECs and competitive carriers do; pure-copper ILEC landlines do
   not — you'll need Path C for those).
2. Open a BYOC trunk at the transit provider (e.g. Telnyx BYOC).
3. Whitelist the transit provider's IPs / credentials with your existing
   carrier so they accept the SIP delivery target.
4. Configure the BYOC trunk's **outbound** target to your LiveKit SIP
   endpoint, same as Path A step 4.
5. Inbound caller-ID-handling rules differ from Path A — the From URI
   shape can be `sip:<digits>@<carrier-domain>` or `From: "<name>" <sip:+<E.164>@...>`.
   The AIReceptionist CallerID resolver handles both via the
   `sip.phoneNumber`, `sip.fromUser`, `sip.from`, and `sip_<digits>`
   identity fallback chain. If your carrier emits a shape we haven't seen,
   open an issue with the `agent.callerid` log lines.

### Pros

- **Keep your carrier relationship and your existing number.**
- **Often cheaper per-minute** than re-porting to a tier-1 SIP provider.
- **Carrier-side features** (E911 records, regulatory compliance) stay
  in place.

### Cons

- **More moving parts.** Two providers in the path means two places to
  blame when something breaks.
- **Variable SIP quirks.** Some carriers do strange things with `From`
  headers, P-Asserted-Identity, or codec negotiation. Expect to spend
  time on the first call diagnosing.
- **No SIP REFER on some carriers.** If your carrier strips REFER, you
  can't transfer back out via the carrier. You'd need to fall back to
  outbound dial via the BYOC trunk instead (more complex; not currently
  documented in this project).

---

## Path C — Keep the landline, add an FXS gateway + PBX

**When this is right:** you have a copper landline you cannot or will
not port (regulatory, customer-recognition, legacy fax line, etc.), AND
you have somewhere to plug in a small piece of hardware on-site.

**Status: conceptual.** This project doesn't ship a tested HT813
configuration. The pieces below are well-known patterns from the open-source
PBX community, but you should expect to iterate on this in a lab before
trusting it for production receptionist duties.

### What you need

- An **FXS gateway** (Analog Telephone Adapter) — Grandstream HT813,
  Cisco SPA112, Obihai/Poly OBi200, or similar. Plug the landline into
  the FXS port; the gateway converts copper analog to SIP packets.
- A **SIP server** to register the FXS gateway with and to provide the
  routing logic — Asterisk or FreePBX on a Raspberry Pi, a small VM, or
  your existing on-premise PBX.
- A **SIP transit** out of that PBX to LiveKit. Cheapest option is to
  open a small SIP trunk at any of the Path A providers and treat the
  PBX as the originator — even though no PSTN minutes flow through it,
  the trunk gives you a clean SIP delivery target.

### Topology

```text
+---------------+      +-------------+      +----------+
| Copper        | FXS  |  FXS        | SIP  | Asterisk |
| landline      |----->|  gateway    |----->|  / PBX   |
| (kept as-is)  |      | (HT813)     |      |          |
+---------------+      +-------------+      +-----+----+
                                                  |   SIP
                                                  v
                                       +---------------------+
                                       |  SIP trunk provider |
                                       |  (Path A) as transit|
                                       +---------------------+
                                                  |
                                                  v
                                       +---------------------+
                                       |   LiveKit SIP       |
                                       +---------------------+
```

### Minimum-viable Asterisk `pjsip.conf` snippet (starter, untested)

```ini
; ---------------------------------------------------------------
; HT813 FXS endpoint (the gateway registers here when it picks up
; the landline). Replace fxs-secret and the IP with your values.
; ---------------------------------------------------------------
[fxs-endpoint]
type = endpoint
transport = transport-udp
auth = fxs-auth
aors = fxs-aor
context = from-fxs
disallow = all
allow = ulaw
allow = alaw

[fxs-auth]
type = auth
auth_type = userpass
username = fxs
password = fxs-secret

[fxs-aor]
type = aor
max_contacts = 1

; ---------------------------------------------------------------
; Outbound trunk to your SIP transit (the Path A provider).
; ---------------------------------------------------------------
[livekit-trunk]
type = endpoint
transport = transport-udp
context = from-livekit
disallow = all
allow = ulaw
outbound_auth = livekit-trunk-auth
aors = livekit-trunk-aor

[livekit-trunk-auth]
type = auth
auth_type = userpass
username = your-trunk-username
password = your-trunk-password

[livekit-trunk-aor]
type = aor
contact = sip:<trunk-host>;transport=udp
```

And the matching `extensions.conf` dialplan:

```ini
[from-fxs]
; Every call from the landline goes to the trunk that forwards to LiveKit.
exten => _X.,1,Dial(PJSIP/livekit-trunk/sip:+15555550100@<trunk-host>)
exten => _X.,n,Hangup()

[from-livekit]
; Outbound (transfers) — adjust to your number plan.
exten => _NXXNXXXXXX,1,Dial(PJSIP/livekit-trunk/sip:+1${EXTEN}@<trunk-host>)
exten => _NXXNXXXXXX,n,Hangup()
```

Replace `<trunk-host>` with your transit provider's hostname, and
`+15555550100` with the DID at your transit provider that LiveKit's
inbound trunk matches.

### Pros

- **You keep your landline.** No porting, no regulatory paperwork.
- **Physical phones still work.** The PBX can ring your existing analog
  handsets in parallel with the AI agent.
- **Resilience**: if the PBX or AIReceptionist is down, the landline still
  rings the physical phone.

### Cons

- **Hardware to maintain.** FXS gateway + PBX host = two more things that
  can fail.
- **Power and internet sensitivity.** The PBX needs power and an
  internet route to your transit provider 24/7.
- **SIP/audio quirks.** Echo, AEC, codec compatibility, jitter on cheap
  hardware — you'll spend time tuning.
- **E911 caveats** (see below). If callers ever hear "press 1 for
  emergency" from your AI greeting, make absolutely sure 911 still works.

---

## Trade-offs

| Concern | Path A (SIP trunk provider) | Path B (BYOC) | Path C (FXS + PBX) |
|---|---|---|---|
| Hardware on-site | None | None | FXS gateway + PBX host |
| Port the number? | Yes | No | No |
| Keep existing carrier | No | Yes | Yes |
| Setup time | Hours | Days | Days to weeks |
| Time to first call | < 1 hour after provisioning | Days | Days |
| Ongoing failure modes | One vendor relationship | Two vendor relationships | Hardware + two vendors |
| Per-minute cost | Provider-published | Often lower than A | Carrier minutes + transit |
| Transfer support (SIP REFER) | Yes (enable in trunk settings) | Carrier-dependent | Asterisk handles via `Dial()` |
| Physical phone still rings? | No | No | Yes |
| Recommended for new deployments | Yes | If you have a carrier relationship | Only when porting is impossible |

---

## E911 and reliability caveats

- **AIReceptionist does NOT provide E911.** Neither LiveKit nor this
  project route to emergency services. Your number provider (Path A
  trunk, Path B BYOC, or Path C carrier) is responsible for 911 routing
  and address registration.
- **The agent's persona should NOT take emergency calls seriously.**
  Every shipped persona template includes language like *"If this is a
  medical emergency, please call 911"*. Do not remove it.
- **Internet outage = no AI receptionist.** Paths A and B fail entirely
  if your network goes down. Path C still rings the physical phone
  because the analog circuit is independent of internet — that's its
  main advantage.
- **Power outage at the PBX in Path C** kills the AI but the landline
  itself can still work (copper provides line voltage). Plan accordingly.
- **Caller's number privacy.** When the agent transfers a call, the
  destination's phone displays a caller ID that depends on the carrier's
  configuration: usually the original caller's number, sometimes your
  trunk's outbound caller ID. Verify the behavior with a test call
  before going live.
