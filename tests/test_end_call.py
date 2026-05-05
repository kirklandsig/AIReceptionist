# tests/test_end_call.py
"""Tests for the end_call function tool and the _terminate_room helper.

These tests avoid spinning up a real LiveKit AgentSession; the tool body
is exercised by binding the unbound method to a SimpleNamespace stand-in
that carries just the lifecycle and config the tool actually touches.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.agent import (
    _AGENT_END_REASONS,
    _terminate_room,
)
from receptionist.config import BusinessConfig
from receptionist.lifecycle import CallLifecycle


# ---- _terminate_room -------------------------------------------------------


def _job_ctx(*, room_name: str = "room-xyz") -> MagicMock:
    """Mock JobContext exposing api.room.{remove_participant,delete_room}."""
    ctx = MagicMock()
    ctx.room.name = room_name
    ctx.api.room.remove_participant = AsyncMock()
    ctx.api.room.delete_room = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_terminate_room_prefers_remove_participant_for_sip_caller():
    """SIP BYE via remove_participant is the polite path: it drops just the
    caller and leaves the room intact for the agent's close handler."""
    ctx = _job_ctx()
    await _terminate_room(ctx, "sip_17135550038", "room-xyz", call_id="r")
    ctx.api.room.remove_participant.assert_awaited_once()
    ctx.api.room.delete_room.assert_not_awaited()
    # The request payload must carry the room and identity verbatim
    call_args = ctx.api.room.remove_participant.call_args.args[0]
    assert call_args.room == "room-xyz"
    assert call_args.identity == "sip_17135550038"


@pytest.mark.asyncio
async def test_terminate_room_falls_back_to_delete_room_when_remove_fails():
    """If remove_participant raises (token missing room_admin, participant
    already gone, etc.), fall back to delete_room so the call still ends."""
    ctx = _job_ctx()
    ctx.api.room.remove_participant.side_effect = RuntimeError("no admin")
    await _terminate_room(ctx, "sip_17135550038", "room-xyz", call_id="r")
    ctx.api.room.remove_participant.assert_awaited_once()
    ctx.api.room.delete_room.assert_awaited_once()
    delete_args = ctx.api.room.delete_room.call_args.args[0]
    assert delete_args.room == "room-xyz"


@pytest.mark.asyncio
async def test_terminate_room_uses_delete_room_when_no_caller_identity():
    """When _get_caller_identity couldn't resolve a SIP participant
    (Playground/test sessions, unusual BYOC kinds), skip remove and go
    straight to delete_room."""
    ctx = _job_ctx()
    await _terminate_room(ctx, "", "room-xyz", call_id="r")
    ctx.api.room.remove_participant.assert_not_awaited()
    ctx.api.room.delete_room.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminate_room_swallows_delete_room_failure():
    """Last-resort: if even delete_room fails, log and return so the close
    handler eventually fires from natural disconnect."""
    ctx = _job_ctx()
    ctx.api.room.remove_participant.side_effect = RuntimeError("no admin")
    ctx.api.room.delete_room.side_effect = RuntimeError("server down")
    # Must not raise
    await _terminate_room(ctx, "sip_17135550038", "room-xyz", call_id="r")
    ctx.api.room.delete_room.assert_awaited_once()


# ---- end_call tool body ----------------------------------------------------


def _config(v2_yaml: str) -> BusinessConfig:
    return BusinessConfig.from_yaml_string(v2_yaml)


def _bare_receptionist(v2_yaml):
    """Build a Receptionist-shaped object with just the attributes end_call needs.

    Using a SimpleNamespace + bound method avoids invoking the LiveKit Agent
    superclass __init__ (which requires a running session)."""
    from collections import deque
    from receptionist.agent import Receptionist

    config = _config(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)
    obj = SimpleNamespace(
        config=config,
        lifecycle=lifecycle,
        _offered_slot_batches=deque(maxlen=3),
        _calendar_client=None,
    )
    # The function_tool decorator wraps the method; pull the original via __wrapped__
    # if present, otherwise the method itself is callable as an unbound coroutine.
    raw = Receptionist.end_call
    # `function_tool` exposes the original async function via `.fnc` on the
    # FunctionTool wrapper. Tolerate both layouts so future SDK versions work.
    if hasattr(raw, "fnc"):
        raw = raw.fnc
    obj._end_call = raw.__get__(obj)
    return obj, lifecycle


def _ctx_with_session() -> MagicMock:
    """Mock RunContext: ctx.session.generate_reply returns a SpeechHandle-shape mock."""
    handle = MagicMock()
    handle.wait_for_playout = AsyncMock()
    session = MagicMock()
    session.generate_reply = MagicMock(return_value=handle)
    ctx = SimpleNamespace(session=session)
    return ctx, handle


