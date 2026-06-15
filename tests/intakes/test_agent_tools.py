# tests/intakes/test_agent_tools.py
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from receptionist.lifecycle import CallLifecycle


def _config_with_intakes(v2_yaml: str, *, intake_file_path: str):
    from receptionist.config import (
        BusinessConfig, IntakesConfig, IntakeCaseType, IntakeQuestion,
        IntakeSubmissionConfig,
    )
    base = BusinessConfig.from_yaml_string(v2_yaml)
    return base.model_copy(update={
        "intakes": IntakesConfig(
            enabled=True,
            preamble_en="This takes 15-20 minutes.",
            submission=IntakeSubmissionConfig(file_path=intake_file_path),
            case_types=[
                IntakeCaseType(
                    key="example_intake",
                    display_name="Example intake",
                    display_name_es="Entrevista de ejemplo",
                    questions=[
                        IntakeQuestion(
                            key="caller_full_name",
                            prompt_en="Full legal name?",
                            prompt_es="¿Nombre legal completo?",
                            required=True,
                            critical=True,
                            validation="text",
                        ),
                        IntakeQuestion(
                            key="employer",
                            prompt_en="Who was your employer?",
                            prompt_es="¿Quién era su empleador?",
                            required=True,
                            critical=False,
                            validation="text",
                        ),
                    ],
                ),
            ],
        ),
    })


def _config_with_dtmf_intake(v2_yaml):
    from receptionist.config import (
        BusinessConfig, IntakesConfig, IntakeCaseType, IntakeQuestion,
        IntakeSubmissionConfig,
    )
    base = BusinessConfig.from_yaml_string(v2_yaml)
    return base.model_copy(update={
        "intakes": IntakesConfig(
            enabled=True,
            submission=IntakeSubmissionConfig(file_path="./m/intakes/"),
            case_types=[
                IntakeCaseType(
                    key="wc", display_name="WC",
                    questions=[
                        IntakeQuestion(key="name", prompt_en="Name?"),
                        IntakeQuestion(
                            key="cb", prompt_en="Number?",
                            input="dtmf", dtmf_length=10,
                        ),
                    ],
                ),
            ],
        ),
    })


def _keypad_receptionist(config, lifecycle, dtmf_state):
    """Bare receptionist exposing await_keypad_entry, with a _dtmf_state slot."""
    from receptionist.agent import Receptionist
    obj = SimpleNamespace(config=config, lifecycle=lifecycle, _dtmf_state=dtmf_state)
    raw = Receptionist.await_keypad_entry
    fn = raw.fnc if hasattr(raw, "fnc") else raw
    obj._await_keypad_entry = fn.__get__(obj)
    return obj


def _bare_receptionist(config, lifecycle):
    """Build a Receptionist-shaped object with the intake state the tools need.

    Avoids the LiveKit Agent superclass init.
    """
    from receptionist.agent import Receptionist
    from receptionist.intakes.models import IntakeAnswer

    obj = SimpleNamespace(
        config=config,
        lifecycle=lifecycle,
        _IntakeAnswer=IntakeAnswer,
        _intake_answers={},
        _intake_case_type=None,
        _intake_language="en",
        _intake_started_at=None,
    )

    def _unwrap(method):
        return method.fnc if hasattr(method, "fnc") else method

    obj._record_intake_answer = _unwrap(Receptionist.record_intake_answer).__get__(obj)
    obj._finalize_intake = _unwrap(Receptionist.finalize_intake).__get__(obj)
    return obj


@pytest.fixture
def fake_ctx():
    return SimpleNamespace()


@pytest.mark.asyncio
async def test_record_intake_answer_persists_partial_and_tracks_state(
    tmp_path, v2_yaml, fake_ctx,
):
    config = _config_with_intakes(v2_yaml, intake_file_path=str(tmp_path))
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    result = await r._record_intake_answer(
        fake_ctx,
        case_type="example_intake",
        question_key="caller_full_name",
        spoken_text="Jane Doe",
        language="en",
        english_summary="Jane Doe",
    )
    assert "recorded" in result.lower()
    assert r._intake_case_type == "example_intake"
    assert "caller_full_name" in r._intake_answers
    # Partial file written
    partials = list(tmp_path.glob("intake_*.partial.json"))
    assert len(partials) == 1
    data = json.loads(partials[0].read_text(encoding="utf-8"))
    assert data["status"] == "partial"
    assert len(data["answers"]) == 1
    assert data["answers"][0]["spoken_text"] == "Jane Doe"


