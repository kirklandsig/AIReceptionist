# tests/messaging/test_file_channel.py
from __future__ import annotations

import json
import pytest
from pathlib import Path

from receptionist.messaging.models import Message, DispatchContext
from receptionist.messaging.channels.file import FileChannel
from receptionist.config import FileChannel as FileChannelConfig


@pytest.mark.asyncio
async def test_file_channel_writes_message(tmp_path):
    cfg = FileChannelConfig(type="file", file_path=str(tmp_path))
    channel = FileChannel(cfg)
    msg = Message(caller_name="Jane", callback_number="+15551112222",
                  message="Call me", business_name="Acme")
    await channel.deliver(msg, DispatchContext())

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["caller_name"] == "Jane"
    assert data["message"] == "Call me"


@pytest.mark.asyncio
async def test_file_channel_creates_missing_directory(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    cfg = FileChannelConfig(type="file", file_path=str(target))
    channel = FileChannel(cfg)
    msg = Message("X", "+1", "m", "B")
    await channel.deliver(msg, DispatchContext())

    assert target.exists()
    assert len(list(target.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_file_channel_filename_includes_timestamp(tmp_path):
    cfg = FileChannelConfig(type="file", file_path=str(tmp_path))
    channel = FileChannel(cfg)
    for i in range(3):
        msg = Message(f"C{i}", "+1", "m", "B")
        await channel.deliver(msg, DispatchContext())
    files = sorted(tmp_path.glob("*.json"))
    assert len(files) == 3
    for f in files:
        assert f.name.startswith("message_")
        assert f.name.endswith(".json")
