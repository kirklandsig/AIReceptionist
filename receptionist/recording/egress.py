# receptionist/recording/egress.py
from __future__ import annotations

import logging
from dataclasses import dataclass

from livekit import api

from receptionist.config import RecordingConfig
from receptionist.recording.storage import RecordingDestination, resolve_destination

logger = logging.getLogger("receptionist")


@dataclass
class RecordingHandle:
    egress_id: str
    destination: RecordingDestination


@dataclass
class RecordingArtifact:
    egress_id: str
    url: str


async def start_recording(
    *, room_name: str, config: RecordingConfig, call_id: str
) -> RecordingHandle | None:
    """Start a LiveKit room composite egress.

    Returns a RecordingHandle on success, None on error (call continues
    without recording, caller marks metadata.recording_failed = True).
    """
    if not config.enabled:
        return None

    destination = resolve_destination(config.storage, call_id)

    req = _build_egress_request(room_name, config, destination)

    lk_api: api.LiveKitAPI | None = None
    try:
        lk_api = api.LiveKitAPI()
        info = await lk_api.egress.start_room_composite_egress(req)
        logger.info(
            "Recording started: egress_id=%s kind=%s",
            info.egress_id, destination.kind,
            extra={"call_id": call_id, "component": "recording.egress"},
        )
        return RecordingHandle(egress_id=info.egress_id, destination=destination)
    except Exception:
        logger.exception(
            "Recording start failed",
            extra={"call_id": call_id, "component": "recording.egress"},
        )
        return None
    finally:
        if lk_api is not None:
            try:
                await lk_api.aclose()
            except Exception:
                pass


async def stop_recording(handle: RecordingHandle) -> RecordingArtifact | None:
    """Stop the egress. Returns artifact URL based on destination kind.

    We treat the destination URL as authoritative whether or not the
    stop call succeeds — egress may complete async.
    """
    lk_api: api.LiveKitAPI | None = None
    try:
        lk_api = api.LiveKitAPI()
        await lk_api.egress.stop_egress(api.StopEgressRequest(egress_id=handle.egress_id))
    except Exception:
        logger.exception(
            "Recording stop failed; returning destination URL anyway",
            extra={"egress_id": handle.egress_id, "component": "recording.egress"},
        )
    finally:
        if lk_api is not None:
            try:
                await lk_api.aclose()
            except Exception:
                pass

    url = _artifact_url(handle.destination)
    if url is None:
        return None
    return RecordingArtifact(egress_id=handle.egress_id, url=url)


def _build_egress_request(
    room_name: str,
    config: RecordingConfig,
    destination: RecordingDestination,
) -> api.RoomCompositeEgressRequest:
    # Protobuf message fields cannot be assigned directly (e.g.
    # `file_output.s3 = ...` raises AttributeError). Pass S3Upload via
    # the EncodedFileOutput constructor kwarg instead.
    file_output_kwargs = {
        "file_type": api.EncodedFileType.MP4,
        "filepath": _egress_filepath(destination),
    }
    if destination.kind == "s3":
        file_output_kwargs["s3"] = api.S3Upload(
            access_key="",  # picked up from env AWS_ACCESS_KEY_ID
            secret="",      # picked up from env AWS_SECRET_ACCESS_KEY
            region=destination.s3_region or "",
            bucket=destination.s3_bucket or "",
            endpoint=destination.s3_endpoint_url or "",
        )

    file_output = api.EncodedFileOutput(**file_output_kwargs)

    return api.RoomCompositeEgressRequest(
        room_name=room_name,
        audio_only=True,
        file_outputs=[file_output],
    )


def _egress_filepath(destination: RecordingDestination) -> str:
    if destination.kind == "local":
        assert destination.local_path is not None
        return str(destination.local_path)
    if destination.kind == "s3":
        assert destination.s3_key is not None
        return destination.s3_key
    raise ValueError(f"Unknown destination kind: {destination.kind}")


def _artifact_url(destination: RecordingDestination) -> str | None:
    if destination.kind == "local":
        return str(destination.local_path) if destination.local_path else None
    if destination.kind == "s3":
        if destination.s3_bucket and destination.s3_key:
            return f"s3://{destination.s3_bucket}/{destination.s3_key}"
    return None