@pytest.mark.asyncio
async def test_record_intake_answer_queues_partial_submission_for_email(
    tmp_path, v2_yaml, fake_ctx,
):
    config = _config_with_intakes(v2_yaml, intake_file_path=str(tmp_path))
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    await r._record_intake_answer(
        fake_ctx,
        case_type="example_intake",
        question_key="caller_full_name",
        spoken_text="Jane Doe",
        language="en",
        english_summary="Jane Doe",
    )

    assert lifecycle._pending_intake_submission is not None
    assert lifecycle._pending_intake_submission.status == "partial"
    assert lifecycle._pending_intake_submission.answers[0].spoken_text == "Jane Doe"
    assert lifecycle._intake_case_type_display == "Example intake"


@pytest.mark.asyncio
async def test_record_intake_answer_rejects_unknown_case_type(
    tmp_path, v2_yaml, fake_ctx,
):
    config = _config_with_intakes(v2_yaml, intake_file_path=str(tmp_path))
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    result = await r._record_intake_answer(
        fake_ctx,
        case_type="not_a_real_case_type",
        question_key="caller_full_name",
        spoken_text="Jane",
    )
    assert "Unknown case type" in result
    assert r._intake_case_type is None
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.asyncio
async def test_record_intake_answer_rejects_unknown_question_key(
    tmp_path, v2_yaml, fake_ctx,
):
    config = _config_with_intakes(v2_yaml, intake_file_path=str(tmp_path))
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    result = await r._record_intake_answer(
        fake_ctx,
        case_type="example_intake",
        question_key="not_a_real_question",
        spoken_text="something",
    )
    assert "Unknown question key" in result


@pytest.mark.asyncio
async def test_record_intake_answer_disabled_returns_friendly_error(
    tmp_path, v2_yaml, fake_ctx,
):
    # Build a config WITHOUT intakes enabled
    from receptionist.config import BusinessConfig
    config = BusinessConfig.from_yaml_string(v2_yaml)  # no intakes
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    result = await r._record_intake_answer(
        fake_ctx,
        case_type="example_intake",
        question_key="caller_full_name",
        spoken_text="Jane",
    )
    assert "not enabled" in result.lower()


@pytest.mark.asyncio
async def test_record_intake_answer_clears_state_on_case_type_change(
    tmp_path, v2_yaml, fake_ctx,
):
    from receptionist.config import (
        BusinessConfig, IntakesConfig, IntakeCaseType, IntakeQuestion,
        IntakeSubmissionConfig,
    )
    base = BusinessConfig.from_yaml_string(v2_yaml)
    config = base.model_copy(update={
        "intakes": IntakesConfig(
            enabled=True,
            submission=IntakeSubmissionConfig(file_path=str(tmp_path)),
            case_types=[
                IntakeCaseType(
                    key="case_a",
                    display_name="Case A",
                    questions=[IntakeQuestion(key="q1", prompt_en="A1?")],
                ),
                IntakeCaseType(
                    key="case_b",
                    display_name="Case B",
                    questions=[IntakeQuestion(key="q1", prompt_en="B1?")],
                ),
            ],
        ),
    })
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    await r._record_intake_answer(
        fake_ctx, case_type="case_a", question_key="q1", spoken_text="answer-a",
    )
    assert r._intake_case_type == "case_a"
    assert "q1" in r._intake_answers
    assert r._intake_answers["q1"].spoken_text == "answer-a"

    # Caller corrects: actually it's case_b
    await r._record_intake_answer(
        fake_ctx, case_type="case_b", question_key="q1", spoken_text="answer-b",
    )
    assert r._intake_case_type == "case_b"
    # Prior answers wiped
    assert r._intake_answers["q1"].spoken_text == "answer-b"
    assert len(r._intake_answers) == 1


