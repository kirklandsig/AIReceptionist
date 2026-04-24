# tests/recording/test_storage.py
from __future__ import annotations

from receptionist.config import (
    LocalStorageConfig, RecordingStorageConfig, S3StorageConfig,
)
from receptionist.recording.storage import resolve_destination


def test_resolve_local_destination(tmp_path):
    cfg = RecordingStorageConfig(type="local", local=LocalStorageConfig(path=str(tmp_path)))
    dest = resolve_destination(cfg, call_id="room-1")
    assert dest.kind == "local"
    assert dest.local_path is not None
    assert dest.local_path.parent == tmp_path
    assert dest.local_path.name.startswith("recording_")
    assert dest.local_path.suffix == ".mp4"
    assert dest.s3_bucket is None


def test_resolve_s3_destination():
    cfg = RecordingStorageConfig(
        type="s3",
        s3=S3StorageConfig(bucket="rec-bucket", region="us-east-1", prefix="acme/"),
    )
    dest = resolve_destination(cfg, call_id="room-1")
    assert dest.kind == "s3"
    assert dest.s3_bucket == "rec-bucket"
    assert dest.s3_key is not None
    assert dest.s3_key.startswith("acme/recording_")
    assert dest.s3_key.endswith(".mp4")
    assert dest.local_path is None


def test_resolve_s3_empty_prefix():
    cfg = RecordingStorageConfig(
        type="s3",
        s3=S3StorageConfig(bucket="rec-bucket", region="us-east-1", prefix=""),
    )
    dest = resolve_destination(cfg, call_id="room-1")
    assert dest.s3_key is not None
    assert not dest.s3_key.startswith("/")


def test_resolve_s3_with_endpoint_url():
    cfg = RecordingStorageConfig(
        type="s3",
        s3=S3StorageConfig(
            bucket="rec", region="auto", prefix="p/",
            endpoint_url="https://r2.example.com",
        ),
    )
    dest = resolve_destination(cfg, call_id="room-1")
    assert dest.s3_endpoint_url == "https://r2.example.com"


def test_resolve_sanitizes_call_id(tmp_path):
    cfg = RecordingStorageConfig(type="local", local=LocalStorageConfig(path=str(tmp_path)))
    dest = resolve_destination(cfg, call_id="room/with\\bad:chars")
    assert "bad" in dest.local_path.name
    assert "/" not in dest.local_path.name
    assert "\\" not in dest.local_path.name
