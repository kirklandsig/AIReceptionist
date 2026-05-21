from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from receptionist.config import EmailConfig, InfoPacket, InfoPacketLink
from receptionist.info_packets import is_valid_email_destination, send_info_packet_email
from receptionist.lifecycle import CallLifecycle


def _email_config() -> EmailConfig:
    return EmailConfig.model_validate({
        "from": "AI Receptionist <ai@example.com>",
        "sender": {
            "type": "smtp",
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password": "pass",
                "use_tls": True,
            },
        },
        "triggers": {"on_message": False, "on_call_end": False},
    })


def _packet() -> InfoPacket:
    return InfoPacket(
        key="firm_overview",
        display_name="Firm Overview",
        email_subject="Information from Example Law",
        email_body="Thank you for completing an intake.",
        links=[InfoPacketLink(label="Website", url="https://example.com")],
    )


def test_email_destination_validation():
    assert is_valid_email_destination("claimant@example.com") is True
    assert is_valid_email_destination("not an email") is False
    assert is_valid_email_destination("a@localhost") is False


@pytest.mark.asyncio
async def test_send_info_packet_email_uses_configured_sender(mocker):
    sender = AsyncMock()
    mocker.patch("receptionist.info_packets._build_sender", return_value=sender)
    await send_info_packet_email(
        packet=_packet(),
        email_config=_email_config(),
        destination="claimant@example.com",
        business_name="Example Law",
        call_id="room-1",
    )
    sender.send.assert_awaited_once()
    kwargs = sender.send.await_args.kwargs
    assert kwargs["to"] == ["claimant@example.com"]
    assert kwargs["subject"] == "Information from Example Law"


def _config_with_packets(v2_yaml: str):
    from receptionist.config import BusinessConfig, InfoPacketsConfig

    base = BusinessConfig.from_yaml_string(v2_yaml)
    return base.model_copy(update={
        "email": _email_config(),
        "info_packets": InfoPacketsConfig(
            enabled=True,
            default_packet="firm_overview",
            packets=[_packet()],
        ),
    })


def _bare_packet_receptionist(config, lifecycle):
    from receptionist.agent import Receptionist

    obj = SimpleNamespace(config=config, lifecycle=lifecycle)
    raw = Receptionist.send_info_packet
    raw = raw.fnc if hasattr(raw, "fnc") else raw
    obj._send_info_packet = raw.__get__(obj)
    return obj


def _bare_transfer_receptionist(config, lifecycle):
    from receptionist.agent import Receptionist

    obj = SimpleNamespace(
        config=config,
        lifecycle=lifecycle,
        _routing_by_name={r.name.lower(): r for r in config.routing},
    )
    raw = Receptionist.transfer_call
    raw = raw.fnc if hasattr(raw, "fnc") else raw
    obj._transfer_call = raw.__get__(obj)
    return obj


def _config_with_intakes_and_packets(v2_yaml: str, *, intake_file_path: str):
    from receptionist.config import (
        BusinessConfig,
        InfoPacketsConfig,
        IntakeCaseType,
        IntakeQuestion,
        IntakesConfig,
        IntakeSubmissionConfig,
    )

    base = BusinessConfig.from_yaml_string(v2_yaml)
    return base.model_copy(update={
        "email": _email_config(),
        "info_packets": InfoPacketsConfig(
            enabled=True,
            default_packet="firm_overview",
            packets=[_packet()],
        ),
        "intakes": IntakesConfig(
            enabled=True,
            preamble_en="This takes 30 minutes.",
            submission=IntakeSubmissionConfig(file_path=intake_file_path),
            case_types=[
                IntakeCaseType(
                    key="example_intake",
                    display_name="Example intake",
                    questions=[
                        IntakeQuestion(
                            key="caller_full_name",
                            prompt_en="Full legal name?",
                            required=True,
                            critical=True,
                        ),
                    ],
                ),
            ],
        ),
    })


def _bare_intake_packet_receptionist(config, lifecycle):
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

    obj._record_intake_answer = _unwrap(
        Receptionist.record_intake_answer,
    ).__get__(obj)
    obj._finalize_intake = _unwrap(Receptionist.finalize_intake).__get__(obj)
    return obj


@pytest.mark.asyncio
async def test_send_info_packet_tool_sends_email_and_records_success(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=True,
    )
    assert "sent" in result.lower()
    send_mock.assert_awaited_once()
    assert lifecycle.metadata.info_packet_sends[0].status == "sent"


@pytest.mark.asyncio
async def test_transfer_call_refuses_in_intake_only_mode(v2_yaml):
    from receptionist.config import AgentConfig

    config = _config_with_packets(v2_yaml).model_copy(
        update={"agent": AgentConfig(mode="intake_only")},
    )
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_transfer_receptionist(config, lifecycle)
    result = await r._transfer_call(SimpleNamespace(), department="Any Attorney")
    assert "cannot transfer" in result.lower()
    assert "message" in result.lower()


@pytest.mark.asyncio
async def test_send_info_packet_tool_refuses_without_consent(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=False,
    )
    assert "permission" in result.lower() or "consent" in result.lower()
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_info_packet_tool_refuses_sms(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="sms",
        destination="+15551234567",
        consent_confirmed=True,
    )
    assert "email" in result.lower()
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_info_packet_tool_rejects_unknown_packet(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="missing",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=True,
    )
    assert "unknown" in result.lower()
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_info_packet_tool_rejects_invalid_destination(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="not an email",
        consent_confirmed=True,
    )
    assert "valid" in result.lower()
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_info_packet_tool_records_transport_failure(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    mocker.patch(
        "receptionist.agent.send_info_packet_email",
        AsyncMock(side_effect=RuntimeError("smtp failed")),
    )
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=True,
    )
    assert "trouble" in result.lower() or "follow up" in result.lower()
    record = lifecycle.metadata.info_packet_sends[0]
    assert record.status == "failed"
    assert record.error == "transport_failed"


@pytest.mark.asyncio
async def test_finalize_intake_nudges_packet_offer_when_enabled(tmp_path, v2_yaml):
    config = _config_with_intakes_and_packets(
        v2_yaml, intake_file_path=str(tmp_path),
    )
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_intake_packet_receptionist(config, lifecycle)

    await r._record_intake_answer(
        SimpleNamespace(),
        case_type="example_intake",
        question_key="caller_full_name",
        spoken_text="Jane Doe",
        english_summary="Jane Doe",
    )
    result = await r._finalize_intake(
        SimpleNamespace(),
        caller_name="Jane Doe",
        callback_number="+15551112222",
        english_overview="New client intake completed.",
    )
    assert "send_info_packet" in result
    assert "permission" in result.lower() or "consent" in result.lower()
    assert "email" in result.lower()
