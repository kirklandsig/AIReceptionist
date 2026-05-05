# tests/test_voice_idle.py
"""Issue #11: silence-timeout, max-duration, and unproductive-turn safety nets.

Covers the `VoiceIdleConfig` schema, the unproductive-turn counter on
Receptionist, and the message-text extractor used to score agent replies.
"""
from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.agent import _extract_message_text
from receptionist.config import BusinessConfig, VoiceIdleConfig
from receptionist.lifecycle import CallLifecycle


# ---- VoiceIdleConfig schema ------------------------------------------------


def test_voice_idle_defaults_match_design_spec():
    """Defaults: silence on (15s+30s), max duration off, unproductive on at 5."""
    cfg = VoiceIdleConfig()
    assert cfg.silence_hangup_enabled is True
    assert cfg.away_seconds == 15.0
    assert cfg.silence_grace_seconds == 30.0
    assert cfg.max_call_duration_seconds is None
    assert cfg.unproductive_hangup_enabled is True
    assert cfg.unproductive_turn_threshold == 5
    # Default phrase list covers Trinicom's Blade Runner-style deflections
    assert any("here to help" in p for p in cfg.unproductive_phrases)


def test_voice_idle_extra_fields_rejected():
    """Strict schema: typos are loud, not silent."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VoiceIdleConfig(silence_hangup=True)  # wrong field name


def test_voice_idle_threshold_must_be_positive():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VoiceIdleConfig(unproductive_turn_threshold=0)


def test_voice_idle_max_duration_must_be_positive_when_set():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VoiceIdleConfig(max_call_duration_seconds=0)


def test_voice_idle_away_seconds_must_be_positive():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VoiceIdleConfig(away_seconds=0)


def test_voice_config_idle_yaml_round_trip():
    """A YAML business config can override voice.idle without breaking
    backward compat (omitting voice.idle preserves defaults)."""
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice:
  voice_id: marin
  idle:
    silence_hangup_enabled: false
    away_seconds: 20
    silence_grace_seconds: 45
    max_call_duration_seconds: 600
    unproductive_turn_threshold: 3
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
"""
    cfg = BusinessConfig.from_yaml_string(yaml_text)
    idle = cfg.voice.idle
    assert idle.silence_hangup_enabled is False
    assert idle.away_seconds == 20.0
    assert idle.silence_grace_seconds == 45.0
    assert idle.max_call_duration_seconds == 600
    assert idle.unproductive_turn_threshold == 3


def test_voice_config_omitted_idle_uses_defaults(v2_yaml):
    """Existing YAMLs without `voice.idle` must keep working unchanged."""
    cfg = BusinessConfig.from_yaml_string(v2_yaml)
    assert cfg.voice.idle.silence_hangup_enabled is True
    assert cfg.voice.idle.unproductive_turn_threshold == 5


# ---- _extract_message_text -------------------------------------------------


def test_extract_message_text_string_content():
    item = SimpleNamespace(content="hello world")
    assert _extract_message_text(item) == "hello world"


def test_extract_message_text_list_of_text_parts():
    parts = [SimpleNamespace(text="hello"), SimpleNamespace(text="world")]
    item = SimpleNamespace(content=parts)
    assert _extract_message_text(item) == "hello world"


def test_extract_message_text_falls_back_to_transcript():
    """Audio-modality replies don't carry .text but do carry .transcript."""
    parts = [SimpleNamespace(transcript="audio reply transcript")]
    item = SimpleNamespace(content=parts)
    assert _extract_message_text(item) == "audio reply transcript"


def test_extract_message_text_empty_returns_empty():
    item = SimpleNamespace(content=None)
    assert _extract_message_text(item) == ""


# ---- Unproductive-turn counter on Receptionist -----------------------------


def _bare_receptionist(v2_yaml: str):
    """Build a Receptionist-shaped object for #11 counter tests.

    Bypasses the LiveKit Agent superclass __init__ (which requires a session)
    by binding the unbound methods to a SimpleNamespace stand-in carrying
    only the attributes the unproductive-turn handlers read."""
    from receptionist.agent import Receptionist

    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)
    obj = SimpleNamespace(
        config=config,
        lifecycle=lifecycle,
        session=MagicMock(),
        _consecutive_unproductive_turns=0,
        _current_turn_has_user_input=False,
        _current_turn_used_tool=False,
        _current_turn_assistant_replied=False,
        _unproductive_end_scheduled=False,
        _offered_slot_batches=deque(maxlen=3),
        _calendar_client=None,
    )
    obj._on_user_input_transcribed = (
        Receptionist._on_user_input_transcribed.__get__(obj)
    )
    obj._on_function_tools_executed = (
        Receptionist._on_function_tools_executed.__get__(obj)
    )
    obj._on_conversation_item_added = (
        Receptionist._on_conversation_item_added.__get__(obj)
    )
    return obj


def _user_event(*, is_final: bool = True):
    return SimpleNamespace(is_final=is_final)


def _assistant_item(text: str):
    item = SimpleNamespace(role="assistant", content=text)
    return SimpleNamespace(item=item)


def _user_item(text: str):
    item = SimpleNamespace(role="user", content=text)
    return SimpleNamespace(item=item)


def test_unproductive_counter_increments_on_deflection_phrase(v2_yaml):
    r = _bare_receptionist(v2_yaml)
    r._on_user_input_transcribed(_user_event())
    r._on_conversation_item_added(_assistant_item("I'm here to help!"))
    assert r._consecutive_unproductive_turns == 1


