from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.config import (
    AgentConfig, BusinessConfig, DtmfActionConfig, DtmfConfig,
)
from receptionist.lifecycle import CallLifecycle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dtmf_yaml(v2_yaml):
    return v2_yaml + """
dtmf:
  enabled: true
  menu_announcement_en: "Press 1 for the front desk, 0 to leave a message."
  digits:
    "1":
      action: transfer
      routing: "Front Desk"
      acknowledgment_en: "Transferring you to the front desk."
    "0":
      action: take_message
      acknowledgment_en: "I will take a message for you."
    "9":
      action: end_call
      acknowledgment_en: "Thanks, goodbye."
    "*":
      action: repeat_menu
      acknowledgment_en: "Here are the options again."
"""


def _fake_dtmf(digit: str, participant_identity: str = "sip_+15550001"):
    return SimpleNamespace(
        code=int(digit) if digit.isdigit() else 0,
        digit=digit,
        participant=SimpleNamespace(identity=participant_identity),
    )


def _build_state(config: BusinessConfig, *, session=None):
    """Return the per-call DTMF state object the handler closes over."""
    from receptionist.agent import _DtmfHandlerState
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    if session is None:
        session = SimpleNamespace(
            interrupt=MagicMock(),
            generate_reply=AsyncMock(),
            user_state="listening",
        )
    return _DtmfHandlerState(
        config=config,
        lifecycle=lifecycle,
        session=session,
        sip_caller_identity="sip_+15550001",
        execute_transfer=AsyncMock(return_value=SimpleNamespace(
            status="transferred", message="Call transferred to Front Desk",
            target_name="Front Desk",
        )),
        speak_goodbye=AsyncMock(),
        clock=time.monotonic,
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dtmf_transfer_dispatches_execute_transfer(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml)
    state = _build_state(config)

    await _dispatch_dtmf_event(_fake_dtmf("1"), state)

    state.session.interrupt.assert_called_once()
    state.session.generate_reply.assert_awaited()
    state.execute_transfer.assert_awaited_once()
    events = state.lifecycle.metadata.dtmf_events
    assert events[-1].status == "executed"
    assert events[-1].digit == "1"


@pytest.mark.asyncio
async def test_dtmf_take_message_emits_collection_prompt(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml)
    state = _build_state(config)

    await _dispatch_dtmf_event(_fake_dtmf("0"), state)

    state.session.interrupt.assert_called_once()
    instructions = state.session.generate_reply.await_args.kwargs.get("instructions", "")
    assert "take a message" in instructions.lower()
    assert "name" in instructions.lower()
    assert "callback" in instructions.lower()
    assert state.lifecycle.metadata.dtmf_events[-1].status == "executed"


@pytest.mark.asyncio
async def test_dtmf_end_call_invokes_speak_goodbye(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml)
    state = _build_state(config)

    await _dispatch_dtmf_event(_fake_dtmf("9"), state)

    state.speak_goodbye.assert_awaited_once()
    assert state.lifecycle.metadata.dtmf_events[-1].status == "executed"


@pytest.mark.asyncio
async def test_dtmf_repeat_menu_speaks_menu_text(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml)
    state = _build_state(config)

    await _dispatch_dtmf_event(_fake_dtmf("*"), state)

    instructions = state.session.generate_reply.await_args.kwargs.get("instructions", "")
    assert "Press 1 for the front desk" in instructions


@pytest.mark.asyncio
async def test_dtmf_unmapped_digit_records_and_skips(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml)
    state = _build_state(config)

    await _dispatch_dtmf_event(_fake_dtmf("5"), state)

    state.session.interrupt.assert_not_called()
    state.session.generate_reply.assert_not_awaited()
    state.execute_transfer.assert_not_awaited()
    assert state.lifecycle.metadata.dtmf_events[-1].status == "unmapped"


@pytest.mark.asyncio
async def test_dtmf_non_sip_participant_is_ignored(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml)
    state = _build_state(config)

    other = _fake_dtmf("1", participant_identity="agent-self")
    await _dispatch_dtmf_event(other, state)

    state.session.generate_reply.assert_not_awaited()
    assert state.lifecycle.metadata.dtmf_events == []


@pytest.mark.asyncio
async def test_dtmf_disabled_short_circuits(v2_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(v2_yaml)  # no dtmf block
    state = _build_state(config)

    await _dispatch_dtmf_event(_fake_dtmf("1"), state)

    state.session.generate_reply.assert_not_awaited()
    state.execute_transfer.assert_not_awaited()
    assert state.lifecycle.metadata.dtmf_events == []


# ---------------------------------------------------------------------------
# Debounce + in-flight suppression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dtmf_same_digit_within_debounce_is_ignored(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml)
    state = _build_state(config)
    # Use a fake clock so the test isn't time-flaky.
    fake_now = [1000.0]
    state.clock = lambda: fake_now[0]

    await _dispatch_dtmf_event(_fake_dtmf("1"), state)
    fake_now[0] += 0.5  # < 1.5s debounce window
    await _dispatch_dtmf_event(_fake_dtmf("1"), state)

    assert state.execute_transfer.await_count == 1
    statuses = [e.status for e in state.lifecycle.metadata.dtmf_events]
    assert statuses == ["executed", "duplicate_ignored"]


@pytest.mark.asyncio
async def test_dtmf_different_digit_while_in_flight_is_suppressed(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml)
    state = _build_state(config)

    # Hold the execute_transfer call pending so the second event arrives
    # while the first is still in flight.
    in_flight = asyncio.Event()
    proceed = asyncio.Event()

    async def slow_transfer(*args, **kwargs):
        in_flight.set()
        await proceed.wait()
        return SimpleNamespace(
            status="transferred", message="ok", target_name="Front Desk",
        )

    state.execute_transfer = slow_transfer

    task = asyncio.create_task(_dispatch_dtmf_event(_fake_dtmf("1"), state))
    await in_flight.wait()
    await _dispatch_dtmf_event(_fake_dtmf("0"), state)
    statuses_during = [e.status for e in state.lifecycle.metadata.dtmf_events]
    assert "suppressed_in_flight" in statuses_during

    proceed.set()
    await task


# ---------------------------------------------------------------------------
# intake_only behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dtmf_transfer_in_intake_only_refuses_and_pivots(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml).model_copy(
        update={"agent": AgentConfig(mode="intake_only")},
    )
    state = _build_state(config)
    state.execute_transfer = AsyncMock(return_value=SimpleNamespace(
        status="intake_only_refused",
        message="cannot transfer",
        target_name="Front Desk",
    ))

    await _dispatch_dtmf_event(_fake_dtmf("1"), state)

    # Two generate_reply calls: ack + pivot to take_message.
    assert state.session.generate_reply.await_count == 2
    last_call = state.session.generate_reply.await_args_list[-1]
    assert "take a message" in last_call.kwargs["instructions"].lower()
    assert state.lifecycle.metadata.dtmf_events[-1].status == "refused_intake_only"


@pytest.mark.asyncio
async def test_dtmf_take_message_in_intake_only_still_runs(dtmf_yaml):
    from receptionist.agent import _dispatch_dtmf_event

    config = BusinessConfig.from_yaml_string(dtmf_yaml).model_copy(
        update={"agent": AgentConfig(mode="intake_only")},
    )
    state = _build_state(config)

    await _dispatch_dtmf_event(_fake_dtmf("0"), state)

    state.session.generate_reply.assert_awaited()
    assert state.lifecycle.metadata.dtmf_events[-1].status == "executed"
