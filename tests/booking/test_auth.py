# tests/booking/test_auth.py
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from receptionist.booking.auth import (
    CalendarAuthError, build_credentials, SCOPES,
)
from receptionist.config import OAuthAuth, ServiceAccountAuth


def test_scopes_is_events_only():
    """Least-privilege: only calendar.events scope, not full calendar."""
    assert SCOPES == ["https://www.googleapis.com/auth/calendar.events"]


def test_build_credentials_service_account(tmp_path):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps({
        "type": "service_account",
        "project_id": "test",
        "private_key_id": "x",
        "private_key": "-----BEGIN FAKE KEY-----\n...\n",
        "client_email": "test@example.iam.gserviceaccount.com",
        "client_id": "123",
    }), encoding="utf-8")

    fake_creds = MagicMock(name="service_account_creds")
    with patch(
        "receptionist.booking.auth.service_account.Credentials.from_service_account_file",
        return_value=fake_creds,
    ) as mock_from_file:
        auth = ServiceAccountAuth(type="service_account", service_account_file=str(sa_file))
        creds = build_credentials(auth)

    assert creds is fake_creds
    mock_from_file.assert_called_once_with(str(sa_file), scopes=SCOPES)


def test_build_credentials_service_account_missing_file(tmp_path):
    """Missing file raises CalendarAuthError, not a cryptic FileNotFoundError."""
    auth = ServiceAccountAuth(
        type="service_account",
        service_account_file=str(tmp_path / "does-not-exist.json"),
    )
    with pytest.raises(CalendarAuthError, match="not found"):
        build_credentials(auth)


def test_build_credentials_oauth_loads_saved_token(tmp_path):
    token_file = tmp_path / "oauth.json"
    token_file.write_text(json.dumps({
        "token": "access",
        "refresh_token": "refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "c",
        "client_secret": "s",
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
    }), encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(token_file, 0o600)

    fake_creds = MagicMock(name="oauth_creds", valid=True)
    with patch(
        "receptionist.booking.auth.Credentials.from_authorized_user_file",
        return_value=fake_creds,
    ) as mock_from_file:
        auth = OAuthAuth(type="oauth", oauth_token_file=str(token_file))
        creds = build_credentials(auth)

    assert creds is fake_creds
    mock_from_file.assert_called_once_with(str(token_file), SCOPES)


def test_build_credentials_oauth_refreshes_expired(tmp_path):
    """If the loaded Credentials are expired but have a refresh_token, refresh them."""
    token_file = tmp_path / "oauth.json"
    token_file.write_text('{"refresh_token": "r"}', encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(token_file, 0o600)

    fake_creds = MagicMock(
        name="oauth_creds", valid=False, expired=True, refresh_token="r",
    )
    with patch(
        "receptionist.booking.auth.Credentials.from_authorized_user_file",
        return_value=fake_creds,
    ):
        auth = OAuthAuth(type="oauth", oauth_token_file=str(token_file))
        build_credentials(auth)

    fake_creds.refresh.assert_called_once()


def test_build_credentials_oauth_missing_file(tmp_path):
    auth = OAuthAuth(
        type="oauth",
        oauth_token_file=str(tmp_path / "missing.json"),
    )
    with pytest.raises(CalendarAuthError, match="not found"):
        build_credentials(auth)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows does not enforce POSIX mode bits")
def test_build_credentials_oauth_rejects_loose_permissions(tmp_path):
    """0600 required on Unix — looser perms fail to prevent shared-host leakage."""
    token_file = tmp_path / "oauth.json"
    token_file.write_text('{"refresh_token": "r"}', encoding="utf-8")
    os.chmod(token_file, 0o644)

    auth = OAuthAuth(type="oauth", oauth_token_file=str(token_file))
    with pytest.raises(CalendarAuthError, match="permissions"):
        build_credentials(auth)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows does not enforce POSIX mode bits")
def test_build_credentials_oauth_accepts_0600(tmp_path):
    token_file = tmp_path / "oauth.json"
    token_file.write_text('{"refresh_token": "r"}', encoding="utf-8")
    os.chmod(token_file, 0o600)

    fake_creds = MagicMock(valid=True)
    with patch(
        "receptionist.booking.auth.Credentials.from_authorized_user_file",
        return_value=fake_creds,
    ):
        auth = OAuthAuth(type="oauth", oauth_token_file=str(token_file))
        build_credentials(auth)