@pytest.mark.asyncio
async def test_end_call_records_outcome_immediately(v2_yaml, monkeypatch):
    """Issue #10: the agent_ended outcome must land on metadata BEFORE the
    background hangup task runs, so racing close events still see it."""
    receptionist, lifecycle = _bare_receptionist(v2_yaml)
    ctx, handle = _ctx_with_session()

    # Stub the job context + speak/terminate so we don't touch real LiveKit
    monkeypatch.setattr("receptionist.agent.get_job_context", lambda: _job_ctx())
    speak_and_terminate = AsyncMock()
    monkeypatch.setattr(
        "receptionist.agent._speak_goodbye_and_terminate", speak_and_terminate,
    )

    result = await receptionist._end_call(ctx)

    # Outcome is recorded synchronously in the tool body (BEFORE the task runs)
    assert lifecycle.metadata.agent_end_reason == "caller_goodbye"
    assert "agent_ended" in lifecycle.metadata.outcomes
    assert "caller_goodbye" in result
    # Drain the scheduled hangup task
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    speak_and_terminate.assert_awaited_once()
    kwargs = speak_and_terminate.call_args.kwargs
    assert kwargs["reason"] == "caller_goodbye"


@pytest.mark.asyncio
async def test_end_call_clamps_invalid_reason_to_caller_goodbye(v2_yaml, monkeypatch):
    """A hallucinated reason must be replaced with caller_goodbye so the
    field stays a closed vocabulary."""
    receptionist, lifecycle = _bare_receptionist(v2_yaml)
    ctx, _ = _ctx_with_session()
    monkeypatch.setattr("receptionist.agent.get_job_context", lambda: _job_ctx())
    monkeypatch.setattr(
        "receptionist.agent._speak_goodbye_and_terminate", AsyncMock(),
    )

    await receptionist._end_call(ctx, reason="rude_caller")

    assert lifecycle.metadata.agent_end_reason == "caller_goodbye"
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_end_call_accepts_known_reasons(v2_yaml, monkeypatch):
    """Reasons reserved for #11 (silence_timeout, unproductive_turns_exhausted,
    max_duration_reached) must all be accepted by end_call."""
    for reason in [
        "silence_timeout", "unproductive_turns_exhausted", "max_duration_reached",
    ]:
        receptionist, lifecycle = _bare_receptionist(v2_yaml)
        ctx, _ = _ctx_with_session()
        monkeypatch.setattr("receptionist.agent.get_job_context", lambda: _job_ctx())
        monkeypatch.setattr(
            "receptionist.agent._speak_goodbye_and_terminate", AsyncMock(),
        )

        await receptionist._end_call(ctx, reason=reason)
        assert lifecycle.metadata.agent_end_reason == reason
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_speak_goodbye_and_terminate_calls_terminate_after_playout(
    v2_yaml, monkeypatch,
):
    """The shared helper must speak goodbye, await playout, then terminate."""
    from receptionist.agent import _speak_goodbye_and_terminate
    from receptionist.config import BusinessConfig

    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)

    handle = MagicMock()
    handle.wait_for_playout = AsyncMock()
    session = MagicMock()
    session.generate_reply = MagicMock(return_value=handle)

    job_ctx = _job_ctx()
    monkeypatch.setattr(
        "receptionist.agent._get_caller_identity", lambda _ctx: "sip_17135550038",
    )
    terminate = AsyncMock()
    monkeypatch.setattr("receptionist.agent._terminate_room", terminate)

    await _speak_goodbye_and_terminate(
        session, lifecycle, job_ctx, reason="caller_goodbye",
    )
    handle.wait_for_playout.assert_awaited_once()
    terminate.assert_awaited_once()


@pytest.mark.asyncio
async def test_speak_goodbye_and_terminate_hangs_up_on_playout_timeout(
    v2_yaml, monkeypatch,
):
    """Belt-and-suspenders: if the goodbye playout never resolves (TTS stall,
    network glitch), the 10s wait timeout must still trigger the hangup
    so the call doesn't get stuck open."""
    from receptionist.agent import _speak_goodbye_and_terminate
    from receptionist.config import BusinessConfig

    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)

    handle = MagicMock()

    async def _hang_forever() -> None:
        await asyncio.sleep(60)

    handle.wait_for_playout = AsyncMock(side_effect=_hang_forever)
    session = MagicMock()
    session.generate_reply = MagicMock(return_value=handle)
    job_ctx = _job_ctx()
    monkeypatch.setattr(
        "receptionist.agent._get_caller_identity", lambda _ctx: "sip_17135550038",
    )
    terminate = AsyncMock()
    monkeypatch.setattr("receptionist.agent._terminate_room", terminate)

    real_wait_for = asyncio.wait_for

    async def _short_wait(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.05)

    monkeypatch.setattr("receptionist.agent.asyncio.wait_for", _short_wait)

    await _speak_goodbye_and_terminate(
        session, lifecycle, job_ctx, reason="caller_goodbye",
    )
    terminate.assert_awaited_once()


def test_agent_end_reason_whitelist_matches_documentation():
    """Hard-pinned vocabulary so future contributors must update both code
    and docs (function-tools-reference.md / CHANGELOG) when adding a reason."""
    assert _AGENT_END_REASONS == frozenset(
        {
            "caller_goodbye",
            "silence_timeout",
            "unproductive_turns_exhausted",
            "max_duration_reached",
        }
    )