@pytest.mark.asyncio
async def test_finalize_intake_promotes_to_final_and_records_lifecycle(
    tmp_path, v2_yaml, fake_ctx,
):
    config = _config_with_intakes(v2_yaml, intake_file_path=str(tmp_path))
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    await r._record_intake_answer(
        fake_ctx, case_type="example_intake", question_key="caller_full_name",
        spoken_text="Jane Doe", english_summary="Jane Doe",
    )
    await r._record_intake_answer(
        fake_ctx, case_type="example_intake", question_key="employer",
        spoken_text="ACME Co.", english_summary="ACME Co.",
    )

    result = await r._finalize_intake(
        fake_ctx,
        caller_name="Jane Doe",
        callback_number="+15551112222",
        english_overview="New client intake completed.",
    )
    assert "Intake submitted" in result
    assert "Example intake" in result

    # Final file written, partial removed
    finals = list(tmp_path.glob("intake_*.final.json"))
    partials = list(tmp_path.glob("*.partial.json"))
    assert len(finals) == 1
    assert partials == []

    data = json.loads(finals[0].read_text(encoding="utf-8"))
    assert data["status"] == "final"
    assert data["caller_name"] == "Jane Doe"
    assert data["callback_number"] == "+15551112222"
    assert data["english_overview"] == "New client intake completed."
    assert len(data["answers"]) == 2

    # Lifecycle outcome + email queued
    assert "intake_submitted" in lifecycle.metadata.outcomes
    assert lifecycle._pending_intake_submission is not None
    assert lifecycle._pending_intake_submission.status == "final"
    assert lifecycle._intake_case_type_display == "Example intake"


@pytest.mark.asyncio
async def test_finalize_intake_without_prior_answers_returns_error(
    tmp_path, v2_yaml, fake_ctx,
):
    config = _config_with_intakes(v2_yaml, intake_file_path=str(tmp_path))
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    result = await r._finalize_intake(
        fake_ctx, caller_name="Jane", callback_number="+1", english_overview="",
    )
    assert "No intake answers" in result
    assert "intake_submitted" not in lifecycle.metadata.outcomes


@pytest.mark.asyncio
async def test_record_intake_answer_truncates_overlong_text(
    tmp_path, v2_yaml, fake_ctx,
):
    config = _config_with_intakes(v2_yaml, intake_file_path=str(tmp_path))
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    r = _bare_receptionist(config, lifecycle)

    huge = "A" * 10000  # exceeds 4000 cap
    await r._record_intake_answer(
        fake_ctx, case_type="example_intake", question_key="caller_full_name",
        spoken_text=huge,
    )
    answer = r._intake_answers["caller_full_name"]
    assert len(answer.spoken_text) <= 4000


@pytest.mark.asyncio
async def test_await_keypad_entry_returns_captured_digits(v2_yaml, mocker):
    import asyncio
    from receptionist.agent import _DtmfHandlerState

    config = _config_with_dtmf_intake(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)
    state = _DtmfHandlerState(
        config=config, lifecycle=lifecycle, session=mocker.MagicMock(),
        sip_caller_identity="sip_caller",
        execute_transfer=mocker.AsyncMock(), speak_goodbye=mocker.AsyncMock(),
    )
    r = _keypad_receptionist(config, lifecycle, state)

    async def _drive():
        for _ in range(200):
            if state.capture is not None:
                break
            await asyncio.sleep(0.005)
        assert state.capture is not None
        for d in "5551234567":
            state.capture.buffer.add_key(d)
        state.capture.future.set_result(state.capture.buffer.digits)
        state.capture = None

    ctx = mocker.MagicMock()
    ctx.session.generate_reply = mocker.AsyncMock()
    driver = asyncio.create_task(_drive())
    result = await r._await_keypad_entry(ctx, question_key="cb")
    await driver
    assert "5551234567" in result


