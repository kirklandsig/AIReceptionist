# Google Calendar integration setup

This guide walks through configuring a business to use Google Calendar for
in-call appointment booking. There are two authentication paths:
**service account** (simpler, works for Google Workspace) and **OAuth 2.0**
(works for any account, including personal gmail.com, but requires a
browser-based consent step).

If your business uses Google Workspace (custom domain), go with **service
account**. If you're trying to integrate a personal gmail.com calendar, use
**OAuth**.

## Prerequisites

- A Google Cloud project (create one at https://console.cloud.google.com/)
- The Google Calendar API enabled on that project:
  - Go to https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
  - Click **Enable**
- The calendar you want to book on (you'll need its calendar ID — usually
  `primary` for the account's default calendar, or the full email-shaped ID
  for a shared calendar)

## Path A: Service account (Google Workspace)

### 1. Create a service account

1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts
2. Click **Create Service Account**
3. Give it a name like `aireceptionist-<business-slug>`
4. Grant no project-level roles (the service account's permissions come from
   calendar sharing, not IAM)
5. Finish. Back on the service account list, click the account you just
   created, go to the **Keys** tab, and click **Add Key → Create new key →
   JSON**. A JSON file downloads.

### 2. Save the key file

Move the downloaded JSON into the project:

```
mkdir -p secrets/<business-slug>
mv ~/Downloads/<project>-<hash>.json secrets/<business-slug>/google-calendar-sa.json
chmod 600 secrets/<business-slug>/google-calendar-sa.json
```

(Windows users: just place the file; chmod is ignored.)

### 3. Share the calendar with the service account

Take note of the service account's email address — it looks like
`aireceptionist-<biz>@<project>.iam.gserviceaccount.com`. Open the Google
Calendar UI in your browser, go to the calendar's **Settings and sharing**
page, and add the service account email under **Share with specific people**
with permission **Make changes to events**.

Without this step, the service account can authenticate but will get 403
errors on any call to the calendar.

### 4. Configure the business YAML

Add to `config/businesses/<business-slug>.yaml`:

```yaml
calendar:
  enabled: true
  calendar_id: "primary"  # or the specific calendar ID
  auth:
    type: "service_account"
    service_account_file: "./secrets/<business-slug>/google-calendar-sa.json"
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
```

### 5. Verify

Start the agent in dev mode and place a test call. Ask the AI to check
availability for a specific time. Logs should show `GoogleCalendarClient:
created event ...` on successful bookings.

## Path B: OAuth 2.0 (personal gmail, or any account)

### 1. Create an OAuth client

1. Go to https://console.cloud.google.com/apis/credentials
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name: anything memorable, e.g. `aireceptionist-desktop`
5. Click **Create**, then **Download JSON**. You'll get a file that contains
   `{"installed": {"client_id": "...", "client_secret": "..."}}`.

### 2. Save the client JSON

```
mkdir -p secrets/<business-slug>
mv ~/Downloads/client_secret_<...>.json secrets/<business-slug>/google-calendar-oauth-client.json
chmod 600 secrets/<business-slug>/google-calendar-oauth-client.json
```

### 3. Run the setup CLI

```
python -m receptionist.booking setup <business-slug>
```

This opens a browser window. Sign in with the Google account whose calendar
you want to use. Approve the requested scopes (you'll see a single scope:
"See and edit events on all your calendars"). The CLI catches the redirect,
extracts the refresh token, and writes it to
`secrets/<business-slug>/google-calendar-oauth.json` with `0600` permissions.

Example successful output:

```
Starting OAuth flow for mdasr...
A browser window will open. Sign in with the Google account whose calendar
you want to use for appointment booking.

...your browser opens...

[OK] OAuth token saved to secrets/mdasr/google-calendar-oauth.json (permissions: 0600)
[OK] Set auth.type: "oauth" and auth.oauth_token_file: "./secrets/mdasr/google-calendar-oauth.json" in
     config/businesses/mdasr.yaml
```

### 4. Configure the business YAML

```yaml
calendar:
  enabled: true
  calendar_id: "primary"
  auth:
    type: "oauth"
    oauth_token_file: "./secrets/<business-slug>/google-calendar-oauth.json"
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
```

### 5. Verify

Same as the service account path — place a test call.

## Troubleshooting

### `403 Forbidden` on free/busy queries

- **Service account path:** the calendar hasn't been shared with the service
  account email. Re-check step A.3.
- **OAuth path:** the account you consented with doesn't own or have edit
  access to the `calendar_id` you configured. Double-check the ID is a
  calendar the signed-in account can write to.

### `HttpError 404: Not Found` on a calendar ID

The `calendar_id` in the YAML doesn't match an accessible calendar. For a
shared calendar, find the full ID in the Google Calendar UI → calendar
settings → **Calendar ID** (a long email-shaped string).

### OAuth token file has overly permissive permissions

The agent refuses to start on Unix if the OAuth token file is readable by
group or other. Fix with:

```
chmod 600 secrets/<business>/google-calendar-oauth.json
```

### OAuth token expired / refresh failed

OAuth refresh tokens eventually expire (Google's policy varies; typically
after ~6 months of inactivity, or when the user revokes the consent). Re-run
the setup CLI to refresh:

```
rm secrets/<business>/google-calendar-oauth.json
python -m receptionist.booking setup <business-slug>
```

### The agent can see availability but can't book

Usually a scope issue. The project uses two narrow scopes:
`https://www.googleapis.com/auth/calendar.events` (create/edit events) and
`https://www.googleapis.com/auth/calendar.freebusy` (read availability). If
you accidentally ran setup with different scopes, the token may not have the
right permissions. Delete the token file and re-run setup.

## Rotating credentials

**Service account:**
1. Create a new key in the Google Cloud service account's Keys tab
2. Replace `secrets/<business>/google-calendar-sa.json` with the new one
3. Delete the old key from the Cloud Console (optional but recommended)
4. Restart the agent

**OAuth:**
1. Delete `secrets/<business>/google-calendar-oauth.json`
2. Re-run `python -m receptionist.booking setup <business-slug>`
3. Restart the agent

## Per-business isolation

Each business has its own `secrets/<business-slug>/` directory. Don't share
credentials between businesses — each gets its own service account or OAuth
token. This makes revocation surgical (revoking one business doesn't affect
others).

## Data & privacy notes

- The agent creates calendar events with the caller's **name** and **phone
  number** in the event description
- Events are tagged `[via AI receptionist / UNVERIFIED]` — staff viewing
  the event can see at a glance that the caller's identity was NOT verified
- If the caller volunteers an **email address**, they're added as an
  **optional attendee** and Google sends them the standard calendar
  invitation (with `.ics`, accept/decline, and "Add to my calendar"). If
  they decline, the event in the organizer's calendar is unaffected
  because optional attendees don't impact free/busy. If no email is
  given, `sendUpdates=none` is used and no email is sent
- For staff-side notifications (separate from caller invites), enable the
  `on_booking` email trigger on the business's `email.triggers` config
- Call IDs (LiveKit room names) are included in event descriptions so staff
  can cross-reference events with call transcripts
