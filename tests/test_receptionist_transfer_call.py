from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from livekit import api

from receptionist.agent import Receptionist
from receptionist.config import SipConfig
from receptionist.lifecycle import CallLifecycle


def _fake_job_ctx():
    api_ns = SimpleNamespace(sip=SimpleNamespace(
        transfer_sip_participant=AsyncMock(return_value=None),
    ))
    room = SimpleNamespace(name="test-room")
    return SimpleNamespace(api=api_ns, room=room)


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


@pytest.mark.asyncio
async def test_execute_transfer_returns_transferred_on_success(v2_yaml, mocker):
    from receptionist.agent import Receptionist, TransferResult
    from receptionist.config import BusinessConfig
    from receptionist.lifecycle import CallLifecycle

    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = Receptionist(config, lifecycle)

    mocker.patch("receptionist.agent.get_job_context", return_value=_fake_job_ctx())
    mocker.patch(
        "receptionist.agent._get_caller_identity", return_value="sip_+15550001",
    )

    target = config.routing[0]
    result = await r._execute_transfer(target.name, source="dtmf")

    assert isinstance(result, TransferResult)
    assert result.status == "transferred"
    assert lifecycle.metadata.transfer_target == target.name


@pytest.mark.asyncio
async def test_execute_transfer_returns_intake_only_refused(v2_yaml):
    from receptionist.agent import Receptionist
    from receptionist.config import AgentConfig, BusinessConfig
    from receptionist.lifecycle import CallLifecycle

    config = BusinessConfig.from_yaml_string(v2_yaml).model_copy(
        update={"agent": AgentConfig(mode="intake_only")},
    )
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = Receptionist(config, lifecycle)

    target = config.routing[0]
    result = await r._execute_transfer(target.name, source="dtmf")

    assert result.status == "intake_only_refused"
    assert lifecycle.metadata.transfer_target is None


@pytest.mark.asyncio
async def test_execute_transfer_returns_sip_api_failed_when_api_raises(
    v2_yaml, mocker,
):
    from receptionist.agent import Receptionist
    from receptionist.config import BusinessConfig
    from receptionist.lifecycle import CallLifecycle

    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = Receptionist(config, lifecycle)

    fake_ctx = _fake_job_ctx()
    fake_ctx.api.sip.transfer_sip_participant = mocker.AsyncMock(
        side_effect=RuntimeError("boom"),
    )
    mocker.patch("receptionist.agent.get_job_context", return_value=fake_ctx)
    mocker.patch(
        "receptionist.agent._get_caller_identity", return_value="sip_+15550001",
    )

    target = config.routing[0]
    result = await r._execute_transfer(target.name, source="dtmf")

    assert result.status == "sip_api_failed"


@pytest.mark.asyncio
async def test_execute_transfer_returns_department_not_found(v2_yaml, mocker):
    from receptionist.agent import Receptionist, TransferResult
    from receptionist.config import BusinessConfig
    from receptionist.lifecycle import CallLifecycle

    config = BusinessConfig.from_yaml_string(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = Receptionist(config, lifecycle)

    transfer = mocker.AsyncMock()
    fake_ctx = _fake_job_ctx()
    fake_ctx.api.sip.transfer_sip_participant = transfer
    mocker.patch("receptionist.agent.get_job_context", return_value=fake_ctx)

    result = await r._execute_transfer("No Such Dept", source="dtmf")

    assert isinstance(result, TransferResult)
    assert result.status == "department_not_found"
    assert result.target_name is None
    transfer.assert_not_called()
    assert "transferred" not in lifecycle.metadata.outcomes
