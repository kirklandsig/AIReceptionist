# tests/transcript/test_writer.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from receptionist.config import TranscriptsConfig, TranscriptStorageConfig
from receptionist.transcript.capture import TranscriptSegment, SpeakerRole
from receptionist.transcript.metadata import CallMetadata
from receptionist.transcript.writer import write_transcript_files


def _cfg(path: str, formats: list[str] | None = None) -> TranscriptsConfig:
    return TranscriptsConfig(
        enabled=True,
        storage=TranscriptStorageConfig(type="local", path=path),
        formats=formats if formats is not None else ["json", "markdown"],
    )


@pytest.mark.asyncio
async def test_writer_writes_both_formats(tmp_path):
    cfg = _cfg(str(tmp_path))
    md = CallMetadata(call_id="room-1", business_name="Acme",
                      start_ts="2026-04-23T14:30:00+00:00")
    segs = [TranscriptSegment(SpeakerRole.ASSISTANT, "hi", 100.0)]

    result = await write_transcript_files(cfg, md, segs)

    assert result.json_path is not None
    assert result.markdown_path is not None
    assert result.json_path.suffix == ".json"
    assert result.markdown_path.suffix == ".md"
    assert result.json_path.exists()
    assert result.markdown_path.exists()

    data = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert data["metadata"]["call_id"] == "room-1"


@pytest.mark.asyncio
async def test_writer_respects_formats_list(tmp_path):
    cfg = _cfg(str(tmp_path), formats=["json"])
    md = CallMetadata(call_id="room-1", business_name="Acme")
    result = await write_transcript_files(cfg, md, [])

    assert result.json_path is not None
    assert result.markdown_path is None
    assert result.json_path.exists()


@pytest.mark.asyncio
async def test_writer_filename_includes_call_id(tmp_path):
    cfg = _cfg(str(tmp_path))
    md = CallMetadata(call_id="room-xyz", business_name="Acme")
    result = await write_transcript_files(cfg, md, [])
    assert "room-xyz" in result.json_path.name


@pytest.mark.asyncio
async def test_writer_json_failure_still_writes_markdown(tmp_path, mocker):
    """If JSON write fails, Markdown write still runs."""
    cfg = _cfg(str(tmp_path))
    md = CallMetadata(call_id="room-1", business_name="Acme")

    original_write_text = Path.write_text

    def fake_write_text(self, data, **kwargs):
        if self.suffix == ".json":
            raise OSError("disk full on json")
        return original_write_text(self, data, **kwargs)

    mocker.patch.object(Path, "write_text", fake_write_text)

    result = await write_transcript_files(cfg, md, [])
    assert result.json_path is None
    assert result.markdown_path is not None
    assert result.markdown_path.exists()
