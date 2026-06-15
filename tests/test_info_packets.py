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

    obj = SimpleNamespace(
        config=config,
        lifecycle=lifecycle,
        _pending_packet_destination=None,
    )
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
    # transfer_call now delegates to _execute_transfer (shared with the DTMF
    # path), so the bare object needs it bound too.
    obj._execute_transfer = Receptionist._execute_transfer.__get__(obj)
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
    # First call: tool hands back the address for read-back, no send yet.
    first = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=True,
    )
    assert "claimant@example.com" in first
    send_mock.assert_not_called()
    # Second call with destination_confirmed: the send happens.
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert "sent" in result.lower()
    send_mock.assert_awaited_once()
    assert lifecycle.metadata.info_packet_sends[0].status == "sent"


@pytest.mark.asyncio
async def test_send_info_packet_second_call_sends_without_re_passing_consent(
    v2_yaml, mocker,
):
    """Production regression: the model gives consent on the FIRST call, then
    on the confirming SECOND call it passes only destination_confirmed=true
    (the read-back instruction never tells it to re-pass consent_confirmed).
    A matching confirmed destination must complete the send — consent was
    already established on the first call. Previously the consent gate ran
    first and refused the second call, so no packet was ever sent."""
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    # First call WITH consent → read-back, no send.
    first = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=True,
    )
    assert "claimant@example.com" in first
    send_mock.assert_not_called()
    # Second call: destination_confirmed only, consent_confirmed omitted
    # (defaults False) — exactly what the live model did.
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        destination_confirmed=True,
    )
    assert "sent" in result.lower()
    send_mock.assert_awaited_once()
    assert lifecycle.metadata.info_packet_sends[0].status == "sent"


@pytest.mark.asyncio
async def test_send_info_packet_confirmed_without_prior_consent_call_refuses(
    v2_yaml, mocker,
):
    """A confirmed destination is only honored if a prior consent call armed
    the pending destination. destination_confirmed=true on a FRESH tool with
    no prior consented read-back must NOT send — it falls back to asking for
    consent. (Prevents the confirm flag alone from bypassing consent.)"""
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        destination_confirmed=True,  # but no prior consent call
    )
    send_mock.assert_not_called()
    assert "permission" in result.lower() or "consent" in result.lower()


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
    send_mock = mocker.patch(
        "receptionist.agent.send_info_packet_email",
        AsyncMock(side_effect=RuntimeError("smtp failed")),
    )
    first = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=True,
    )
    assert "claimant@example.com" in first
    send_mock.assert_not_called()
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="claimant@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert "trouble" in result.lower() or "follow up" in result.lower()
    record = lifecycle.metadata.info_packet_sends[0]
    assert record.status == "failed"
    assert record.error == "transport_failed"


@pytest.mark.asyncio
async def test_send_info_packet_first_call_returns_readback_and_does_not_send(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
    )
    assert "jane@example.com" in result
    send_mock.assert_not_called()
    assert r._pending_packet_destination == "jane@example.com"


@pytest.mark.asyncio
async def test_send_info_packet_confirmed_wrong_address_reprompts(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="a@example.com",
        consent_confirmed=True,
    )
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="b@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert "b@example.com" in result
    send_mock.assert_not_called()
    assert r._pending_packet_destination == "b@example.com"


@pytest.mark.asyncio
async def test_send_info_packet_confirmed_without_prior_call_reprompts(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert "jane@example.com" in result
    assert "read" in result.lower()
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_send_info_packet_match_is_case_insensitive(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="Jane@Example.com",
        consent_confirmed=True,
    )
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert "sent" in result.lower()
    send_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_info_packet_success_clears_pending(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch("receptionist.agent.send_info_packet_email", AsyncMock())
    await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
    )
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert "sent" in result.lower()
    assert r._pending_packet_destination is None
    # A stale confirmation must NOT trigger an accidental duplicate send.
    third = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert "jane@example.com" in third
    assert send_mock.call_count == 1


@pytest.mark.asyncio
async def test_send_info_packet_transport_failure_keeps_pending(v2_yaml, mocker):
    config = _config_with_packets(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="room-1", caller_phone=None)
    r = _bare_packet_receptionist(config, lifecycle)
    send_mock = mocker.patch(
        "receptionist.agent.send_info_packet_email",
        AsyncMock(side_effect=RuntimeError("smtp failed")),
    )
    await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
    )
    result = await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert "trouble" in result.lower() or "follow up" in result.lower()
    # Pending survives a transport failure so a retry with the same
    # confirmed address still attempts the send.
    assert r._pending_packet_destination == "jane@example.com"
    await r._send_info_packet(
        SimpleNamespace(),
        packet_key="firm_overview",
        channel="email",
        destination="jane@example.com",
        consent_confirmed=True,
        destination_confirmed=True,
    )
    assert send_mock.call_count == 2


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
