# tests/recording/test_egress.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from receptionist.config import (
    ConsentPreambleConfig, LocalStorageConfig, RecordingConfig,
    RecordingStorageConfig, S3StorageConfig,
)
from receptionist.recording.egress import (
    RecordingArtifact, RecordingHandle,
    start_recording, stop_recording,
)
from receptionist.recording.storage import RecordingDestination


def _local_config(tmp_path) -> RecordingConfig:
    return RecordingConfig(
        enabled=True,
        storage=RecordingStorageConfig(
            type="local", local=LocalStorageConfig(path=str(tmp_path)),
        ),
        consent_preamble=ConsentPreambleConfig(enabled=True, text="..."),
    )


def _s3_config() -> RecordingConfig:
    return RecordingConfig(
        enabled=True,
        storage=RecordingStorageConfig(
            type="s3",
            s3=S3StorageConfig(bucket="rec", region="us-east-1", prefix="acme/"),
        ),
        consent_preamble=ConsentPreambleConfig(enabled=True, text="..."),
    )


@pytest.mark.asyncio
async def test_start_recording_local_calls_livekit_api(mocker, tmp_path):
    fake_api = MagicMock()
    fake_api.egress = MagicMock()
    fake_api.egress.start_room_composite_egress = AsyncMock(
        return_value=MagicMock(egress_id="egress-123")
    )
    fake_api.aclose = AsyncMock()
    mocker.patch("receptionist.recording.egress.api.LiveKitAPI", return_value=fake_api)

    handle = await start_recording(
        room_name="room-1",
        config=_local_config(tmp_path),
        call_id="room-1",
    )
    assert isinstance(handle, RecordingHandle)
    assert handle.egress_id == "egress-123"
    assert handle.destination.kind == "local"

    fake_api.egress.start_room_composite_egress.assert_called_once()


@pytest.mark.asyncio
async def test_start_recording_s3(mocker):
    fake_api = MagicMock()
    fake_api.egress = MagicMock()
    fake_api.egress.start_room_composite_egress = AsyncMock(
        return_value=MagicMock(egress_id="egress-456")
    )
    fake_api.aclose = AsyncMock()
    mocker.patch("receptionist.recording.egress.api.LiveKitAPI", return_value=fake_api)

    handle = await start_recording(room_name="room-1", config=_s3_config(), call_id="room-1")

    assert handle.destination.kind == "s3"
    fake_api.egress.start_room_composite_egress.assert_called_once()


@pytest.mark.asyncio
async def test_start_recording_failure_returns_none(mocker, tmp_path):
    fake_api = MagicMock()
    fake_api.egress = MagicMock()
    fake_api.egress.start_room_composite_egress = AsyncMock(
        side_effect=RuntimeError("permissions"),
    )
    fake_api.aclose = AsyncMock()
    mocker.patch("receptionist.recording.egress.api.LiveKitAPI", return_value=fake_api)

    handle = await start_recording(room_name="room-1", config=_local_config(tmp_path), call_id="room-1")
    assert handle is None


@pytest.mark.asyncio
async def test_stop_recording_local(mocker, tmp_path):
    fake_api = MagicMock()
    fake_api.egress = MagicMock()
    fake_api.egress.stop_egress = AsyncMock(return_value=MagicMock(egress_id="egress-123"))
    fake_api.aclose = AsyncMock()
    mocker.patch("receptionist.recording.egress.api.LiveKitAPI", return_value=fake_api)

    handle = RecordingHandle(
        egress_id="egress-123",
        destination=RecordingDestination(kind="local", local_path=tmp_path / "r.mp4"),
    )
    artifact = await stop_recording(handle)
    assert isinstance(artifact, RecordingArtifact)
    assert artifact.egress_id == "egress-123"
    assert artifact.url == str(tmp_path / "r.mp4")


@pytest.mark.asyncio
async def test_stop_recording_s3_url_is_s3_uri(mocker):
    fake_api = MagicMock()
    fake_api.egress = MagicMock()
    fake_api.egress.stop_egress = AsyncMock()
    fake_api.aclose = AsyncMock()
    mocker.patch("receptionist.recording.egress.api.LiveKitAPI", return_value=fake_api)

    handle = RecordingHandle(
        egress_id="egress-456",
        destination=RecordingDestination(
            kind="s3", s3_bucket="rec", s3_key="acme/recording_x.mp4",
            s3_region="us-east-1",
        ),
    )
    artifact = await stop_recording(handle)
    assert artifact.url == "s3://rec/acme/recording_x.mp4"
