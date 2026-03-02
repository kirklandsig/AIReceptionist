# Deployment Guide

This guide covers everything needed to deploy AI Receptionist in production: LiveKit setup (Cloud and self-hosted), SIP trunk configuration with Twilio and Telnyx, environment configuration, and production operation considerations.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Option A: LiveKit Cloud Deployment](#option-a-livekit-cloud-deployment)
- [Option B: Self-Hosted LiveKit Deployment](#option-b-self-hosted-livekit-deployment)
- [SIP Trunk Setup](#sip-trunk-setup)
  - [Telnyx SIP Trunk (Recommended)](#telnyx-sip-trunk)
  - [Twilio SIP Trunk](#twilio-sip-trunk)
- [Connecting SIP Trunk to LiveKit](#connecting-sip-trunk-to-livekit)
- [Running the Agent](#running-the-agent)
  - [Development Mode](#development-mode)
  - [Production Mode](#production-mode)
- [Process Management](#process-management)
- [Health Monitoring](#health-monitoring)
- [Scaling Considerations](#scaling-considerations)
- [Cost Management](#cost-management)
- [Security Checklist](#security-checklist)

---

## Prerequisites

Before deploying, ensure you have:

- **Python 3.11+** installed
- **OpenAI API key** with Realtime API access
- **LiveKit account** (Cloud) or server infrastructure (self-hosted)
- **SIP trunk provider account** (Twilio or Telnyx)
- **Phone number** provisioned through your SIP trunk provider
- **Business configuration YAML** prepared (see [Configuration Reference](configuration-reference.md))

---

## Environment Variables

Create a `.env` file in the project root (use `.env.example` as a template):

```bash
cp .env.example .env
```

Required variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `LIVEKIT_URL` | WebSocket URL for your LiveKit server | `wss://your-project.livekit.cloud` |
| `LIVEKIT_API_KEY` | LiveKit API key for authentication | `APIxxxxxxxxxxxxxxx` |
| `LIVEKIT_API_SECRET` | LiveKit API secret for authentication | `your-api-secret` |
| `OPENAI_API_KEY` | OpenAI API key with Realtime API access | `sk-proj-xxxxxxxxxxxxx` |

**Security**: Never commit `.env` to version control. The `.env.example` file contains placeholder values and is safe to commit.

---

## Option A: LiveKit Cloud Deployment

LiveKit Cloud is the easiest path to production. It handles server infrastructure, scaling, and SIP gateway management.

### Step 1: Create a LiveKit Cloud Account

1. Go to [https://cloud.livekit.io](https://cloud.livekit.io) and create an account.
2. Create a new project.
3. Note your project URL (e.g., `wss://your-project.livekit.cloud`).

### Step 2: Generate API Keys

1. In the LiveKit Cloud dashboard, navigate to **Settings > API Keys**.
2. Create a new API key pair.
3. Copy the **API Key** and **API Secret** into your `.env` file.

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxxxx
LIVEKIT_API_SECRET=your-secret-here
```

### Step 3: Configure SIP in LiveKit Cloud

1. In the LiveKit Cloud dashboard, navigate to **SIP**.
2. Create a new SIP Trunk (see [SIP Trunk Setup](#sip-trunk-setup) below for provider-specific instructions).
3. Create a SIP Dispatch Rule that routes incoming calls to your agent.

### Step 4: Deploy the Agent

The agent connects to LiveKit Cloud as a worker. It can run anywhere with outbound internet access — your local machine, a VPS, a container, etc.

```bash
# Install dependencies
pip install -e .

# Run the agent (production)
python -m receptionist.agent start
```

The agent will connect to LiveKit Cloud and begin accepting calls.

---

## Option B: Self-Hosted LiveKit Deployment

Self-hosting gives you full control over the infrastructure. This is suitable for organizations with specific compliance requirements or those who want to minimize third-party dependencies.

### Step 1: Deploy LiveKit Server

Follow the [official LiveKit Server deployment guide](https://docs.livekit.io/home/self-hosting/deployment/). Recommended options:

**Docker Compose (simplest)**:
```yaml
version: "3.9"
services:
  livekit:
    image: livekit/livekit-server:latest
    ports:
      - "7880:7880"   # HTTP
      - "7881:7881"   # WebRTC TCP
      - "50000-50200:50000-50200/udp"  # WebRTC UDP
    environment:
      - LIVEKIT_KEYS=your-api-key: your-api-secret
    volumes:
      - ./livekit.yaml:/etc/livekit.yaml
    command: ["--config", "/etc/livekit.yaml"]
```

**Minimum `livekit.yaml` config**:
```yaml
port: 7880
rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 50200
  use_external_ip: true
keys:
  your-api-key: your-api-secret
sip:
  # SIP configuration goes here
```

### Step 2: Configure SIP Gateway

For self-hosted deployments, you need to configure the LiveKit SIP gateway. This is built into LiveKit Server and handles SIP-to-WebRTC bridging.

Add SIP configuration to your `livekit.yaml`:

```yaml
sip:
  # Your SIP trunk provider's signaling address
  trunks:
    - name: "primary"
      address: "sip.twilio.com"
      username: "your-sip-username"
      password: "your-sip-password"
```

### Step 3: Configure DNS and TLS

For production self-hosted deployments:

1. Point a domain name to your server (e.g., `livekit.yourdomain.com`).
2. Configure TLS with Let's Encrypt or your preferred certificate authority.
3. Set the `LIVEKIT_URL` to `wss://livekit.yourdomain.com`.

### Step 4: Run the Agent

```bash
LIVEKIT_URL=wss://livekit.yourdomain.com \
LIVEKIT_API_KEY=your-api-key \
LIVEKIT_API_SECRET=your-api-secret \
OPENAI_API_KEY=sk-your-openai-key \
python -m receptionist.agent start
```

---

## SIP Trunk Setup

A SIP trunk connects the PSTN (regular phone network) to your LiveKit server. You need a SIP trunk provider to receive phone calls.

**We recommend Telnyx** over Twilio for this project. Telnyx operates its own private IP backbone (vs Twilio routing over the public internet), charges ~$0.007/min vs Twilio's ~$0.013/min, and is a licensed carrier in 30+ countries. For a project focused on voice fidelity, fewer network hops and a private backbone mean cleaner audio reaching your agent. Both are fully supported by LiveKit.

### Telnyx SIP Trunk (Recommended)

See the [Telnyx section below](#telnyx-sip-trunk-1) or follow [Telnyx's LiveKit configuration guide](https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide) for the most up-to-date steps.

### Twilio SIP Trunk

#### Step 1: Get a Twilio Account

1. Sign up at [https://www.twilio.com](https://www.twilio.com).
2. Complete account verification.

#### Step 2: Purchase a Phone Number

1. In the Twilio Console, go to **Phone Numbers > Manage > Buy a Number**.
2. Select a number with **Voice** capability.
3. Note the phone number (e.g., `+15551234567`).

#### Step 3: Create a SIP Trunk

1. In the Twilio Console, go to **Elastic SIP Trunking > Trunks**.
2. Click **Create new SIP Trunk**.
3. Give it a name (e.g., "AI Receptionist").

#### Step 4: Configure Origination (Twilio to LiveKit)

1. In your trunk settings, go to **Origination**.
2. Add an Origination URI pointing to your LiveKit SIP endpoint:
   - **LiveKit Cloud**: Use the SIP URI provided in your LiveKit Cloud dashboard.
   - **Self-hosted**: `sip:your-livekit-server-ip:5060`
3. Set priority and weight (defaults are fine for single-trunk setups).

#### Step 5: Configure Termination (LiveKit to PSTN)

If you need outbound calling or transfers:

1. Go to **Termination** in your trunk settings.
2. Configure a termination SIP URI.
3. Set up credentials (username/password) for authentication.
4. Add your LiveKit server IP to the Access Control List.

#### Step 6: Associate Phone Number

1. Go to **Phone Numbers** in your trunk settings.
2. Associate your purchased phone number with this trunk.

#### Twilio Pricing Reference

| Item | Cost |
|------|------|
| Phone number (US local) | ~$1.00/month |
| Inbound calls | ~$0.0085/min |
| Outbound calls (transfers) | ~$0.014/min |
| SIP trunk | No additional charge |

### Telnyx SIP Trunk

#### Step 1: Get a Telnyx Account

1. Sign up at [https://telnyx.com](https://telnyx.com).
2. Complete account verification.

#### Step 2: Purchase a Phone Number

1. In the Telnyx Portal, go to **Numbers > Search & Buy**.
2. Select a number with voice capability.
3. Note the phone number.

#### Step 3: Create a SIP Connection

1. Go to **SIP Connections** in the Telnyx Portal.
2. Click **Create SIP Connection**.
3. Choose **Credentials Authentication** or **IP Authentication**.

**For Credentials Authentication**:
- Note the generated username and password.
- Set the outbound profile for your connection.

**For IP Authentication**:
- Add your LiveKit server's IP address.
- This is simpler but requires a static IP.

#### Step 4: Configure Inbound Settings

1. In your SIP Connection settings, set the **Inbound** configuration.
2. Set the SIP URI to point to your LiveKit SIP endpoint:
   - **LiveKit Cloud**: Use the SIP URI from your LiveKit Cloud dashboard.
   - **Self-hosted**: Your LiveKit server's SIP address.

#### Step 5: Assign Phone Number

1. Go to your phone number settings.
2. Set the **Connection** to your SIP Connection.

#### Telnyx Pricing Reference

| Item | Cost |
|------|------|
| Phone number (US local) | ~$1.00/month |
| Inbound calls | ~$0.007/min |
| Outbound calls (transfers) | ~$0.012/min |
| SIP connection | No additional charge |

---

## Connecting SIP Trunk to LiveKit

Once your SIP trunk provider is configured, you need to create the corresponding resources in LiveKit.

### LiveKit SIP Trunk Resource

Use the LiveKit CLI or API to create a SIP Trunk:

```bash
# Install LiveKit CLI
# See: https://docs.livekit.io/home/cli/

# Create SIP Trunk (example for Twilio)
lk sip trunk create \
  --name "twilio-primary" \
  --inbound-addresses "54.172.60.0/30"  # Twilio's IP range
```

For authentication-based trunks:
```bash
lk sip trunk create \
  --name "telnyx-primary" \
  --inbound-username "your-username" \
  --inbound-password "your-password"
```

### LiveKit SIP Dispatch Rule

A dispatch rule tells LiveKit what to do when a SIP call arrives:

```bash
lk sip dispatch-rule create \
  --trunk-id "ST_xxxxxxxx" \
  --type "individual" \
  --room-prefix "call-" \
  --metadata '{"config": "my-business"}'
```

Key parameters:

| Parameter | Description |
|-----------|-------------|
| `--trunk-id` | The SIP trunk to match against |
| `--type` | `"individual"` creates a new room per call |
| `--room-prefix` | Prefix for auto-generated room names |
| `--metadata` | JSON metadata passed to the agent (used for config selection) |

The `metadata` field is how you specify which business config the agent should use. The `"config"` key in the metadata maps to a YAML file in `config/businesses/`. See [Multi-Business Setup](multi-business-setup.md) for details.

---

## Running the Agent

### Development Mode

Development mode provides hot-reloading and verbose logging:

```bash
python -m receptionist.agent dev
```

This is suitable for local testing and development. The agent connects to LiveKit and processes calls, but with development-friendly defaults.

### Production Mode

Production mode is optimized for reliability:

```bash
python -m receptionist.agent start
```

For production, you should:

1. Use a process manager (see below).
2. Configure log output appropriately.
3. Set up health monitoring.
4. Ensure the process restarts on failure.

---

## Process Management

For production deployments, use a process manager to keep the agent running.

### systemd (Linux)

Create `/etc/systemd/system/ai-receptionist.service`:

```ini
[Unit]
Description=AI Receptionist Agent
After=network.target

[Service]
Type=simple
User=ai-receptionist
Group=ai-receptionist
WorkingDirectory=/opt/ai-receptionist
EnvironmentFile=/opt/ai-receptionist/.env
ExecStart=/opt/ai-receptionist/.venv/bin/python -m receptionist.agent start
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-receptionist
sudo systemctl start ai-receptionist
```

View logs:
```bash
sudo journalctl -u ai-receptionist -f
```

### Docker

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY receptionist/ receptionist/
COPY config/ config/

RUN pip install --no-cache-dir -e .

# Create messages directory
RUN mkdir -p messages

CMD ["python", "-m", "receptionist.agent", "start"]
```

Build and run:
```bash
docker build -t ai-receptionist .
docker run -d \
  --name ai-receptionist \
  --env-file .env \
  --restart unless-stopped \
  -v $(pwd)/messages:/app/messages \
  -v $(pwd)/config:/app/config \
  ai-receptionist
```

### Docker Compose

```yaml
version: "3.9"
services:
  agent:
    build: .
    env_file: .env
    restart: unless-stopped
    volumes:
      - ./messages:/app/messages
      - ./config/businesses:/app/config/businesses
```

### Supervisor (Alternative)

```ini
[program:ai-receptionist]
command=/opt/ai-receptionist/.venv/bin/python -m receptionist.agent start
directory=/opt/ai-receptionist
user=ai-receptionist
autostart=true
autorestart=true
stderr_logfile=/var/log/ai-receptionist/error.log
stdout_logfile=/var/log/ai-receptionist/output.log
environment=LIVEKIT_URL="wss://...",LIVEKIT_API_KEY="...",LIVEKIT_API_SECRET="...",OPENAI_API_KEY="..."
```

---

## Health Monitoring

### Log Monitoring

Monitor agent logs for these key indicators:

| Log Pattern | Meaning |
|-------------|---------|
| `Connected to LiveKit` | Agent successfully connected |
| `Session started` | A new call is being handled |
| `Session ended` | A call has completed |
| `Config loaded: <name>` | Business config loaded successfully |
| `ERROR` / `Exception` | Something went wrong |

### Heartbeat Monitoring

The LiveKit Agents SDK maintains a heartbeat with the LiveKit server. If the agent process crashes or becomes unresponsive, LiveKit will detect the loss and can dispatch calls to another agent worker (if available).

### Recommended Monitoring Stack

For production deployments, consider:

1. **Log aggregation**: Ship logs to a centralized service (e.g., Datadog, Grafana Loki, CloudWatch).
2. **Process monitoring**: Use your process manager's built-in monitoring (systemd status, Docker health checks).
3. **Uptime monitoring**: External ping service to verify the agent is connected to LiveKit.
4. **Cost monitoring**: Track OpenAI API usage to catch unexpected spikes.

---

## Scaling Considerations

### Single Agent Instance

A single agent process can handle multiple concurrent calls. The LiveKit Agents SDK manages concurrent sessions within a single worker.

### Multiple Agent Workers

For higher availability or to handle more concurrent calls, run multiple agent instances:

```bash
# Instance 1
python -m receptionist.agent start

# Instance 2 (on another machine or in another container)
python -m receptionist.agent start
```

LiveKit distributes incoming calls across connected workers automatically.

### Geographic Distribution

For lower latency, deploy agent workers close to your callers:

- US East: Handles East Coast calls with lower latency.
- US West: Handles West Coast calls.
- Each worker connects to the same LiveKit Cloud project.

### Resource Requirements

| Metric | Estimate per Concurrent Call |
|--------|------------------------------|
| CPU | ~0.1-0.3 cores |
| Memory | ~50-100 MB |
| Network | ~100 kbps bidirectional |
| Disk | Minimal (message files are small) |

A modest VPS (2 CPU, 4GB RAM) can comfortably handle 5-10 concurrent calls.

---

## Cost Management

### OpenAI Realtime API

This is the largest cost component at ~$0.20-0.30 per minute. To manage costs:

- **Keep calls concise**: A well-configured receptionist resolves calls quickly.
- **Monitor usage**: Track per-call and daily costs through the OpenAI dashboard.
- **Set spending limits**: Configure spending alerts in your OpenAI account.

### SIP Trunk

SIP costs are minimal (~$0.01-0.02/min). Phone number rental is typically $1-2/month.

### LiveKit Cloud

LiveKit Cloud offers a free tier. For high-volume deployments, review LiveKit's pricing page for current rates.

### Monthly Cost Estimate

| Business Profile | Calls/Day | Avg Duration | Monthly Cost |
|-----------------|-----------|-------------|-------------|
| Low volume | 10 | 2 min | ~$150 |
| Medium volume (typical dental office) | 30 | 2 min | ~$450 |
| High volume | 100 | 2 min | ~$1,500 |

---

## Security Checklist

Before going live, verify:

- [ ] `.env` file is not committed to version control
- [ ] `.env` file permissions restrict access (e.g., `chmod 600 .env`)
- [ ] OpenAI API key has appropriate spending limits
- [ ] LiveKit API credentials are kept secure
- [ ] Config YAML files do not contain sensitive information beyond phone numbers
- [ ] Message storage directory has appropriate filesystem permissions
- [ ] If using webhook delivery, the webhook endpoint uses HTTPS
- [ ] Agent process runs as a non-root user
- [ ] Firewall rules restrict access to only necessary ports
- [ ] Log output does not contain sensitive caller information
- [ ] SIP trunk credentials are stored securely (not in code or configs)
