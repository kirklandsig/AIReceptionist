# receptionist/booking/auth.py
from __future__ import annotations

import logging
import stat
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

from receptionist.config import CalendarAuth, OAuthAuth, ServiceAccountAuth

logger = logging.getLogger("receptionist")

# Least-privilege: we read free/busy and create events. Not full calendar.
# - calendar.events: create/edit events on calendars we have access to
# - calendar.freebusy: query free/busy on calendars (events scope alone is
#   not sufficient — Google treats freeBusy as a calendar-level op).
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
]


class CalendarAuthError(Exception):
    """Raised when calendar credentials can't be loaded or refreshed."""


def build_credentials(auth: CalendarAuth):
    """Build a google-auth Credentials object from a CalendarAuth config.

    Raises CalendarAuthError with a clear message on any failure.
    """
    if isinstance(auth, ServiceAccountAuth):
        return _build_service_account(auth)
    if isinstance(auth, OAuthAuth):
        return _build_oauth(auth)
    raise CalendarAuthError(f"Unknown calendar auth type: {type(auth).__name__}")


def _build_service_account(auth: ServiceAccountAuth):
    path = Path(auth.service_account_file)
    if not path.exists():
        raise CalendarAuthError(
            f"Service account key not found: {auth.service_account_file}"
        )
    try:
        return service_account.Credentials.from_service_account_file(
            str(path), scopes=SCOPES,
        )
    except Exception as e:
        raise CalendarAuthError(f"Failed to load service account key: {e}") from e


def _build_oauth(auth: OAuthAuth):
    path = Path(auth.oauth_token_file)
    if not path.exists():
        raise CalendarAuthError(
            f"OAuth token file not found: {auth.oauth_token_file}. "
            f"Run `python -m receptionist.booking setup <business-slug>` first."
        )
    _check_token_permissions(path)
    try:
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    except Exception as e:
        raise CalendarAuthError(f"Failed to load OAuth token: {e}") from e

    # Refresh if expired and we have a refresh token
    if not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            raise CalendarAuthError(f"Failed to refresh OAuth token: {e}") from e

    return creds


def _check_token_permissions(path: Path) -> None:
    """Reject OAuth token files with world/group-readable permissions on Unix."""
    if sys.platform == "win32":
        return  # Windows doesn't have POSIX mode bits
    mode = path.stat().st_mode
    # Bits we care about: group + other read/write/exec. Owner bits are fine.
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CalendarAuthError(
            f"OAuth token file has overly permissive permissions: {oct(mode & 0o777)}. "
            f"Run `chmod 0600 {path}` and try again."
        )
