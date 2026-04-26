# receptionist/booking/client.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build

logger = logging.getLogger("receptionist")


class GoogleCalendarClient:
    """Thin async wrapper over google-api-python-client's Calendar v3 service.

    All Google API calls are synchronous in google-api-python-client, so we
    wrap them in asyncio.to_thread to keep the event loop unblocked during
    calls.
    """

    def __init__(self, credentials, calendar_id: str) -> None:
        self.credentials = credentials
        self.calendar_id = calendar_id
        # cache_discovery=False is the documented pattern; avoids noisy
        # warnings about oauth2client absence in production.
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    async def free_busy(
        self, time_min: datetime, time_max: datetime
    ) -> list[tuple[datetime, datetime]]:
        """Query free/busy. Returns list of (start, end) tuples of busy intervals.

        time_min / time_max must be timezone-aware datetime objects.
        Returned datetimes preserve the timezone from Google's RFC 3339 response
        (typically UTC when the response uses the 'Z' suffix).
        """
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": self.calendar_id}],
        }
        response = await asyncio.to_thread(
            lambda: self._service.freebusy().query(body=body).execute()
        )
        busy_raw = response.get("calendars", {}).get(self.calendar_id, {}).get("busy", [])
        return [
            (_parse_rfc3339(b["start"]), _parse_rfc3339(b["end"]))
            for b in busy_raw
        ]

    async def create_event(
        self,
        *,
        start: datetime,
        end: datetime,
        summary: str,
        description: str,
        time_zone: str,
        location: str | None = None,
        attendee_email: str | None = None,
    ) -> dict[str, Any]:
        """Create a calendar event. Returns {id, htmlLink, ...}.

        `time_zone` is an IANA zone string (e.g. "America/New_York"). The start/end
        datetimes are rendered as wall-clock times in that zone in the request body
        so Google honors the configured timezone semantics.

        When `attendee_email` is given, the caller is added as an OPTIONAL attendee
        and Google sends them the standard calendar invitation (with .ics, accept/
        decline, "Add to my calendar"). Optional attendees do not affect the
        organizer's busy view if they decline. When None, no email is sent
        (sendUpdates="none").
        """
        body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": time_zone,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": time_zone,
            },
        }
        if location:
            body["location"] = location

        # If a caller email is provided, add them as an optional attendee.
        # optional=True keeps the event off-impact in the organizer's free/busy:
        # a caller decline won't make our event look "tentative" or flag conflicts.
        if attendee_email:
            body["attendees"] = [
                {"email": attendee_email, "optional": True, "responseStatus": "needsAction"},
            ]
            send_updates = "all"
        else:
            send_updates = "none"

        result = await asyncio.to_thread(
            lambda: self._service.events().insert(
                calendarId=self.calendar_id,
                body=body,
                sendUpdates=send_updates,
            ).execute()
        )
        logger.info(
            "GoogleCalendarClient: created event %s (%s)",
            result.get("id"), result.get("htmlLink"),
        )
        return result


def _parse_rfc3339(s: str) -> datetime:
    """Parse Google's RFC 3339 timestamp. Handles both 'Z' suffix and '+HH:MM' offsets."""
    # Python's fromisoformat handles '+HH:MM' natively. The 'Z' suffix needs substitution.
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