def test_unproductive_counter_ignores_pre_user_agent_speech(v2_yaml):
    r = _bare_receptionist(v2_yaml)
    r.config.voice.idle.unproductive_turn_threshold = 1

    r._on_conversation_item_added(_assistant_item("I'm here to help!"))

    assert r._consecutive_unproductive_turns == 0
    assert r.lifecycle.metadata.agent_end_reason is None


def test_unproductive_counter_resets_on_function_tool_call(v2_yaml):
    """Issue #11: any function-tool invocation (lookup_faq, get_business_hours,
    etc.) is a productive signal; the counter must reset to 0."""
    r = _bare_receptionist(v2_yaml)
    # Two unproductive turns
    for _ in range(2):
        r._on_user_input_transcribed(_user_event())
        r._on_conversation_item_added(_assistant_item("I'm here to help."))
    assert r._consecutive_unproductive_turns == 2

    # Productive turn: tool fires
    r._on_user_input_transcribed(_user_event())
    r._on_function_tools_executed(SimpleNamespace())
    r._on_conversation_item_added(_assistant_item("Yes, we accept Cigna."))
    assert r._consecutive_unproductive_turns == 0


def test_unproductive_counter_resets_on_substantive_reply(v2_yaml):
    """A reply that doesn't match any deflection phrase is treated as
    substantive and resets the counter."""
    r = _bare_receptionist(v2_yaml)
    r._on_user_input_transcribed(_user_event())
    r._on_conversation_item_added(_assistant_item("I'm here to help!"))
    assert r._consecutive_unproductive_turns == 1

    r._on_user_input_transcribed(_user_event())
    r._on_conversation_item_added(_assistant_item(
        "We're open Monday through Friday from 8 AM to 5 PM."
    ))
    assert r._consecutive_unproductive_turns == 0


def test_unproductive_counter_only_scores_first_assistant_reply_per_turn(v2_yaml):
    """An assistant message followed by a follow-up in the same turn must
    not double-count the deflection (otherwise two replies in a single
    turn would burn the budget twice)."""
    r = _bare_receptionist(v2_yaml)
    r._on_user_input_transcribed(_user_event())
    r._on_conversation_item_added(_assistant_item("I'm here to help."))
    r._on_conversation_item_added(_assistant_item("I'm here to assist."))
    assert r._consecutive_unproductive_turns == 1


def test_unproductive_counter_ignored_when_disabled(v2_yaml):
    """When `voice.idle.unproductive_hangup_enabled: false`, the counter is
    a no-op and the agent will never end on this path."""
    yaml_text = v2_yaml.replace(
        '  model: "gpt-realtime-1.5"',
        '  model: "gpt-realtime-1.5"\n  idle:\n    unproductive_hangup_enabled: false',
    )
    r = _bare_receptionist(yaml_text)
    for _ in range(20):
        r._on_user_input_transcribed(_user_event())
        r._on_conversation_item_added(_assistant_item("I'm here to help."))
    assert r._consecutive_unproductive_turns == 0


@pytest.mark.asyncio
async def test_unproductive_counter_triggers_end_at_threshold(v2_yaml, monkeypatch):
    """At the configured threshold, the counter records `agent_ended` with
    reason `unproductive_turns_exhausted` and schedules the goodbye+terminate
    background task."""
    r = _bare_receptionist(v2_yaml)
    # Override threshold to 3 for a faster test
    r.config.voice.idle.unproductive_turn_threshold = 3

    speak_and_terminate = AsyncMock()
    monkeypatch.setattr(
        "receptionist.agent._speak_goodbye_and_terminate", speak_and_terminate,
    )
    monkeypatch.setattr(
        "receptionist.agent.get_job_context",
        lambda: SimpleNamespace(room=SimpleNamespace(name="room-xyz"), api=MagicMock()),
    )

    for _ in range(3):
        r._on_user_input_transcribed(_user_event())
        r._on_conversation_item_added(_assistant_item("I'm here to help."))

    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    assert r.lifecycle.metadata.agent_end_reason == "unproductive_turns_exhausted"
    assert "agent_ended" in r.lifecycle.metadata.outcomes
    speak_and_terminate.assert_awaited_once()
    assert speak_and_terminate.call_args.kwargs["reason"] == "unproductive_turns_exhausted"


@pytest.mark.asyncio
async def test_unproductive_end_only_fires_once(v2_yaml, monkeypatch):
    """Subsequent unproductive replies after the threshold must not re-fire
    the goodbye+terminate background task."""
    r = _bare_receptionist(v2_yaml)
    r.config.voice.idle.unproductive_turn_threshold = 2

    speak_and_terminate = AsyncMock()
    monkeypatch.setattr(
        "receptionist.agent._speak_goodbye_and_terminate", speak_and_terminate,
    )
    monkeypatch.setattr(
        "receptionist.agent.get_job_context",
        lambda: SimpleNamespace(room=SimpleNamespace(name="room-xyz"), api=MagicMock()),
    )

    for _ in range(5):
        r._on_user_input_transcribed(_user_event())
        r._on_conversation_item_added(_assistant_item("I'm here to help."))

    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    speak_and_terminate.assert_awaited_once()


def test_unproductive_counter_ignores_user_role_items(v2_yaml):
    """Counter logic must only inspect assistant items; a user item that
    happens to contain a deflection phrase shouldn't increment the counter."""
    r = _bare_receptionist(v2_yaml)
    r._on_user_input_transcribed(_user_event())
    r._on_conversation_item_added(_user_item("I'm here to help, can you help?"))
    assert r._consecutive_unproductive_turns == 0
