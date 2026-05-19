from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from livekit import api

from receptionist.agent import Receptionist
from receptionist.config import SipConfig
from receptionist.lifecycle import CallLifecycle


class _Session:
    def __init__(self) -> None:
        self.generate_reply = AsyncMock()


class _Context:
    def __init__(self) -> None:
        self.session = _Session()


@pytest.fixture
def receptionist(v2_yaml, mocker):
    from receptionist.config import BusinessConfig

    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-x", caller_phone=None)
    r = Receptionist(config, lifecycle)
    job_ctx = SimpleNamespace(
        room=SimpleNamespace(name="room-x", remote_participants={
            "caller": SimpleNamespace(
                kind=api.RoomParticipantIdentity, identity="sip_15551112222",
            ),
        }),
        api=SimpleNamespace(
            sip=SimpleNamespace(transfer_sip_participant=AsyncMock()),
        ),
    )
    mocker.patch("receptionist.agent.get_job_context", return_value=job_ctx)
    mocker.patch("receptionist.agent._get_caller_identity", return_value="sip_15551112222")
    return r, lifecycle, job_ctx


@pytest.mark.asyncio
async def test_transfer_call_unknown_department_does_not_call_sip(receptionist):
    r, lifecycle, job_ctx = receptionist
    result = await r.transfer_call(_Context(), "No Such Dept")
    assert "not found" in result
    job_ctx.api.sip.transfer_sip_participant.assert_not_called()
    assert "transferred" not in lifecycle.metadata.outcomes


@pytest.mark.asyncio
async def test_transfer_call_success_records_transfer_and_uses_template(receptionist):
    r, lifecycle, job_ctx = receptionist
    r.config.sip = SipConfig(transfer_uri_template="sip:{number}")

    result = await r.transfer_call(_Context(), "Front Desk")

    assert result == "Call transferred to Front Desk"
    assert lifecycle.metadata.transfer_target == "Front Desk"
    assert "transferred" in lifecycle.metadata.outcomes
    req = job_ctx.api.sip.transfer_sip_participant.call_args.args[0]
    assert req.room_name == "room-x"
    assert req.participant_identity == "sip_15551112222"
    assert req.transfer_to == "sip:+15551234567"


@pytest.mark.asyncio
async def test_transfer_call_failure_does_not_record_transfer(receptionist):
    r, lifecycle, job_ctx = receptionist
    job_ctx.api.sip.transfer_sip_participant.side_effect = RuntimeError("sip down")

    result = await r.transfer_call(_Context(), "Front Desk")

    assert "wasn't able to transfer" in result
    assert "transferred" not in lifecycle.metadata.outcomes
