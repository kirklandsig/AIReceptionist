# Multi-Business Setup

This guide explains how to run a single AI Receptionist deployment that handles calls for multiple businesses, each with its own phone number, configuration, and behavior.

---

## Table of Contents

- [Overview](#overview)
- [How Multi-Business Routing Works](#how-multi-business-routing-works)
- [Step-by-Step Setup](#step-by-step-setup)
  - [Step 1: Create Business Configurations](#step-1-create-business-configurations)
  - [Step 2: Provision Phone Numbers](#step-2-provision-phone-numbers)
  - [Step 3: Create SIP Trunks](#step-3-create-sip-trunks)
  - [Step 4: Create Dispatch Rules](#step-4-create-dispatch-rules)
  - [Step 5: Deploy the Agent](#step-5-deploy-the-agent)
- [Configuration Organization](#configuration-organization)
- [Message Isolation](#message-isolation)
- [Example: Three-Business Setup](#example-three-business-setup)
- [Monitoring Multiple Businesses](#monitoring-multiple-businesses)
- [Scaling Considerations](#scaling-considerations)
- [Common Patterns](#common-patterns)
- [Troubleshooting Multi-Business Issues](#troubleshooting-multi-business-issues)

---

## Overview

AI Receptionist supports a multi-tenant architecture where a single running agent process serves multiple businesses. Each inbound call is routed to the correct business configuration based on metadata attached to the SIP dispatch rule in LiveKit.

```
Phone Number A ──► SIP Trunk A ──► Dispatch Rule (config: "acme-dental")  ──┐
                                                                              │
Phone Number B ──► SIP Trunk B ──► Dispatch Rule (config: "smith-law")    ──┤── Agent
                                                                              │
Phone Number C ──► SIP Trunk C ──► Dispatch Rule (config: "city-clinic")  ──┘
```

Each call gets:
- Its own YAML configuration (greeting, FAQs, hours, routing, etc.)
- Its own voice and personality
- Its own message storage
- Complete isolation from other businesses

---

## How Multi-Business Routing Works

### The Config Selection Process

When a call arrives, the agent determines which business configuration to use through this process:

1. **LiveKit creates a room** for the incoming call.
2. **Job metadata** is attached to the room based on the SIP dispatch rule. This metadata contains a `"config"` key with the business slug.
3. **`load_business_config(ctx)`** in `agent.py`:
   a. Reads `ctx.job.metadata` and looks for the `"config"` key.
   b. Validates the slug against `^[a-zA-Z0-9_-]+$` (security: path traversal protection).
   c. Loads `config/businesses/<slug>.yaml`.
4. If no metadata is found, the agent **falls back** to the first YAML file (alphabetically) in `config/businesses/`.

### The Metadata Flow

```
SIP Dispatch Rule
  metadata: '{"config": "acme-dental"}'
       │
       ▼
LiveKit Room Created
  room.metadata → '{"config": "acme-dental"}'
       │
       ▼
Agent handle_call()
  ctx.job.metadata → {"config": "acme-dental"}
       │
       ▼
load_business_config()
  slug = "acme-dental"
  path = "config/businesses/acme-dental.yaml"
       │
       ▼
BusinessConfig loaded and validated
```

---

## Step-by-Step Setup

### Step 1: Create Business Configurations

Create a separate YAML file for each business in `config/businesses/`:

```
config/businesses/
├── acme-dental.yaml
├── smith-law.yaml
└── city-clinic.yaml
```

Each file is a complete, independent configuration. See [Configuration Reference](configuration-reference.md) for the full field reference.

**Naming rules**:
- Use lowercase alphanumeric characters, hyphens, and underscores only.
- The filename (without `.yaml`) becomes the slug used in dispatch rules.
- Examples: `acme-dental`, `smith_law_firm`, `downtown-clinic-nyc`

### Step 2: Provision Phone Numbers

Each business needs its own phone number. Purchase numbers from your SIP trunk provider:

**Twilio**:
1. Go to **Phone Numbers > Manage > Buy a Number** in the Twilio Console.
2. Purchase one number per business.
3. Note each number and its intended business.

**Telnyx**:
1. Go to **Numbers > Search & Buy** in the Telnyx Portal.
2. Purchase one number per business.

| Business | Phone Number | Config Slug |
|----------|-------------|-------------|
| Acme Dental | +15551001001 | `acme-dental` |
| Smith Law | +15551001002 | `smith-law` |
| City Clinic | +15551001003 | `city-clinic` |

### Step 3: Create SIP Trunks

You can use a single SIP trunk for all numbers or separate trunks per business. The dispatch rule (not the trunk) determines routing.

**Single trunk approach** (simpler):
- One SIP trunk handles all inbound numbers.
- Dispatch rules differentiate by the called number (DID).

**Separate trunk approach** (more isolation):
- One SIP trunk per business.
- Each trunk is associated with one phone number.
- Dispatch rules match by trunk ID.

### Step 4: Create Dispatch Rules

This is the critical step. Each dispatch rule maps an inbound call to a business configuration.

#### Using LiveKit CLI

Create one JSON file per business and change `agentName` only if the worker's `RECEPTIONIST_AGENT_NAME` is not `receptionist`:

```json
{
  "dispatch_rule": {
    "name": "Acme Dental Receptionist",
    "trunk_ids": ["ST_acme_trunk_id"],
    "rule": {
      "dispatchRuleIndividual": {
        "roomPrefix": "call-acme-"
      }
    },
    "roomConfig": {
      "agents": [
        {
          "agentName": "receptionist",
          "metadata": "{\"config\": \"acme-dental\"}"
        }
      ]
    }
  }
}
```

Then create the rule with `lk sip dispatch create acme-dental-dispatch.json`. Repeat for `smith-law` and `city-clinic`, changing the trunk ID, room prefix, and metadata config slug.

**Key parameters**:

| Parameter | Purpose |
|-----------|---------|
| `trunk_ids` | Matches inbound calls from specific SIP trunks |
| `rule.dispatchRuleIndividual.roomPrefix` | Prefix for per-call room names |
| `roomConfig.agents[].agentName` | Dispatches the named worker; default is `receptionist` |
| `roomConfig.agents[].metadata` | JSON string with the `"config"` key specifying the business slug |

#### Using LiveKit Cloud Dashboard

1. Go to **SIP > Dispatch Rules**.
2. Create a new rule for each business.
3. Use the JSON editor so you can set `roomConfig.agents[].agentName` and metadata.
4. The agent metadata JSON string must include `{"config": "<slug>"}`.

### Step 5: Deploy the Agent

Deploy a single agent instance. It will handle calls for all businesses:

```bash
python -m receptionist.agent start
```

The agent automatically selects the correct configuration for each call based on the dispatch rule metadata. No code changes are needed to support multiple businesses.

For the RingCentral law-firm path, see [RingCentral + Twilio Setup](ringcentral-setup.md). That guide uses the same metadata pattern with `{"config":"<your-slug>"}` and a Twilio DID added to the RingCentral reception group as an external member. The tracked template is `config/businesses/example-workers-comp.yaml`.

---

## Configuration Organization

### Directory Structure

```
config/businesses/
├── acme-dental.yaml         # Acme Dental configuration
├── smith-law.yaml            # Smith Law Firm configuration
├── city-clinic.yaml          # City Clinic configuration
└── example-dental.yaml       # Example template (can be kept or removed)
```

### Shared vs. Unique Settings

While each YAML file is independent, you can establish conventions across businesses:

| Setting | Typically Shared | Typically Unique |
|---------|-----------------|------------------|
| `voice.voice_id` | Sometimes (org-wide voice) | Often (personality match) |
| `greeting` | Never | Always |
| `personality` | Sometimes (industry-wide template) | Usually |
| `hours` | Rarely | Always |
| `routing` | Never | Always |
| `faqs` | Rarely | Usually |
| `messages.channels` | Often (org-wide policy) | Sometimes |

### Template Approach

For organizations managing many similar businesses (e.g., a franchise), maintain a template:

```
config/businesses/
├── _template-dental.yaml     # Template (underscore prefix = not auto-loaded)
├── acme-dental.yaml          # Based on template
├── bright-dental.yaml        # Based on template
└── smile-dental.yaml         # Based on template
```

The underscore prefix is a convention. Config slugs starting with `_` are still valid but typically indicate templates, not active configs.

---

## Message Isolation

### Per-Business Message Directories

Configure each business to store messages in a separate directory:

```yaml
# acme-dental.yaml
messages:
  channels:
    - type: "file"
      file_path: "messages/acme-dental/"

# smith-law.yaml
messages:
  channels:
    - type: "file"
      file_path: "messages/smith-law/"

# city-clinic.yaml
messages:
  channels:
    - type: "file"
      file_path: "messages/city-clinic/"
```

Create the directories:
```bash
mkdir -p messages/acme-dental
mkdir -p messages/smith-law
mkdir -p messages/city-clinic
```

### Message File Identification

Each message JSON file includes the `business_name` field, so messages are identifiable even if stored in a shared directory:

```json
{
  "caller_name": "Jane Doe",
  "callback_number": "555-123-4567",
  "message": "Please call me back about my appointment.",
  "business_name": "Acme Dental",
  "timestamp": "2026-03-02T14:30:25.123456+00:00"
}
```

---

## Example: Three-Business Setup

Here is a complete example of setting up three businesses on a single deployment.

### Business 1: Acme Dental

**config/businesses/acme-dental.yaml**:
```yaml
business:
  name: "Acme Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "coral"

greeting: "Thank you for calling Acme Dental. How can I help you today?"

personality: |
  You are a warm, professional dental office receptionist. You are patient
  and speak clearly. You avoid medical jargon.

hours:
  monday: { open: "08:00", close: "17:00" }
  tuesday: { open: "08:00", close: "17:00" }
  wednesday: { open: "08:00", close: "17:00" }
  thursday: { open: "08:00", close: "17:00" }
  friday: { open: "08:00", close: "15:00" }
  saturday: "closed"
  sunday: "closed"

after_hours_message: |
  Acme Dental is currently closed. We're open Monday through Thursday
  8 AM to 5 PM, and Friday 8 AM to 3 PM. For dental emergencies,
  please call 911.

routing:
  - name: "Scheduling"
    number: "+15551001001"
    description: "Book or change appointments"
  - name: "Billing"
    number: "+15551001002"
    description: "Insurance and payment questions"

faqs:
  - question: "What insurance do you accept?"
    answer: "We accept Delta Dental, Cigna, Aetna, and MetLife."
  - question: "Do you accept new patients?"
    answer: "Yes, we are currently accepting new patients."

messages:
  channels:
    - type: "file"
      file_path: "messages/acme-dental/"
```

### Business 2: Smith Law Firm

**config/businesses/smith-law.yaml**:
```yaml
business:
  name: "Smith & Associates Law Firm"
  type: "law firm"
  timezone: "America/Chicago"

voice:
  voice_id: "sage"

greeting: "Thank you for calling Smith and Associates. How may I direct your call?"

personality: |
  You are a polished, professional legal receptionist. You speak formally
  and never offer legal advice or opinions. You are careful about
  confidentiality and always offer to have an attorney call back.

hours:
  monday: { open: "09:00", close: "18:00" }
  tuesday: { open: "09:00", close: "18:00" }
  wednesday: { open: "09:00", close: "18:00" }
  thursday: { open: "09:00", close: "18:00" }
  friday: { open: "09:00", close: "17:00" }
  saturday: "closed"
  sunday: "closed"

after_hours_message: |
  Smith and Associates is currently closed. Our office hours are Monday
  through Thursday 9 AM to 6 PM, and Friday 9 AM to 5 PM. If you have
  an urgent legal matter, please leave a message and an attorney will
  contact you as soon as possible.

routing:
  - name: "Family Law"
    number: "+15552001001"
    description: "Divorce, custody, and family matters"
  - name: "Estate Planning"
    number: "+15552001002"
    description: "Wills, trusts, and estate matters"
  - name: "General Inquiry"
    number: "+15552001003"
    description: "All other legal inquiries"

faqs:
  - question: "Do you offer free consultations?"
    answer: "We offer a complimentary 30-minute initial consultation for new clients."
  - question: "What areas of law do you practice?"
    answer: "We specialize in family law, estate planning, and general civil litigation."

messages:
  channels:
    - type: "file"
      file_path: "messages/smith-law/"
```

### Business 3: City Clinic

**config/businesses/city-clinic.yaml**:
```yaml
business:
  name: "City Health Clinic"
  type: "medical clinic"
  timezone: "America/Los_Angeles"

voice:
  voice_id: "ash"

greeting: "City Health Clinic, how can I help you?"

personality: |
  You are a compassionate, efficient medical clinic receptionist. You are
  warm but respectful of the caller's time. You never provide medical
  advice or diagnose symptoms. For urgent medical issues, always recommend
  calling 911 or going to the emergency room.

hours:
  monday: { open: "07:00", close: "19:00" }
  tuesday: { open: "07:00", close: "19:00" }
  wednesday: { open: "07:00", close: "19:00" }
  thursday: { open: "07:00", close: "19:00" }
  friday: { open: "07:00", close: "19:00" }
  saturday: { open: "08:00", close: "14:00" }
  sunday: "closed"

after_hours_message: |
  City Health Clinic is currently closed. We're open Monday through
  Friday 7 AM to 7 PM, and Saturday 8 AM to 2 PM. For medical
  emergencies, please call 911 or go to your nearest emergency room.

routing:
  - name: "Appointments"
    number: "+15553001001"
    description: "Schedule, change, or cancel appointments"
  - name: "Pharmacy"
    number: "+15553001002"
    description: "Prescription refills and pharmacy questions"
  - name: "Nurse Line"
    number: "+15553001003"
    description: "Speak with a registered nurse"

faqs:
  - question: "Do you accept walk-ins?"
    answer: "Yes, we accept walk-in patients, though appointments are preferred to minimize wait times."
  - question: "What should I bring to my first visit?"
    answer: "Please bring your insurance card, a photo ID, and a list of any medications you are currently taking."

messages:
  channels:
    - type: "file"
      file_path: "messages/city-clinic/"
```

### Dispatch Rules for This Setup

```bash
# Acme Dental (East Coast, trunk from Twilio)
lk sip dispatch-rule create \
  --trunk-id "ST_twilio_acme" \
  --type "individual" \
  --room-prefix "call-acme-" \
  --metadata '{"config": "acme-dental"}'

# Smith Law (Central, trunk from Telnyx)
lk sip dispatch-rule create \
  --trunk-id "ST_telnyx_smith" \
  --type "individual" \
  --room-prefix "call-smith-" \
  --metadata '{"config": "smith-law"}'

# City Clinic (West Coast, trunk from Twilio)
lk sip dispatch-rule create \
  --trunk-id "ST_twilio_clinic" \
  --type "individual" \
  --room-prefix "call-clinic-" \
  --metadata '{"config": "city-clinic"}'
```

### Directory Setup

```bash
mkdir -p messages/acme-dental
mkdir -p messages/smith-law
mkdir -p messages/city-clinic
```

### Start the Agent

```bash
python -m receptionist.agent start
```

One process now handles all three businesses.

---

## Monitoring Multiple Businesses

### Log Differentiation

Agent logs include the room name, which contains the business-specific prefix:

```
[call-acme-abc123] Session started, config: acme-dental
[call-smith-def456] Session started, config: smith-law
[call-acme-abc123] Tool call: lookup_faq("insurance")
[call-clinic-ghi789] Session started, config: city-clinic
```

Use the room prefix to filter logs per business.

### Message Monitoring

If using separate message directories, monitor each independently:

```bash
# Count messages per business
ls messages/acme-dental/*.json 2>/dev/null | wc -l
ls messages/smith-law/*.json 2>/dev/null | wc -l
ls messages/city-clinic/*.json 2>/dev/null | wc -l
```

### Per-Business Call Volume

LiveKit Cloud provides analytics dashboards where you can filter by room prefix to see per-business call volumes.

---

## Scaling Considerations

### Single Agent, Multiple Businesses

A single agent process can handle multiple concurrent calls across different businesses. Each call is independent — it loads its own configuration and maintains its own state.

### Resource Impact

Multiple businesses do not significantly increase resource usage per call. The main consideration is total concurrent call volume across all businesses, not the number of businesses.

### When to Split

Consider running separate agent instances when:

- **Different SLAs**: One business requires 99.99% uptime while others have lower requirements.
- **Geographic separation**: Businesses in different regions benefit from agents deployed locally.
- **Resource isolation**: One high-volume business should not impact others.
- **Maintenance windows**: You need to update one business's config without affecting others (though YAML changes do not require restarts in most cases).

To split, run separate agent processes with different environment configurations. Each process only handles calls routed to it.

---

## Troubleshooting Multi-Business Issues

### Calls going to the wrong business

**Symptom**: A call to Business A gets the greeting and config of Business B.

**Cause**: Dispatch rule metadata is pointing to the wrong config slug, or the fallback is activating.

**Solution**:
1. Verify each dispatch rule has the correct `metadata` with the right `"config"` value.
2. Check that the YAML filename matches the slug exactly.
3. Verify the trunk ID in each dispatch rule matches the intended SIP trunk.

### Fallback config used unexpectedly

**Symptom**: All calls use the same (first alphabetical) configuration regardless of which number was called.

**Cause**: Job metadata is not being passed through, or the `"config"` key is missing from the metadata.

**Solution**:
1. Verify dispatch rules are configured with metadata in LiveKit.
2. Check that the metadata JSON is valid: `{"config": "slug-name"}`.
3. Ensure the dispatch rule is active and matched for the incoming trunk/number.
4. Check LiveKit logs for dispatch rule matching.

### New business config not picked up

**Symptom**: You added a new YAML file and dispatch rule, but calls are not handled correctly.

**Cause**: The agent may have started before the file was created, or the dispatch rule is not yet active.

**Solution**:
1. The agent reads config files at call time (not at startup), so new files are picked up automatically.
2. Verify the dispatch rule is active in LiveKit.
3. Test by making a call to the new number.
4. Check that the filename and slug match exactly.

### Messages from different businesses mixing together

**Symptom**: Messages from Business A appear in Business B's directory.

**Cause**: Both businesses are configured with the same `file_path`.

**Solution**: Use unique `file_path` values for each business:

```yaml
# Business A
messages:
  channels:
    - type: "file"
      file_path: "messages/business-a/"

# Business B
messages:
  channels:
    - type: "file"
      file_path: "messages/business-b/"
```
