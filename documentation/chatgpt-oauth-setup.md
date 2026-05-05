# ChatGPT OAuth Setup

AIReceptionist can authenticate OpenAI Realtime with either a normal OpenAI
Platform API key or a ChatGPT login token from the Codex CLI. The ChatGPT OAuth
path is useful when you already have a ChatGPT Plus/Pro/Team/Enterprise account
with the needed Realtime model access and want calls to use that account's
subscription entitlements instead of a project API key.

This mode is configured per business through `voice.auth.type: "oauth_codex"`.

## When To Use This

Use ChatGPT OAuth when:

- You want to run the receptionist from a ChatGPT subscription account rather
  than an `sk-...` OpenAI Platform key.
- Different businesses should use different ChatGPT accounts.
- You are testing Realtime access from the same account you use in ChatGPT or
  Codex.

Use API-key auth instead when:

- You need standard OpenAI Platform billing, usage dashboards, service accounts,
  or organization/project controls.
- You are deploying in an environment where browser login is not practical.
- The ChatGPT account does not have access to the configured `voice.model`.

Model access and rate limits still come from OpenAI. If a ChatGPT account does
not have access to `gpt-realtime-1.5`, the agent will fail at call startup with
an auth/model-access error and you should use a different ChatGPT account or an
OpenAI API key.

## Requirements

- Codex CLI installed and available on `PATH`.
- A ChatGPT account with access to the Realtime model you configured.
- LiveKit credentials in `.env`: `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
  `LIVEKIT_API_SECRET`.
- A business YAML in `config/businesses/<business>.yaml`.

Install Codex CLI if needed:

```bash
npm install -g @openai/codex
codex --version
```

## One-Business Setup

Run the setup command for the business slug (the YAML filename without
`.yaml`):

```bash
python -m receptionist.voice setup example-dental
```

What the command does:

1. Validates `config/businesses/example-dental.yaml` exists.
2. Uses an existing usable target token if one is already configured.
3. Otherwise runs `codex login` so you can sign in with the intended ChatGPT
   account.
4. Copies the Codex auth file to `secrets/example-dental/openai_auth.json`.
5. Validates the token and refresh token.
6. Writes this block into the business YAML:

```yaml
voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"
  auth:
    type: "oauth_codex"
    path: "secrets/example-dental/openai_auth.json"
```

After this, `OPENAI_API_KEY` is not required for that business. `voice.auth` is
strict: if the configured OAuth file is missing or invalid, the agent fails
fast instead of silently falling back to a global API key.

## Multi-Business Setup

Run setup once per business and sign in with the ChatGPT account that should be
used for that business.

```bash
python -m receptionist.voice setup acme
python -m receptionist.voice setup trinicom
```

Each YAML should point at its own token file:

```yaml
# config/businesses/acme.yaml
voice:
  auth:
    type: "oauth_codex"
    path: "secrets/acme/openai_auth.json"

# config/businesses/trinicom.yaml
voice:
  auth:
    type: "oauth_codex"
    path: "secrets/trinicom/openai_auth.json"
```

Do not share one ChatGPT token file across unrelated businesses unless you
intentionally want all of them to use the same ChatGPT account.

## Non-Interactive Smoke Tests

For local smoke tests only, you can reuse an already-logged-in Codex auth file:

```bash
python -m receptionist.voice setup example-dental --reuse-existing-codex-auth
```

This skips the `codex login` prompt when `--codex-auth-source` is already
usable. Avoid this flag during customer/business onboarding because it can copy
the wrong currently logged-in ChatGPT account.

## Runtime Behavior

Codex access tokens are short-lived. At call startup, AIReceptionist checks the
token expiry:

- If the access token is still valid, it is passed to OpenAI Realtime.
- If the token is expired or close to expiring, the agent uses
  `tokens.refresh_token` to refresh it.
- Rotated tokens are written back to the same file atomically.
- Concurrent refreshes are serialized with an in-process lock plus a per-file
  `.refresh.lock` file so multiple calls/workers do not spend the same rotating
  refresh token.

Keep token files secret. They are equivalent to account credentials.

Recommended production layout:

```text
secrets/
  acme/
    openai_auth.json
  trinicom/
    openai_auth.json
```

Do not commit `secrets/` or token JSON files.

## Running The Agent

Once the business YAML contains `voice.auth.type: "oauth_codex"`, run the agent
normally:

```bash
python -m receptionist.agent dev
```

For a specific local business config:

```bash
RECEPTIONIST_CONFIG=example-dental python -m receptionist.agent dev
```

On Windows PowerShell:

```powershell
$env:RECEPTIONIST_CONFIG = "example-dental"
python -m receptionist.agent dev
```

## Troubleshooting

### `Codex CLI not found on PATH`

Install the CLI and restart the shell:

```bash
npm install -g @openai/codex
codex --version
```

### `voice.auth oauth_codex file not found`

Run setup again for that business:

```bash
python -m receptionist.voice setup <business>
```

### `voice.auth oauth_codex refresh failed`

The refresh token may be missing, expired, revoked, or from the wrong account.
Run setup again and sign in with the intended ChatGPT account.

### `Invalid bearer token`, `insufficient_scope`, or model-access errors

Confirm the signed-in ChatGPT account has access to the configured
`voice.model`. If it does not, use a different ChatGPT account or switch the
business to API-key auth:

```yaml
voice:
  auth:
    type: "api_key"
    env: "OPENAI_API_KEY"
```

### Calls still use `OPENAI_API_KEY`

Only businesses with a `voice.auth` block use the per-business OAuth token. If
`voice.auth` is omitted, the LiveKit OpenAI plugin keeps using `OPENAI_API_KEY`
from the process environment.
