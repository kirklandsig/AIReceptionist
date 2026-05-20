# tests/intakes/test_config.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from receptionist.config import (
    IntakeQuestion, IntakeCaseType, IntakeSubmissionConfig, IntakesConfig,
)


def _q(key: str = "name", **kwargs) -> IntakeQuestion:
    return IntakeQuestion(
        key=key,
        prompt_en=kwargs.pop("prompt_en", f"Please state your {key}."),
        prompt_es=kwargs.pop("prompt_es", None),
        required=kwargs.pop("required", True),
        validation=kwargs.pop("validation", "text"),
        critical=kwargs.pop("critical", False),
    )


def test_intake_question_defaults():
    q = _q()
    assert q.required is True
    assert q.validation == "text"
    assert q.critical is False
    assert q.prompt_es is None


def test_intake_question_rejects_extra_fields():
    with pytest.raises(ValidationError):
        IntakeQuestion(
            key="x", prompt_en="?", garbage="value",  # type: ignore[arg-type]
        )


def test_intake_case_type_requires_at_least_one_question():
    with pytest.raises(ValidationError, match="at least one question"):
        IntakeCaseType(key="x", display_name="X", questions=[])


def test_intake_case_type_rejects_duplicate_question_keys():
    with pytest.raises(ValidationError, match="duplicate intake question key"):
        IntakeCaseType(
            key="x", display_name="X",
            questions=[_q("name"), _q("name")],
        )


def test_intakes_config_requires_at_least_one_case_type():
    with pytest.raises(ValidationError, match="at least one case type"):
        IntakesConfig(
            submission=IntakeSubmissionConfig(file_path="./messages/x/intakes/"),
            case_types=[],
        )


def test_intakes_config_rejects_duplicate_case_type_keys():
    ct1 = IntakeCaseType(key="wc", display_name="WC", questions=[_q("name")])
    ct2 = IntakeCaseType(key="wc", display_name="Workers Comp", questions=[_q("name")])
    with pytest.raises(ValidationError, match="duplicate intake case type key"):
        IntakesConfig(
            submission=IntakeSubmissionConfig(file_path="./m/"),
            case_types=[ct1, ct2],
        )


def test_intakes_config_enabled_default_false():
    ct = IntakeCaseType(key="wc", display_name="WC", questions=[_q("name")])
    cfg = IntakesConfig(
        submission=IntakeSubmissionConfig(file_path="./m/"),
        case_types=[ct],
    )
    assert cfg.enabled is False
    assert cfg.preamble_en == ""
    assert cfg.preamble_es is None


def test_intakes_loads_from_business_yaml(v2_yaml):
    """A complete BusinessConfig accepts an intakes block."""
    from receptionist.config import BusinessConfig

    yaml_text = v2_yaml + """
intakes:
  enabled: true
  preamble_en: "This takes 15-20 minutes."
  preamble_es: "Esto toma 15-20 minutos."
  submission:
    file_path: "./messages/test/intakes/"
  case_types:
    - key: example_intake
      display_name: "Example intake"
      display_name_es: "Entrevista de ejemplo"
      questions:
        - key: caller_full_name
          prompt_en: "Full legal name?"
          prompt_es: "¿Nombre legal completo?"
          required: true
          critical: true
          validation: text
        - key: phone_again
          prompt_en: "Confirm callback number?"
          prompt_es: "¿Confirmar número de devolución?"
          required: true
          critical: true
          validation: phone
"""
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.intakes is not None
    assert config.intakes.enabled is True
    assert config.intakes.preamble_en.startswith("This takes")
    assert len(config.intakes.case_types) == 1
    ct = config.intakes.case_types[0]
    assert ct.key == "example_intake"
    assert ct.display_name == "Example intake"
    assert len(ct.questions) == 2
    assert ct.questions[0].critical is True
