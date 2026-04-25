# tests/booking/test_client.py
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from receptionist.booking.client import GoogleCalendarClient


def _fake_service(freebusy_response=None, insert_response=None):
    """Construct a MagicMock that looks enough like googleapiclient's service.

    service.freebusy().query(body=...).execute() -> freebusy_response
    service.events().insert(...).execute() -> insert_response
    """
    svc = MagicMock()
    svc.freebusy.return_value.query.return_value.execute.return_value = (
        freebusy_response or {"calendars": {"primary": {"busy": []}}}
    )
    svc.events.return_value.insert.return_value.execute.return_value = (
        insert_response or {"id": "evt123", "htmlLink": "https://cal.example/evt123"}
    )
    return svc


@pytest.mark.asyncio
async def test_free_busy_builds_request_body(mocker):
    fake_service = _fake_service(freebusy_response={
        "calendars": {"primary": {"busy": [
            {"start": "2026-04-28T14:00:00Z", "end": "2026-04-28T15:00:00Z"},
        ]}},
    })
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)

    creds = MagicMock()
    client = GoogleCalendarClient(creds, calendar_id="primary")

    t_min = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    t_max = datetime(2026, 4, 28, 17, 0, tzinfo=timezone.utc)
    busy = await client.free_busy(t_min, t_max)

    assert len(busy) == 1
    start, end = busy[0]
    assert start == datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc)

    # Inspect the request body
    call_kwargs = fake_service.freebusy.return_value.query.call_args.kwargs
    body = call_kwargs["body"]
    assert body["items"] == [{"id": "primary"}]
    assert body["timeMin"].startswith("2026-04-28T09:00")
    assert body["timeMax"].startswith("2026-04-28T17:00")


@pytest.mark.asyncio
async def test_free_busy_parses_rfc3339_z_suffix(mocker):
    """Google returns times as RFC 3339. The 'Z' suffix (UTC) must parse correctly."""
    fake_service = _fake_service(freebusy_response={
        "calendars": {"primary": {"busy": [
            {"start": "2026-04-28T14:00:00Z", "end": "2026-04-28T15:30:00Z"},
        ]}},
    })
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)

    client = GoogleCalendarClient(MagicMock(), calendar_id="primary")
    busy = await client.free_busy(
        datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 29, 0, 0, tzinfo=timezone.utc),
    )
    start, end = busy[0]
    assert start.tzinfo is not None
    assert end == datetime(2026, 4, 28, 15, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_free_busy_empty_result(mocker):
    fake_service = _fake_service(freebusy_response={
        "calendars": {"primary": {"busy": []}},
    })
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)
    client = GoogleCalendarClient(MagicMock(), calendar_id="primary")
    busy = await client.free_busy(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert busy == []


@pytest.mark.asyncio
async def test_create_event_sends_correct_body(mocker):
    fake_service = _fake_service(insert_response={
        "id": "evt-new-123",
        "htmlLink": "https://calendar.google.com/event?eid=abc",
    })
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)
    client = GoogleCalendarClient(MagicMock(), calendar_id="primary")

    result = await client.create_event(
        start=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc),
        summary="Appointment: Jane Doe",
        description="[via AI receptionist / UNVERIFIED]",
        time_zone="America/New_York",
    )

    assert result == {
        "id": "evt-new-123",
        "htmlLink": "https://calendar.google.com/event?eid=abc",
    }

    call_kwargs = fake_service.events.return_value.insert.call_args.kwargs
    assert call_kwargs["calendarId"] == "primary"
    assert call_kwargs["sendUpdates"] == "none"
    body = call_kwargs["body"]
    assert body["summary"] == "Appointment: Jane Doe"
    assert body["description"] == "[via AI receptionist / UNVERIFIED]"
    assert body["start"]["timeZone"] == "America/New_York"
    assert body["end"]["timeZone"] == "America/New_York"
    assert body["start"]["dateTime"].startswith("2026-04-28T14:00")
    assert body["end"]["dateTime"].startswith("2026-04-28T14:30")


@pytest.mark.asyncio
async def test_create_event_http_error_propagates(mocker):
    """HttpError from googleapiclient is not swallowed — the caller decides."""
    from googleapiclient.errors import HttpError
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.side_effect = (
        HttpError(resp=MagicMock(status=403), content=b'{"error": "permission denied"}')
    )
    mocker.patch("receptionist.booking.client.build", return_value=fake_service)
    client = GoogleCalendarClient(MagicMock(), calendar_id="primary")

    with pytest.raises(HttpError):
        await client.create_event(
            start=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
            end=datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc),
            summary="x", description="x", time_zone="UTC",
        )