@pytest.mark.asyncio
async def test_await_keypad_entry_times_out_to_voice_fallback(v2_yaml, mocker):
    from receptionist.agent import _DtmfHandlerState
    import receptionist.agent as agent_module

    mocker.patch.object(agent_module, "_KEYPAD_ENTRY_TIMEOUT_SECONDS", 0.05)
    config = _config_with_dtmf_intake(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)
    state = _DtmfHandlerState(
        config=config, lifecycle=lifecycle, session=mocker.MagicMock(),
        sip_caller_identity="sip_caller",
        execute_transfer=mocker.AsyncMock(), speak_goodbye=mocker.AsyncMock(),
    )
    r = _keypad_receptionist(config, lifecycle, state)
    ctx = mocker.MagicMock()
    ctx.session.generate_reply = mocker.AsyncMock()
    result = await r._await_keypad_entry(ctx, question_key="cb")
    assert "say the number" in result.lower()
    assert state.capture is None  # disarmed on timeout


@pytest.mark.asyncio
async def test_await_keypad_entry_rejects_voice_question(v2_yaml, mocker):
    from receptionist.agent import _DtmfHandlerState
    config = _config_with_dtmf_intake(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)
    state = _DtmfHandlerState(
        config=config, lifecycle=lifecycle, session=mocker.MagicMock(),
        sip_caller_identity="sip_caller",
        execute_transfer=mocker.AsyncMock(), speak_goodbye=mocker.AsyncMock(),
    )
    r = _keypad_receptionist(config, lifecycle, state)
    ctx = mocker.MagicMock()
    ctx.session.generate_reply = mocker.AsyncMock()
    result = await r._await_keypad_entry(ctx, question_key="name")  # voice question
    assert "not a keypad" in result.lower() or "say" in result.lower()
    assert state.capture is None


@pytest.mark.asyncio
async def test_await_keypad_entry_without_handler_returns_fallback(v2_yaml, mocker):
    config = _config_with_dtmf_intake(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)
    r = _keypad_receptionist(config, lifecycle, None)  # no handler wired
    ctx = mocker.MagicMock()
    ctx.session.generate_reply = mocker.AsyncMock()
    result = await r._await_keypad_entry(ctx, question_key="cb")
    assert "say the number" in result.lower()


@pytest.mark.asyncio
async def test_await_keypad_entry_rearm_cancels_prior_call(v2_yaml, mocker):
    """A second await_keypad_entry call must unblock the first immediately
    (not hang 30s) and leave the SECOND call's capture armed."""
    import asyncio
    from receptionist.agent import _DtmfHandlerState

    config = _config_with_dtmf_intake(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r-1", caller_phone=None)
    state = _DtmfHandlerState(
        config=config, lifecycle=lifecycle, session=mocker.MagicMock(),
        sip_caller_identity="sip_caller",
        execute_transfer=mocker.AsyncMock(), speak_goodbye=mocker.AsyncMock(),
    )
    r = _keypad_receptionist(config, lifecycle, state)
    ctx = mocker.MagicMock()
    ctx.session.generate_reply = mocker.AsyncMock()

    # First call parks awaiting digits.
    first = asyncio.create_task(r._await_keypad_entry(ctx, question_key="cb"))
    for _ in range(200):
        if state.capture is not None:
            break
        await asyncio.sleep(0.005)
    first_capture = state.capture
    assert first_capture is not None

    # Second call re-arms; should cancel the first.
    second = asyncio.create_task(r._await_keypad_entry(ctx, question_key="cb"))
    for _ in range(200):
        if state.capture is not None and state.capture is not first_capture:
            break
        await asyncio.sleep(0.005)
    assert state.capture is not None and state.capture is not first_capture

    # First call returns promptly (a fallback), not hanging 30s.
    first_result = await asyncio.wait_for(first, timeout=2.0)
    assert isinstance(first_result, str)
    # Second call's capture is still live and armed.
    assert state.capture is not None

    # Drive the second to completion so we don't leak the task.
    for d in "5550001234":
        state.capture.buffer.add_key(d)
    state.capture.future.set_result(state.capture.buffer.digits)
    state.capture = None
    second_result = await asyncio.wait_for(second, timeout=2.0)
    assert "5550001234" in second_result
