# Troubleshooting

This document covers common issues encountered when setting up, configuring, and running AI Receptionist, along with their solutions.

---

## Table of Contents

- [Configuration Errors](#configuration-errors)
- [Connection Issues](#connection-issues)
- [SIP and Call Issues](#sip-and-call-issues)
- [Audio Quality Issues](#audio-quality-issues)
- [Agent Behavior Issues](#agent-behavior-issues)
- [Message Delivery Issues](#message-delivery-issues)
- [Performance Issues](#performance-issues)
- [Development and Testing Issues](#development-and-testing-issues)
- [Getting Help](#getting-help)

---

## Configuration Errors

### "field required" or "value is not a valid string"

**Symptom**: Agent fails to start with a Pydantic validation error.

**Cause**: A required field is missing from your YAML configuration file, or a field has the wrong type.

**Solution**:
1. Compare your config against the [Configuration Reference](configuration-reference.md).
2. Verify all required fields are present: `business`, `voice`, `greeting`, `personality`, `hours`, `after_hours_message`, `routing`, `faqs`, `messages`.
3. Check YAML formatting — indentation matters. Use spaces, not tabs.

```yaml
# Wrong (tab indentation)
business:
	name: "My Business"    # TAB character - will cause errors

# Correct (space indentation)
business:
  name: "My Business"      # Two spaces
```

### `expected <block end>, but found '<block mapping start>'`

**Symptom**: Agent crashes at config load with a `ConfigError` mentioning
"indentation error" or, on older versions, the cryptic raw `yaml.parser.
ParserError: expected <block end>, but found '<block mapping start>'`.

**Cause**: A top-level section (e.g. `sip:`, `recording:`, `calendar:`)
has a leading space, so YAML reads it as nested under the previous block.
Most commonly this happens when uncommenting a `# section:` example block
by removing only the `#` and leaving the trailing space.

```yaml
# Wrong — one leading space, parser sees this as nested under `messages:`
 sip:
  transfer_uri_template: "sip:{number}"

# Correct — column 0
sip:
  transfer_uri_template: "sip:{number}"
```

**Solution**: When uncommenting an example block, remove BOTH the leading
`#` AND the space that follows it.

### "Invalid time format" on hours fields

**Symptom**: Validation error mentioning `open` or `close` time fields.

**Cause**: Time values are not in `HH:MM` 24-hour format.

**Solution**: Use the correct format with leading zeros:

```yaml
# Wrong
hours:
  monday:
    open: "8:00"     # Missing leading zero
    close: "5:00 PM" # 12-hour format with AM/PM

# Correct
hours:
  monday:
    open: "08:00"    # Leading zero
    close: "17:00"   # 24-hour format
```

### Cross-field validation error on messages config

**Symptom**: Error about `file_path` or `webhook_url` being required.

**Cause**: The `delivery` method does not match the provided fields.

**Solution**: Ensure the delivery method matches the provided path/URL:

```yaml
# File delivery requires file_path
messages:
  delivery: "file"
  file_path: "messages/"

# Webhook delivery requires webhook_url
messages:
  delivery: "webhook"
  webhook_url: "https://your-app.com/api/messages"
```

### "closed" day not recognized

**Symptom**: Validation error on a day that should be marked as closed.

**Cause**: The string "closed" must be lowercase and a plain string, not an object.

**Solution**:

```yaml
# Wrong
hours:
  saturday:
    open: "closed"    # "closed" inside an object

# Wrong
hours:
  saturday: "Closed"  # Capital C

# Correct
hours:
  saturday: "closed"  # Plain lowercase string
```

### Config file not found

**Symptom**: Agent starts but uses the wrong config or reports no config found.

**Cause**: The config slug in job metadata does not match a file in `config/businesses/`, or the fallback mechanism picked a different file.

**Solution**:
1. Verify the file exists: `ls config/businesses/`
2. Check the filename matches the slug (without `.yaml` extension).
3. If using job metadata, verify the slug matches: `"config": "my-business"` maps to `config/businesses/my-business.yaml`.
4. Slugs must match `^[a-zA-Z0-9_-]+$` — no spaces or special characters.

---

## Connection Issues

### "Could not connect to LiveKit server"

**Symptom**: Agent fails to start or exits immediately with a connection error.

**Cause**: The LiveKit URL is incorrect, the server is unreachable, or credentials are wrong.

**Solution**:
1. Verify `LIVEKIT_URL` in your `.env` file starts with `wss://`.
2. Check that the URL is correct (no trailing slash, correct hostname).
3. Verify `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` are correct.
4. Test connectivity: `curl -I https://your-project.livekit.cloud` (replace `wss://` with `https://` for the HTTP check).
5. Check firewall rules — the agent needs outbound WebSocket access on port 443.

```
# Common mistakes
LIVEKIT_URL=https://...     # Wrong: should be wss://
LIVEKIT_URL=wss://...cloud/ # Wrong: trailing slash
LIVEKIT_URL=wss://...cloud  # Correct
```

### "Authentication failed" or "Invalid API key"

**Symptom**: Connection established but immediately rejected.

**Cause**: API key or secret is incorrect.

**Solution**:
1. Regenerate your API key pair in the LiveKit dashboard.
2. Copy the new values into `.env` exactly — no extra whitespace.
3. Restart the agent.
4. Verify `.env` is being loaded (check for `python-dotenv` in dependencies).

### OpenAI Realtime auth errors

**Symptom**: Agent connects to LiveKit but fails when a call arrives, with OpenAI authentication errors in logs. Examples include `401`, `Invalid bearer token`, `insufficient_scope`, or a missing env-var error from `voice.auth`.

**Cause**: The configured Realtime auth source is missing, expired, or does not have access to the selected Realtime model.

**Solution**:
1. If `voice.auth` is omitted, verify `OPENAI_API_KEY` in `.env` starts with `sk-`.
2. If using `voice.auth.type: "api_key"`, verify the configured `env` var exists in the agent process.
3. If using `voice.auth.type: "oauth_codex"`, verify the configured file exists and contains `tokens.access_token` and `tokens.refresh_token`. Run `python -m receptionist.voice setup <business>` to create or repair a per-business token file.
4. If using `voice.auth.type: "oauth_static"`, verify exactly one of `token` or `token_env` is configured and that the token is current.
5. Confirm the account behind the bearer has Realtime model access and billing/plan access for `voice.model`.
6. Test a bearer manually: `curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"`

### `oauth_codex` refresh failed

**Symptom**: Calls worked earlier, then startup or call handling fails with a
`voice.auth oauth_codex refresh failed` error.

**Cause**: The short-lived Codex `access_token` expired and the stored
`refresh_token` was missing, revoked, expired, or already rotated by another
copy of the file.

**Solution**:
1. Run `python -m receptionist.voice setup <business>` and sign in again with the business's ChatGPT account.
2. Confirm the YAML points at the intended per-business file, usually `secrets/<business>/openai_auth.json`.
3. If multiple workers share a business, ensure they all mount the same token file path so refresh rotation is visible to every worker.
4. If refresh continues to fail, run `codex login status` to confirm the base Codex login is still valid.

### Codex CLI not found during voice setup

**Symptom**: `python -m receptionist.voice setup <business>` exits with
`Codex CLI not found on PATH`.

**Solution**:
1. Install Codex CLI: `npm install -g @openai/codex`.
2. Confirm `codex --version` works in the same shell you use for setup.
3. Re-run `python -m receptionist.voice setup <business>`.

---

## SIP and Call Issues

### Calls not reaching the agent

**Symptom**: Phone rings, but the AI receptionist never picks up. Calls go to voicemail or fail.

**Cause**: SIP trunk misconfiguration — calls are not being routed from the SIP provider to LiveKit.

**Solution**:
1. Verify your SIP trunk is configured in LiveKit (Cloud dashboard or server config).
2. Check the SIP dispatch rule routes calls to your agent.
3. Verify your SIP provider (Twilio/Telnyx) is sending calls to the correct LiveKit SIP endpoint.
4. Check SIP trunk provider logs for failed connection attempts.
5. Ensure the agent is running and connected to LiveKit when the call arrives.

### Agent answers but caller hears silence

**Symptom**: Call connects, but no greeting is played and the caller hears nothing.

**Cause**: Audio pipeline issue — typically the OpenAI Realtime session did not start correctly, or there is a media routing problem.

**Solution**:
1. Check agent logs for errors during session creation.
2. Verify the OpenAI API key has Realtime API access.
3. Check that the voice ID in your config is valid (see [available voices](configuration-reference.md#voice)).
4. Try a different voice to rule out voice-specific issues.
5. Restart the agent and try again.

### Call transfers fail

**Symptom**: Agent says "Let me transfer you..." but the transfer does not happen, or the caller gets disconnected.

**Cause**: SIP transfer is not configured correctly, or the target number is unreachable.

**Solution**:
1. Verify routing numbers in your config are in E.164 format (`+1XXXXXXXXXX`).
2. Check that outbound calling is configured on your SIP trunk (Twilio Termination or Telnyx outbound profile).
3. Verify the target phone numbers are valid and reachable.
4. Check LiveKit logs for SIP REFER/transfer errors.
5. Some SIP trunk configurations require explicit outbound/termination setup separate from inbound/origination.

### Agent never hangs up, even after caller leaves the line silent

**Symptom**: After the caller stops talking — or walks away from the
phone — the agent stays on the line indefinitely, racking up SIP and
Realtime usage.

**Cause**: `voice.idle.silence_hangup_enabled` is `false`, or the
`away_seconds + silence_grace_seconds` total is too long for the
business's tolerance.

**Solution**:
1. Confirm `voice.idle.silence_hangup_enabled: true` in the business YAML
   (default is true; explicit `false` disables the path).
2. Tune `voice.idle.away_seconds` (default 15s) and
   `voice.idle.silence_grace_seconds` (default 30s); the total is the
   maximum silence before the agent says goodbye.
3. The hangup is recorded as `outcomes: ["agent_ended"]` with
   `agent_end_reason: "silence_timeout"`. Check the call summary email
   to confirm the new path fired.

### Agent hangs up with `agent_end_reason: unproductive_turns_exhausted`

**Symptom**: A call ends with the agent-ended outcome and reason
`unproductive_turns_exhausted` even though the caller was making good
faith requests.

**Cause**: `voice.idle.unproductive_phrases` matched the agent's reply
text on N consecutive turns where no function tool fired. Common false
positive: chit-chat or empathetic interjections containing one of the
default substrings (e.g. "I'm here to help" used as a greeting).

**Solution**:
1. Inspect the markdown transcript to see which agent replies were scored
   unproductive (the `agent.unproductive` INFO logs record `count` and
   `threshold`).
2. Trim the `voice.idle.unproductive_phrases` list to drop the noisy
   substring, or raise `voice.idle.unproductive_turn_threshold` (default 5).
3. To disable entirely, set `voice.idle.unproductive_hangup_enabled: false`.

### Agent hangs up with `agent_end_reason: max_duration_reached`

**Symptom**: Calls cut off at exactly the same elapsed time, regardless of
the caller's intent.

**Cause**: `voice.idle.max_call_duration_seconds` is set; the cap was
hit. This setting defaults to `null` (no cap).

**Solution**: Adjust or remove `voice.idle.max_call_duration_seconds`
to match the longest call your business reasonably needs.

### Caller shows as `Unknown` in call-end email or transcript

**Symptom**: A real phone call has CallerID, but call-end emails or
transcript headers show `Caller: Unknown`.

**Cause**: Current versions capture CallerID three ways:
1. At `handle_call` snapshot (room scan when the agent picks up).
2. On every `participant_connected` event.
3. On every `participant_attributes_changed` event for any `sip.*`
   attribute, in case the trunk publishes CallerID after the participant
   has already joined the room.

Resolution checks (in order, kind-agnostic since 2026-05):
- attribute `sip.phoneNumber`
- attribute `sip.fromUser` (Telnyx setups)
- attribute `sip.from` (URI or full SIP FROM header)
- participant identity matching `sip_<digits>` (Asterisk BYOC pattern)

If `Unknown` still appears, the SIP trunk is not exposing CallerID through
any of those fields.

**Solution**:
1. Pull the latest `main` branch. Earlier versions short-circuited on
   `participant.kind != PARTICIPANT_KIND_SIP`, which made the
   identity-regex fallback unreachable on BYOC/Asterisk trunks that emit
   the SIP participant with a different kind value.
2. Check the always-on INFO logs with `component=agent.callerid` in your
   agent log stream. Each capture attempt records `participant_identity`,
   `participant_kind`, and the attribute keys the trunk actually published.
   The handle-call snapshot also records every remote participant present
   at pickup time.
3. If using BYOC/Asterisk, verify your trunk is forwarding caller ID into
   LiveKit. Some SIP setups need explicit caller-ID mapping or header
   forwarding. The `agent.callerid` logs will show whether the trunk is
   publishing any `sip.*` attributes at all.
4. If you've redeployed the fix and still see `Unknown`, ensure your
   server has cleared any `__pycache__/` directories and that the running
   process is the one with the new code (check the start-up timestamp
   against the deploy time).

### One-way audio (caller hears agent but agent does not hear caller, or vice versa)

**Symptom**: Audio flows in only one direction.

**Cause**: NAT traversal issue, firewall blocking UDP, or SIP codec mismatch.

**Solution**:
1. If self-hosting LiveKit, ensure `use_external_ip: true` is set in your LiveKit server config.
2. Open the required UDP port range (e.g., 50000-50200) on your firewall.
3. Check that both the LiveKit server and SIP trunk support common codecs (G.711 / OPUS).
4. For LiveKit Cloud: this is typically handled automatically; contact LiveKit support if it persists.

---

## Audio Quality Issues

### Robotic or distorted audio

**Symptom**: The AI's voice sounds robotic, glitchy, or unnaturally distorted.

**Cause**: Network latency, packet loss, or insufficient bandwidth between the agent and LiveKit/OpenAI.

**Solution**:
1. Check network quality between the agent and LiveKit server. High latency (>100ms) or packet loss will degrade audio.
2. Deploy the agent closer to the LiveKit server geographically.
3. Ensure the machine running the agent is not CPU-constrained (check CPU usage).
4. Verify there is sufficient bandwidth (~100 kbps bidirectional per call).

### Echo or feedback

**Symptom**: Caller hears their own voice echoed back.

**Cause**: Acoustic echo from the audio pipeline, or noise cancellation not working.

**Solution**:
1. Verify noise cancellation is active in the agent logs.
2. Check that `BVCTelephony` is being used for SIP calls (not the WebRTC-optimized `BVC`).
3. The noise cancellation plugin must be properly installed (`livekit-plugins-noise-cancellation`).

### Background noise interfering with recognition

**Symptom**: Agent frequently misunderstands the caller or gets confused by background noise.

**Cause**: Noise cancellation not effective enough, or caller in a very noisy environment.

**Solution**:
1. Ensure noise cancellation is enabled and using the correct mode (`BVCTelephony` for SIP).
2. The noise cancellation plugin should be installed and imported correctly.
3. For extremely noisy environments, this is a limitation of current noise cancellation technology. The caller may need to move to a quieter location.

---

## Agent Behavior Issues

### Agent does not follow personality instructions

**Symptom**: The receptionist does not use the tone, style, or behavior described in the personality config.

**Cause**: Personality instructions may be too vague, or conflicting with other parts of the prompt.

**Solution**:
1. Make personality instructions more specific and directive.
2. Inspect the generated system prompt to verify the personality is included:
   ```python
   from receptionist.config import load_config
   from receptionist.prompts import build_system_prompt
   config = load_config("config/businesses/your-config.yaml")
   print(build_system_prompt(config))
   ```
3. Ensure personality does not conflict with behavioral rules at the end of the prompt.
4. Try more explicit instructions: instead of "be friendly," say "greet the caller warmly, use their name when possible, and express genuine interest in helping them."

### Agent provides incorrect business hours

**Symptom**: Agent tells the caller the wrong hours.

**Cause**: Timezone misconfiguration, or hours are not updated in the YAML config.

**Solution**:
1. Verify the `timezone` field uses the correct IANA timezone (e.g., `America/New_York`, not `EST`).
2. Check the hours in your YAML config match the actual business hours.
3. Remember that times are in 24-hour format: `17:00` is 5 PM, not 5 AM.
4. Test the `get_business_hours` tool by calling during known open and closed times.

### Agent cannot answer questions that are in the FAQs

**Symptom**: Caller asks a question that is clearly in the FAQ list, but the agent does not find it.

**Cause**: The `lookup_faq` tool uses substring matching, and the caller's phrasing does not contain any substring of the FAQ question.

**Solution**:
1. Review FAQ questions — they should contain common keywords callers would use.
2. Remember the LLM also has FAQ content in its system prompt, so it may answer without calling the tool.
3. Consider adding multiple FAQ entries with different phrasings for important questions:
   ```yaml
   faqs:
     - question: "What insurance do you accept?"
       answer: "We accept Delta Dental, Cigna, and Aetna."
     - question: "Do you take my insurance?"
       answer: "We accept Delta Dental, Cigna, and Aetna."
   ```

### Agent is too verbose or too terse

**Symptom**: Responses are either too long (caller gets impatient) or too short (not enough information).

**Cause**: Personality instructions do not specify response length, or conflicting instructions.

**Solution**: Add explicit length guidance to the personality field:

```yaml
personality: |
  Keep your responses concise — aim for 1-2 sentences per response.
  Only elaborate when the caller asks for more detail. Be efficient
  with the caller's time while remaining warm and helpful.
```

---

## Message Delivery Issues

### Messages not being saved

**Symptom**: Agent confirms message was taken, but no file appears in the messages directory.

**Cause**: The messages directory does not exist, or the process does not have write permissions.

**Solution**:
1. Create the messages directory: `mkdir -p messages/`
2. Check file permissions: the process running the agent must have write access.
3. Check the `file_path` in your config matches the actual directory.
4. Look for errors in the agent logs related to file writing.

### "NotImplementedError" when using webhook delivery

**Symptom**: Agent crashes or errors when a message is taken with webhook delivery configured.

**Cause**: Webhook delivery is defined in the configuration schema but not yet implemented.

**Solution**: Use file-based delivery for now:

```yaml
messages:
  delivery: "file"
  file_path: "messages/"
```

Webhook delivery is planned for a future release.

### Message files have wrong timestamps

**Symptom**: Message file timestamps do not match the expected time.

**Cause**: Timestamps are always in UTC, which may differ from the business timezone.

**Solution**: This is by design. Message timestamps are stored in UTC for consistency. Convert to the business timezone when displaying:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

utc_time = datetime.fromisoformat(message_data["timestamp"])
local_time = utc_time.astimezone(ZoneInfo("America/New_York"))
```

---

## Performance Issues

### High latency in agent responses

**Symptom**: Noticeable delay (>2 seconds) between the caller finishing speaking and the agent responding.

**Cause**: Network latency to OpenAI, slow config loading, or CPU-bound operations on the event loop.

**Solution**:
1. Check network latency to OpenAI API endpoints.
2. Deploy the agent in a region close to both LiveKit and OpenAI (US East is typically optimal for both).
3. Ensure no synchronous/blocking operations are running on the event loop (all I/O should use `asyncio.to_thread()`).
4. Check system resources — CPU and memory should not be at capacity.

### Agent becomes unresponsive during high call volume

**Symptom**: Agent stops handling new calls, or existing calls become degraded.

**Cause**: Too many concurrent calls for the available resources.

**Solution**:
1. Check resource usage (CPU, memory, network).
2. Scale horizontally by running additional agent instances (they automatically load-balance through LiveKit).
3. A single agent process can handle several concurrent calls, but the exact number depends on your hardware. Start with 5-10 concurrent calls as a baseline.

### Memory usage grows over time

**Symptom**: Agent process memory increases steadily, eventually leading to OOM or slowdowns.

**Cause**: Potential memory leak, or normal accumulation of session data that is not being released.

**Solution**:
1. Restart the agent process periodically (configure your process manager for periodic restarts).
2. Monitor memory usage over time and report specific patterns in a GitHub issue.
3. Check Python version — newer versions may have improved garbage collection.

---

## Development and Testing Issues

### Tests fail with import errors

**Symptom**: `python -m pytest tests/ -v` fails with `ModuleNotFoundError`.

**Cause**: The package is not installed in the virtual environment.

**Solution**:
```bash
# Ensure virtual environment is activated
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install in editable mode
pip install -e .

# Run tests
python -m pytest tests/ -v
```

### Tests pass but agent fails to start

**Symptom**: All 15 tests pass, but `python -m receptionist.agent dev` fails.

**Cause**: Tests do not require LiveKit/OpenAI credentials, but the agent does.

**Solution**:
1. Verify `.env` file exists and contains all required variables.
2. Check that `python-dotenv` is installed and loading the file.
3. Try exporting the variables directly to isolate the issue:
   ```bash
   export LIVEKIT_URL=wss://...
   export LIVEKIT_API_KEY=...
   export LIVEKIT_API_SECRET=...
   export OPENAI_API_KEY=sk-...
   python -m receptionist.agent dev
   ```

### Python version incompatibility

**Symptom**: Syntax errors or missing standard library modules.

**Cause**: Running on Python <3.11.

**Solution**:
1. Check your Python version: `python --version`
2. Ensure Python 3.11 or later is installed.
3. If you have multiple Python versions, specify explicitly: `python3.11 -m venv .venv`
4. The `zoneinfo` module (used for timezone handling) is in the standard library from Python 3.9+, but other features may require 3.11+.

---

## Getting Help

If you cannot resolve your issue using this guide:

1. **Search existing issues**: Check the GitHub Issues page for similar problems.
2. **Enable verbose logging**: Run with maximum logging to capture detailed output for debugging.
3. **Open a new issue**: Include the following information:
   - Python version (`python --version`)
   - Operating system and version
   - Relevant log output (sanitize any API keys or sensitive data)
   - Steps to reproduce the issue
   - Configuration file (sanitize phone numbers and business details)
4. **Community discussions**: Use GitHub Discussions for questions, ideas, and general help.
