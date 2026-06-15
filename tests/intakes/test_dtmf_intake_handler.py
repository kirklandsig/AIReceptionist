# tests/intakes/test_dtmf_intake_handler.py
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.agent import (
    _ActiveCapture, _DtmfHandlerState, _dispatch_dtmf_event,
)
from receptionist.config import BusinessConfig
from receptionist.intakes.dtmf_capture import DigitCaptureBuffer
from receptionist.lifecycle import CallLifecycle


def _state(config, *, capture=None):
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)
    return _DtmfHandlerState(
        config=config,
        lifecycle=lifecycle,
        session=MagicMock(),
        sip_caller_identity="sip_caller",
        execute_transfer=AsyncMock(),
        speak_goodbye=AsyncMock(),
        capture=capture,
    )


def _event(digit, identity="sip_caller"):
    return SimpleNamespace(digit=digit, participant=SimpleNamespace(identity=identity))


@pytest.mark.asyncio
async def test_armed_capture_routes_digits_to_buffer_not_menu(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    capture = _ActiveCapture(
        buffer=DigitCaptureBuffer(), future=fut, question_key="cb",
    )
    state = _state(config, capture=capture)

    await _dispatch_dtmf_event(_event("6"), state)
    await _dispatch_dtmf_event(_event("3"), state)
    await _dispatch_dtmf_event(_event("1"), state)
    assert not fut.done()
    await _dispatch_dtmf_event(_event("#"), state)

    assert fut.done()
    assert fut.result() == "631"
    assert state.capture is None


@pytest.mark.asyncio
async def test_disarmed_digit_falls_through_to_menu_unmapped(v2_yaml, mocker):
    # With capture disarmed (None) but a real DTMF menu present, an unmapped
    # digit must fall through to the menu path and record "unmapped" — proving
    # the menu lookup still runs while keypad-capture is disarmed.
    menu_yaml = v2_yaml + """
dtmf:
  enabled: true
  menu_announcement_en: "Press 1 for the front desk."
  digits:
    "1":
      action: transfer
      routing: "Front Desk"
      acknowledgment_en: "Transferring you to the front desk."
"""
    config = BusinessConfig.from_yaml_string(menu_yaml)
    state = _state(config, capture=None)
    record = mocker.spy(state.lifecycle, "record_dtmf_event")
    await _dispatch_dtmf_event(_event("5"), state)
    statuses = [c.kwargs.get("status") for c in record.call_args_list]
    assert "unmapped" in statuses


@pytest.mark.asyncio
async def test_capture_star_clears_and_stays_armed(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    capture = _ActiveCapture(
        buffer=DigitCaptureBuffer(), future=fut, question_key="cb",
    )
    state = _state(config, capture=capture)
    await _dispatch_dtmf_event(_event("9"), state)
    await _dispatch_dtmf_event(_event("*"), state)
    assert state.capture is capture
    assert not fut.done()
    await _dispatch_dtmf_event(_event("7"), state)
    await _dispatch_dtmf_event(_event("#"), state)
    assert fut.result() == "7"


@pytest.mark.asyncio
async def test_capture_ignores_non_sip_caller(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    capture = _ActiveCapture(
        buffer=DigitCaptureBuffer(), future=fut, question_key="cb",
    )
    state = _state(config, capture=capture)
    await _dispatch_dtmf_event(_event("6", identity="someone_else"), state)
    assert not fut.done()
    assert capture.buffer.digits == ""
