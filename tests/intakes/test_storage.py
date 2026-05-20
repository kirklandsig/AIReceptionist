# tests/intakes/test_storage.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from receptionist.intakes.models import IntakeAnswer, IntakeSubmission
from receptionist.intakes.storage import persist_partial, persist_final


def _answer(key: str, text: str = "answer text") -> IntakeAnswer:
    return IntakeAnswer(
        question_key=key,
        prompt=f"Question for {key}",
        spoken_text=text,
        language="en",
        english_summary=text,
    )


def _submission(call_id: str = "room-abc", status: str = "partial") -> IntakeSubmission:
    return IntakeSubmission(
        case_type="example",
        business_name="Acme",
        call_id=call_id,
        caller_name="Jane",
        callback_number="+15551112222",
        answers=[_answer("name", "Jane"), _answer("dob", "1990-01-01")],
        language="en",
        english_overview="Test intake",
        status=status,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_persist_partial_writes_file(tmp_path):
    sub = _submission()
    path = await persist_partial(sub, tmp_path)
    assert path.exists()
    assert path.name == "intake_room-abc.partial.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "partial"
    assert data["case_type"] == "example"
    assert len(data["answers"]) == 2


@pytest.mark.asyncio
async def test_persist_partial_overwrites_atomically(tmp_path):
    sub1 = _submission()
    path1 = await persist_partial(sub1, tmp_path)
    sub2 = IntakeSubmission(
        case_type="example",
        business_name="Acme",
        call_id="room-abc",
        caller_name="Jane",
        callback_number="+15551112222",
        answers=[_answer("name", "Jane"), _answer("dob", "1990-01-01"), _answer("employer", "ACME Co")],
        language="en",
    )
    path2 = await persist_partial(sub2, tmp_path)
    assert path1 == path2
    data = json.loads(path2.read_text(encoding="utf-8"))
    assert len(data["answers"]) == 3
    # No leftover tmp files
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


@pytest.mark.asyncio
async def test_persist_final_promotes_and_removes_partial(tmp_path):
    partial = await persist_partial(_submission(), tmp_path)
    assert partial.exists()

    final_sub = _submission(status="final")
    final_path = await persist_final(final_sub, tmp_path)

    assert final_path.exists()
    assert "final.json" in final_path.name
    assert not partial.exists(), "partial file should be removed after finalization"

    data = json.loads(final_path.read_text(encoding="utf-8"))
    assert data["status"] == "final"


@pytest.mark.asyncio
async def test_persist_final_refuses_non_final_status(tmp_path):
    sub = _submission(status="partial")
    with pytest.raises(ValueError, match="non-final"):
        await persist_final(sub, tmp_path)


@pytest.mark.asyncio
async def test_persist_partial_creates_directory(tmp_path):
    target_dir = tmp_path / "nested" / "intakes"
    assert not target_dir.exists()
    path = await persist_partial(_submission(), target_dir)
    assert path.parent == target_dir
    assert target_dir.exists()


@pytest.mark.asyncio
async def test_persist_handles_call_id_with_unsafe_characters(tmp_path):
    sub = _submission(call_id="room/abc with spaces!")
    path = await persist_partial(sub, tmp_path)
    # Filename must be safe regardless of input
    assert "/" not in path.name
    assert " " not in path.name
    assert "!" not in path.name
    assert path.exists()
