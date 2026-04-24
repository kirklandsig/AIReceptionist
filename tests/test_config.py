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


# ---- v2 schema tests ----

from receptionist.config import BusinessConfig


def test_v2_schema_loads(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    assert config.business.name == "Test Dental"
    assert config.voice.voice_id == "marin"
    assert config.voice.model == "gpt-realtime-1.5"


def test_languages_config(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    assert config.languages.primary == "en"
    assert config.languages.allowed == ["en", "es"]


def test_languages_primary_must_be_in_allowed():
    bad = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "fr", allowed: ["en", "es"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
"""
    with pytest.raises(Exception, match="primary"):
        BusinessConfig.from_yaml_string(bad)


def test_messages_channels_list(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    assert len(config.messages.channels) == 1
    assert config.messages.channels[0].type == "file"
    assert config.messages.channels[0].file_path == "./messages/test-dental/"


def test_multiple_channels():
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./m/"
    - type: "webhook"
      url: "https://example.com/hook"
      headers: { X-Api-Key: "secret" }
    - type: "email"
      to: ["admin@example.com"]
email:
  from: "noreply@example.com"
  sender:
    type: "smtp"
    smtp:
      host: "smtp.example.com"
      port: 587
      username: "u"
      password: "p"
      use_tls: true
"""
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert len(config.messages.channels) == 3
    assert [c.type for c in config.messages.channels] == ["file", "webhook", "email"]


def test_legacy_delivery_converts_to_channels(legacy_yaml):
    """Legacy `delivery: file` form auto-converts to channels: [{type: file, ...}]."""
    config = BusinessConfig.from_yaml_string(legacy_yaml)
    assert len(config.messages.channels) == 1
    assert config.messages.channels[0].type == "file"
    assert config.messages.channels[0].file_path == "./messages/legacy/"


def test_env_var_interpolation(monkeypatch):
    monkeypatch.setenv("TEST_WEBHOOK_TOKEN", "secret-abc")
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  channels:
    - type: "webhook"
      url: "https://example.com"
      headers: { X-Api-Key: "${TEST_WEBHOOK_TOKEN}" }
"""
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.messages.channels[0].headers["X-Api-Key"] == "secret-abc"


def test_env_var_missing_raises():
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  channels:
    - type: "webhook"
      url: "${DOES_NOT_EXIST_VAR_12345}"
"""
    with pytest.raises(Exception, match="DOES_NOT_EXIST_VAR_12345"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_recording_config():
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
recording:
  enabled: true
  storage:
    type: "local"
    local:
      path: "./rec/"
  consent_preamble:
    enabled: true
    text: "Recorded for quality."
"""
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.recording.enabled is True
    assert config.recording.storage.type == "local"
    assert config.recording.storage.local.path == "./rec/"
    assert config.recording.consent_preamble.enabled is True


def test_recording_storage_requires_matching_subconfig():
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
recording:
  enabled: true
  storage:
    type: "s3"
    # s3 block missing!
  consent_preamble: { enabled: false, text: "" }
"""
    with pytest.raises(Exception, match="s3"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_retention_defaults():
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
"""
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.retention.recordings_days == 90
    assert config.retention.transcripts_days == 90
    assert config.retention.messages_days == 0


def test_email_channel_requires_email_section():
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  channels:
    - type: "email"
      to: ["a@b.c"]
# missing email: section
"""
    with pytest.raises(Exception, match="email"):
        BusinessConfig.from_yaml_string(yaml_text)
