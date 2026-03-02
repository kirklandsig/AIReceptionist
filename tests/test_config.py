import pytest
from pathlib import Path
from receptionist.config import BusinessConfig, load_config


EXAMPLE_YAML = """
business:
  name: "Test Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "coral"

greeting: "Thank you for calling Test Dental."

personality: "You are a friendly receptionist."

hours:
  monday: { open: "08:00", close: "17:00" }
  tuesday: { open: "08:00", close: "17:00" }
  wednesday: closed
  thursday: { open: "08:00", close: "17:00" }
  friday: { open: "08:00", close: "15:00" }
  saturday: closed
  sunday: closed

after_hours_message: "We are currently closed."

routing:
  - name: "Front Desk"
    number: "+15551234567"
    description: "General inquiries"

faqs:
  - question: "Where are you located?"
    answer: "123 Main Street."

messages:
  delivery: "file"
  file_path: "./messages/test-dental/"
"""


def test_load_config_from_yaml_string():
    config = BusinessConfig.from_yaml_string(EXAMPLE_YAML)
    assert config.business.name == "Test Dental"
    assert config.business.timezone == "America/New_York"
    assert config.voice.voice_id == "coral"
    assert config.greeting == "Thank you for calling Test Dental."
    assert len(config.routing) == 1
    assert config.routing[0].number == "+15551234567"
    assert len(config.faqs) == 1


def test_load_config_from_file(tmp_path):
    config_file = tmp_path / "test.yaml"
    config_file.write_text(EXAMPLE_YAML)
    config = load_config(config_file)
    assert config.business.name == "Test Dental"


def test_hours_closed_day():
    config = BusinessConfig.from_yaml_string(EXAMPLE_YAML)
    assert config.hours.wednesday is None


def test_hours_open_day():
    config = BusinessConfig.from_yaml_string(EXAMPLE_YAML)
    assert config.hours.monday is not None
    assert config.hours.monday.open == "08:00"
    assert config.hours.monday.close == "17:00"


def test_config_validation_missing_business_name():
    bad_yaml = """
business:
  type: "dental office"
  timezone: "America/New_York"
voice:
  voice_id: "coral"
greeting: "Hello"
personality: "Be nice"
hours:
  monday: closed
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  delivery: "file"
  file_path: "./messages/test/"
"""
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(bad_yaml)


def test_config_validation_invalid_delivery():
    bad_yaml = """
business:
  name: "Test"
  type: "test"
  timezone: "America/New_York"
voice:
  voice_id: "coral"
greeting: "Hello"
personality: "Be nice"
hours:
  monday: closed
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  delivery: "carrier_pigeon"
  file_path: "./messages/test/"
"""
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(bad_yaml)
