# tests/intakes/test_lifecycle.py
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from receptionist.lifecycle import CallLifecycle
from receptionist.intakes.models import IntakeAnswer, IntakeSubmission


def _intakes_config_yaml() -> str:
    return """
intakes:
  enabled: true
  preamble_en: "This takes 15-20 minutes."
  submission:
    file_path: "./messages/test/intakes/"
  case_types:
    - key: example_intake
      display_name: "Example intake"
      questions:
        - key: caller_full_name
          prompt_en: "Full legal name?"
          required: true
          critical: true
"""


def _config_with_intakes_and_email(v2_yaml):
    from receptionist.config import BusinessConfig
    yaml_text = v2_yaml + _intakes_config_yaml() + """
email:
  from: "ai@example.com"
  sender:
    type: "smtp"
    smtp: { host: "h", port: 587, username: "u", password: "p", use_tls: true }
  triggers:
    on_message: false
    on_call_end: false
    on_booking: false
messages:
  channels:
    - type: "file"
      file_path: "./messages/test/"
    - type: "email"
      to: ["owner@acme.com"]
"""
    # The append above will leave the old messages block from v2_yaml; replace it.
    # Simpler: rebuild via model_copy on parsed config from v2_yaml.
    base = BusinessConfig.from_yaml_string(v2_yaml)
    # Now load with intakes-extended yaml
    from receptionist.config import (
        EmailChannel as EmailChannelConfig, EmailConfig, IntakesConfig,
        IntakeCaseType, IntakeQuestion, IntakeSubmissionConfig,
    )
    return base.model_copy(update={
        "messages": base.messages.model_copy(update={
            "channels": [
                *base.messages.channels,
                EmailChannelConfig(type="email", to=["owner@acme.com"]),
            ],
        }),
        "email": EmailConfig.model_validate({
            "from": "ai@example.com",
            "sender": {
                "type": "smtp",
                "smtp": {"host": "h", "port": 587, "username": "u", "password": "p", "use_tls": True},
            },
            "triggers": {"on_message": False, "on_call_end": False, "on_booking": False},
        }),
        "intakes": IntakesConfig(
            enabled=True,
            preamble_en="This takes 15-20 minutes.",
            submission=IntakeSubmissionConfig(file_path="./messages/test/intakes/"),
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


def _make_submission() -> IntakeSubmission:
    return IntakeSubmission(
        case_type="example_intake",
        business_name="Test Dental",
        call_id="room-1",
        caller_name="Jane",
        callback_number="+15551112222",
        answers=[
            IntakeAnswer(
                question_key="caller_full_name",
                prompt="Full legal name?",
                spoken_text="Jane Doe",
                language="en",
                english_summary="Jane Doe",
            ),
        ],
        language="en",
        english_overview="Test intake",
        status="final",
    )


def test_lifecycle_records_intake_outcome(v2_yaml):
    config = _config_with_intakes_and_email(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.record_intake_submitted()
    assert "intake_submitted" in lifecycle.metadata.outcomes


def test_lifecycle_enqueue_overwrites_previous_submission(v2_yaml):
    config = _config_with_intakes_and_email(v2_yaml)
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    s1 = _make_submission()
    s2 = _make_submission()
    s2.caller_name = "Jane Doe"
    lifecycle.enqueue_intake_submission(s1, case_type_display="Example")
    lifecycle.enqueue_intake_submission(s2, case_type_display="Example")
    assert lifecycle._pending_intake_submission is s2


@pytest.mark.asyncio
async def test_lifecycle_fires_intake_email_at_call_end(v2_yaml, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel

    config = _config_with_intakes_and_email(v2_yaml)
    deliver_intake_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_intake", deliver_intake_mock)

    lifecycle = CallLifecycle(
        config=config, call_id="room-1", caller_phone="+15551112222",
    )
    submission = _make_submission()
    lifecycle.enqueue_intake_submission(
        submission, case_type_display="Example intake",
    )

    await lifecycle.on_call_ended()

    deliver_intake_mock.assert_called_once()
    fired_sub, fired_ctx = deliver_intake_mock.call_args.args
    assert fired_sub is submission
    assert deliver_intake_mock.call_args.kwargs.get("case_type_display") == "Example intake"
    # Submission reference is cleared after dispatch
    assert lifecycle._pending_intake_submission is None


@pytest.mark.asyncio
async def test_lifecycle_intake_clears_even_without_email_config(v2_yaml, mocker):
    """If a business enables intakes but has no email config, the structured
    JSON is on disk and the pending submission should still be cleared so a
    re-entry into on_call_ended doesn't see stale state."""
    from receptionist.config import (
        BusinessConfig, IntakesConfig, IntakeCaseType, IntakeQuestion,
        IntakeSubmissionConfig,
    )
    base = BusinessConfig.from_yaml_string(v2_yaml)
    config = base.model_copy(update={
        "email": None,
        "intakes": IntakesConfig(
            enabled=True,
            submission=IntakeSubmissionConfig(file_path="./m/intakes/"),
            case_types=[
                IntakeCaseType(
                    key="example_intake",
                    display_name="Example intake",
                    questions=[IntakeQuestion(key="name", prompt_en="Name?")],
                ),
            ],
        ),
    })
    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    lifecycle.enqueue_intake_submission(_make_submission(), case_type_display="X")
    await lifecycle.on_call_ended()
    assert lifecycle._pending_intake_submission is None


@pytest.mark.asyncio
async def test_lifecycle_intake_email_not_fired_without_pending(v2_yaml, mocker):
    from receptionist.messaging.channels.email import EmailChannel as RuntimeEmailChannel

    config = _config_with_intakes_and_email(v2_yaml)
    deliver_intake_mock = AsyncMock()
    mocker.patch.object(RuntimeEmailChannel, "deliver_intake", deliver_intake_mock)

    lifecycle = CallLifecycle(config=config, call_id="r", caller_phone=None)
    await lifecycle.on_call_ended()
    deliver_intake_mock.assert_not_called()
