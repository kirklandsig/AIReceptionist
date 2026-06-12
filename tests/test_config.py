import pytest
from pathlib import Path
from pydantic import ValidationError
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


def test_example_workers_comp_config_loads_with_resend_env(monkeypatch):
    """Smoke test for the public workers' compensation law-firm template.

    Loads the tracked `example-workers-comp.yaml`, confirms the channels
    schema, recording, and transcripts are wired correctly, and asserts
    the example email address and env-var name are the generic
    placeholders rather than any real-firm identifier (regression guard
    against re-introducing client-specific values into the public template).
    """
    monkeypatch.setenv("EXAMPLE_RESEND_API_KEY", "test-resend-key")
    config = load_config(Path("config/businesses/example-workers-comp.yaml"))
    assert config.business.name == "Example Workers' Comp Law"
    assert config.greeting.startswith("Thank you for calling Example Workers' Comp Law")
    assert len(config.routing) == 15
    assert config.messages.channels[1].to == ["intake@example.com"]
    assert config.recording is not None
    assert config.recording.enabled is True
    assert config.recording.consent_preamble.enabled is False
    assert config.transcripts is not None
    assert config.transcripts.enabled is True
    # Generic-placeholder regression guard: no client domain in the template.
    raw_yaml = Path("config/businesses/example-workers-comp.yaml").read_text(
        encoding="utf-8",
    )
    assert "licomplaw" not in raw_yaml.lower()
    assert "nycomplaw" not in raw_yaml.lower()


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
    assert config.voice.model == "gpt-realtime"
    assert config.voice.auth is None


def test_agent_mode_defaults_to_receptionist(v2_yaml):
    config = BusinessConfig.from_yaml_string(v2_yaml)
    assert config.agent.mode == "receptionist"


def test_agent_mode_accepts_intake_only(v2_yaml):
    yaml_text = v2_yaml.replace(
        "business:", "agent:\n  mode: intake_only\n\nbusiness:", 1,
    )
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.agent.mode == "intake_only"


def test_info_packets_requires_email_when_enabled(v2_yaml):
    yaml_text = v2_yaml + '''
info_packets:
  enabled: true
  packets:
    - key: firm_overview
      display_name: "Firm Overview"
      email_subject: "Information from Example Law"
      email_body: "Thank you for completing an intake."
'''
    with pytest.raises(ValidationError, match="info_packets.*email"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_info_packets_accepts_configured_email_packet(v2_yaml):
    yaml_text = v2_yaml + '''
email:
  from: "AI Receptionist <ai@example.com>"
  sender:
    type: "smtp"
    smtp:
      host: "smtp.example.com"
      port: 587
      username: "user"
      password: "pass"
      use_tls: true
info_packets:
  enabled: true
  default_packet: firm_overview
  packets:
    - key: firm_overview
      display_name: "Firm Overview"
      email_subject: "Information from Example Law"
      email_body: "Thank you for completing an intake."
      links:
        - label: "Website"
          url: "https://example.com"
'''
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.info_packets.enabled is True
    assert config.info_packets.default_packet == "firm_overview"
    assert config.info_packets.packets[0].links[0].url == "https://example.com"


def test_info_packets_rejects_bad_keys_and_links(v2_yaml):
    yaml_text = v2_yaml + '''
email:
  from: "AI Receptionist <ai@example.com>"
  sender:
    type: "smtp"
    smtp:
      host: "smtp.example.com"
      port: 587
      username: "user"
      password: "pass"
      use_tls: true
info_packets:
  enabled: true
  packets:
    - key: "../secret"
      display_name: "Firm Overview"
      email_subject: "Information from Example Law"
      email_body: "Thank you for completing an intake."
      links:
        - label: "Bad"
          url: "file:///secret.pdf"
'''
    with pytest.raises(ValidationError):
        BusinessConfig.from_yaml_string(yaml_text)


def _v2_yaml_with_voice_auth(v2_yaml: str, auth_block: str) -> str:
    return v2_yaml.replace(
        '  model: "gpt-realtime"',
        f'  model: "gpt-realtime"\n  auth:\n{auth_block}',
    )


def test_voice_auth_api_key_defaults_to_openai_env(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(v2_yaml, '    type: "api_key"')
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.voice.auth.type == "api_key"
    assert config.voice.auth.env == "OPENAI_API_KEY"


def test_voice_auth_api_key_custom_env(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(v2_yaml, '    type: "api_key"\n    env: "ACME_OPENAI_KEY"')
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.voice.auth.type == "api_key"
    assert config.voice.auth.env == "ACME_OPENAI_KEY"


def test_voice_auth_oauth_codex_defaults_to_codex_path(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(v2_yaml, '    type: "oauth_codex"')
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.voice.auth.type == "oauth_codex"
    assert config.voice.auth.path == "~/.codex/auth.json"


def test_voice_auth_oauth_codex_custom_path(v2_yaml, tmp_path):
    auth_path = tmp_path / "auth.json"
    yaml_text = _v2_yaml_with_voice_auth(
        v2_yaml,
        f'    type: "oauth_codex"\n    path: "{_yaml_safe(auth_path)}"',
    )
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.voice.auth.type == "oauth_codex"
    assert config.voice.auth.path == _yaml_safe(auth_path)


def test_voice_auth_oauth_static_with_inline_token(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(v2_yaml, '    type: "oauth_static"\n    token: "bearer-token"')
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.voice.auth.type == "oauth_static"
    assert config.voice.auth.token == "bearer-token"
    assert config.voice.auth.token_env is None


def test_voice_auth_oauth_static_with_token_env(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(v2_yaml, '    type: "oauth_static"\n    token_env: "OPENAI_OAUTH_TOKEN"')
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.voice.auth.type == "oauth_static"
    assert config.voice.auth.token is None
    assert config.voice.auth.token_env == "OPENAI_OAUTH_TOKEN"


def test_voice_auth_oauth_static_requires_one_token_source(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(v2_yaml, '    type: "oauth_static"')
    with pytest.raises(Exception, match="exactly one"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_voice_auth_oauth_static_rejects_two_token_sources(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(
        v2_yaml,
        '    type: "oauth_static"\n    token: "x"\n    token_env: "OPENAI_OAUTH_TOKEN"',
    )
    with pytest.raises(Exception, match="exactly one"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_voice_auth_unknown_type_rejected(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(v2_yaml, '    type: "magic"')
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(yaml_text)


def test_voice_auth_extra_fields_rejected(v2_yaml):
    yaml_text = _v2_yaml_with_voice_auth(
        v2_yaml,
        '    type: "oauth_codex"\n    path: "~/.codex/auth.json"\n    token_env: "NOPE"',
    )
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(yaml_text)


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


def test_env_var_lowercase_placeholder_raises():
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
      headers: { X-Api-Key: "${test_webhook_token}" }
"""
    with pytest.raises(Exception, match="Invalid environment variable placeholder"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_literal_dollar_brace_in_text_is_not_rejected():
    """A literal '${' in caller-facing text that does NOT look like an env-var
    placeholder must not be rejected. This avoids false positives where a
    greeting or FAQ answer happens to mention `${...}` text."""
    yaml_text = """
business: { name: "X", type: "x", timezone: "UTC" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Use placeholders like {name} not $ { lookup } in messages."
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
"""
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert "{name}" in config.personality


def test_invalid_timezone_rejected_at_config_load():
    yaml_text = EXAMPLE_YAML.replace("America/New_York", "America/New_Yrok")
    with pytest.raises(Exception, match="Invalid IANA timezone"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_top_level_extra_fields_rejected(v2_yaml):
    yaml_text = v2_yaml + "\nunknown_section: true\n"
    with pytest.raises(Exception):
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


# ---- calendar config tests ----


def _calendar_yaml_fragment(auth_block: str) -> str:
    """Returns a full v2 YAML with calendar enabled and the given auth block."""
    return f"""
business: {{ name: "X", type: "x", timezone: "America/New_York" }}
voice: {{ voice_id: "marin" }}
languages: {{ primary: "en", allowed: ["en"] }}
greeting: "Hi"
personality: "Nice"
hours: {{ monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }}
after_hours_message: "Closed"
routing: []
faqs: []
messages: {{ channels: [{{type: "file", file_path: "./m/"}}] }}
calendar:
  enabled: true
  calendar_id: "primary"
  {auth_block}
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
"""


def _yaml_safe(p) -> str:
    """Convert a Path/str to a YAML-double-quote-safe form (forward slashes)."""
    return str(p).replace("\\", "/")


def test_calendar_service_account_auth_requires_file(tmp_path):
    """calendar.enabled=True + service_account auth: file must exist."""
    nonexistent = tmp_path / "sa.json"
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"service_account\", service_account_file: \"{_yaml_safe(nonexistent)}\" }}"
    )
    with pytest.raises(Exception, match="calendar auth file not found"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_calendar_service_account_auth_with_existing_file(tmp_path):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text('{"dummy": "content"}', encoding="utf-8")
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"service_account\", service_account_file: \"{_yaml_safe(sa_file)}\" }}"
    )
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.calendar.enabled is True
    assert config.calendar.auth.type == "service_account"
    assert config.calendar.auth.service_account_file == _yaml_safe(sa_file)
    assert config.calendar.buffer_placement == "after"


def test_calendar_oauth_auth_with_existing_file(tmp_path):
    token_file = tmp_path / "oauth.json"
    token_file.write_text('{"token": "x"}', encoding="utf-8")
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"oauth\", oauth_token_file: \"{_yaml_safe(token_file)}\" }}"
    )
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.calendar.auth.type == "oauth"


def test_calendar_extra_fields_rejected(tmp_path):
    """ConfigDict(extra=forbid) on auth variants: extra fields cause ValidationError."""
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"service_account\", "
        f"service_account_file: \"{_yaml_safe(sa_file)}\", "
        f"oauth_token_file: \"/fake/path\" }}"
    )
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(yaml_text)


def test_calendar_disabled_skips_file_check():
    """If calendar.enabled is False, auth file existence is not checked."""
    yaml_text = """
business: { name: "X", type: "x", timezone: "America/New_York" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Hi"
personality: "Nice"
hours: { monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }
after_hours_message: "Closed"
routing: []
faqs: []
messages: { channels: [{type: "file", file_path: "./m/"}] }
calendar:
  enabled: false
  auth:
    type: "service_account"
    service_account_file: "/does/not/exist/sa.json"
"""
    config = BusinessConfig.from_yaml_string(yaml_text)
    assert config.calendar.enabled is False


def test_on_booking_trigger_requires_calendar_enabled(tmp_path):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")
    yaml_text = f"""
business: {{ name: "X", type: "x", timezone: "America/New_York" }}
voice: {{ voice_id: "marin" }}
languages: {{ primary: "en", allowed: ["en"] }}
greeting: "Hi"
personality: "Nice"
hours: {{ monday: closed, tuesday: closed, wednesday: closed, thursday: closed, friday: closed, saturday: closed, sunday: closed }}
after_hours_message: "Closed"
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./m/"
    - type: "email"
      to: ["a@b.c"]
email:
  from: "noreply@example.com"
  sender:
    type: "smtp"
    smtp: {{ host: "h", port: 587, username: "u", password: "p", use_tls: true }}
  triggers:
    on_booking: true
# NO calendar section — validation should fail
"""
    with pytest.raises(Exception, match="on_booking"):
        BusinessConfig.from_yaml_string(yaml_text)


def test_buffer_placement_validator_accepts_valid():
    from receptionist.config import CalendarConfig, ServiceAccountAuth
    cfg = CalendarConfig(
        enabled=False,
        calendar_id="primary",
        auth=ServiceAccountAuth(type="service_account", service_account_file="/tmp/sa.json"),
        buffer_placement="both",
    )
    assert cfg.buffer_placement == "both"


# ---- SIP transfer URI tests (issue #6) ----

def test_sip_transfer_uri_default_is_tel():
    """Default keeps existing behavior — tel:{number} for Twilio/Telnyx/most BYOC."""
    from receptionist.config import SipConfig
    cfg = SipConfig()
    assert cfg.transfer_uri_template == "tel:{number}"
    assert cfg.transfer_uri_template.format(number="+15551234567") == "tel:+15551234567"


def test_sip_transfer_uri_accepts_sip_scheme_for_asterisk():
    """Asterisk classic sip.conf rejects tel-URIs; sip:{number} is the workaround."""
    from receptionist.config import SipConfig
    cfg = SipConfig(transfer_uri_template="sip:{number}")
    assert cfg.transfer_uri_template.format(number="2001") == "sip:2001"


def test_sip_transfer_uri_accepts_full_uri_with_host():
    """Full sip:user@host form for transfers to a remote SIP PBX."""
    from receptionist.config import SipConfig
    cfg = SipConfig(transfer_uri_template="sip:{number}@asterisk.local")
    assert cfg.transfer_uri_template.format(number="2001") == "sip:2001@asterisk.local"


def test_sip_transfer_uri_rejects_template_without_number_placeholder():
    """Misconfigured template without {number} would silently dial the literal string."""
    from receptionist.config import SipConfig
    with pytest.raises(ValidationError, match="number.*placeholder"):
        SipConfig(transfer_uri_template="tel:5551234567")  # forgot {number}


def test_sip_transfer_uri_rejects_extra_fields():
    """Extra fields in the sip section should fail loudly so typos don't pass silently."""
    from receptionist.config import SipConfig
    with pytest.raises(ValidationError):
        SipConfig(transfer_uri_template="tel:{number}", garbage="field")


def test_webhook_channel_rejects_file_scheme():
    """Hard reject anything that's not http or https."""
    from receptionist.config import WebhookChannel
    with pytest.raises(ValidationError, match="scheme must be http"):
        WebhookChannel(type="webhook", url="file:///etc/passwd")


@pytest.mark.parametrize("scheme", ["data", "javascript", "gopher", "ftp"])
def test_webhook_channel_rejects_dangerous_schemes(scheme):
    from receptionist.config import WebhookChannel
    url = f"{scheme}://example.com/x"
    with pytest.raises(ValidationError, match="scheme must be http"):
        WebhookChannel(type="webhook", url=url)


def test_webhook_channel_rejects_url_without_host():
    from receptionist.config import WebhookChannel
    with pytest.raises(ValidationError, match="no host"):
        WebhookChannel(type="webhook", url="http://")


@pytest.mark.parametrize("host_in_url", [
    "127.0.0.1",
    "10.0.0.5",
    "192.168.1.1",
    "169.254.169.254",  # AWS metadata service
    "[::1]",  # IPv6 loopback (URL-form requires brackets)
])
def test_webhook_channel_rejects_private_or_loopback_ip(host_in_url):
    from receptionist.config import WebhookChannel
    url = f"http://{host_in_url}/hook"
    with pytest.raises(ValidationError, match="private|loopback|link-local"):
        WebhookChannel(type="webhook", url=url)


def test_webhook_channel_rejects_localhost_hostname():
    from receptionist.config import WebhookChannel
    with pytest.raises(ValidationError, match="localhost"):
        WebhookChannel(type="webhook", url="http://localhost:9000/hook")


def test_calendar_booking_window_days_has_upper_bound(tmp_path):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")
    yaml_text = _calendar_yaml_fragment(
        f"auth: {{ type: \"service_account\", service_account_file: \"{_yaml_safe(sa_file)}\" }}"
    ).replace("booking_window_days: 30", "booking_window_days: 365")
    with pytest.raises(Exception):
        BusinessConfig.from_yaml_string(yaml_text)


def test_webhook_channel_quiet_on_public_host(caplog):
    """Real public webhooks should not log warnings."""
    from receptionist.config import WebhookChannel
    with caplog.at_level("WARNING", logger="receptionist"):
        WebhookChannel(type="webhook", url="https://hooks.slack.com/services/xyz")
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == []


def test_business_config_default_sip_when_omitted():
    """Backwards compat: configs without a `sip:` section get the default tel: template."""
    from receptionist.config import BusinessConfig
    yaml_text = """
business:
  name: "Test"
  type: "office"
  timezone: "America/New_York"
greeting: "Hi"
personality: "friendly"
hours:
  monday:    { open: "09:00", close: "17:00" }
  tuesday:   closed
  wednesday: closed
  thursday:  closed
  friday:    closed
  saturday:  closed
  sunday:    closed
after_hours_message: "We are closed."
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./messages/test/"
"""
    cfg = BusinessConfig.from_yaml_string(yaml_text)
    assert cfg.sip.transfer_uri_template == "tel:{number}"


# ---- ConfigError + friendly YAML error tests (issue #8) ----

# Minimal YAML that loads cleanly when the SECTION marker has correct indent.
# Used by the indent-trap tests below — they slot in different SECTION lines
# at column 0 (correct) or column 1 (the trap).
_BASE_YAML = """\
business:
  name: "Test"
  type: "office"
  timezone: "America/New_York"
voice:
  voice_id: "marin"
languages:
  primary: "en"
  allowed: ["en"]
greeting: "Hi"
personality: "Be nice."
hours:
  monday: closed
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "Closed."
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./m/"
{section}"""


@pytest.mark.parametrize("section_name,section_body", [
    ("sip", '  transfer_uri_template: "sip:{number}"'),
    ("retention", '  recordings_days: 0'),
])
def test_config_error_on_leading_space_indent_trap(section_name, section_body):
    """The exact issue #8 shape: user uncommented '# sip:' but left a
    leading space, getting ' sip:' at column 1. YAML reads that as
    nesting under messages, then fails. The friendly error must point
    the operator at the actual cause."""
    from receptionist.config import BusinessConfig, ConfigError
    bad_section = f" {section_name}:\n{section_body}\n"
    yaml_text = _BASE_YAML.format(section=bad_section)
    with pytest.raises(ConfigError) as excinfo:
        BusinessConfig.from_yaml_string(yaml_text)
    msg = str(excinfo.value)
    # Friendly explanation present
    assert "indentation" in msg.lower()
    assert section_name in msg
    assert "column 0" in msg
    # Original yaml error chained for debug context
    assert "Original yaml error:" in msg


def test_config_error_chains_underlying_yaml_error():
    """ConfigError is raised `from` the original YAMLError so debugging
    tools can still walk the cause chain."""
    import yaml
    from receptionist.config import BusinessConfig, ConfigError
    bad_yaml = _BASE_YAML.format(section=' sip:\n  transfer_uri_template: "x{number}"\n')
    with pytest.raises(ConfigError) as excinfo:
        BusinessConfig.from_yaml_string(bad_yaml)
    assert isinstance(excinfo.value.__cause__, yaml.YAMLError)


def test_config_error_correct_indent_loads_fine():
    """Sanity check: column-0 sip: still parses without complaint."""
    from receptionist.config import BusinessConfig
    yaml_text = _BASE_YAML.format(
        section='sip:\n  transfer_uri_template: "sip:{number}"\n'
    )
    cfg = BusinessConfig.from_yaml_string(yaml_text)
    assert cfg.sip.transfer_uri_template == "sip:{number}"


def test_config_error_falls_back_for_non_indent_yaml_errors():
    """Other YAML syntax errors (mismatched braces, bad mapping) should
    still produce a ConfigError but use the fallback message — we don't
    want to claim every error is an indent issue."""
    from receptionist.config import BusinessConfig, ConfigError
    # Tab character in indent is a YAML error but not the indent-trap shape
    bad = "business:\n\tname: oops\n"
    with pytest.raises(ConfigError) as excinfo:
        BusinessConfig.from_yaml_string(bad)
    msg = str(excinfo.value)
    # Generic fallback message, NOT the indent-trap-specific one
    assert "indentation error" not in msg
    assert "Config YAML" in msg


def test_config_error_handles_yaml_error_without_problem_mark():
    """Constructor-style YAML errors don't carry a problem_mark; helper
    must still produce *some* message rather than crashing."""
    import yaml
    from receptionist.config import _friendly_yaml_error
    e = yaml.YAMLError("synthetic error with no mark")
    msg = _friendly_yaml_error(e, "anything")
    assert "synthetic error" in msg


# ---------------------------------------------------------------------------
# DTMF config
# ---------------------------------------------------------------------------

def _v2_yaml_with_routing() -> str:
    # Minimal v2 YAML with a routing entry that DTMF transfer actions can
    # reference. Mirrors the shape used by other tests in this file.
    return """
business:
  name: "Acme"
  type: "test"
  timezone: "America/New_York"
voice:
  voice_id: marin
greeting: "Hello"
personality: "Be helpful."
hours:
  monday: {open: "09:00", close: "17:00"}
  tuesday: {open: "09:00", close: "17:00"}
  wednesday: {open: "09:00", close: "17:00"}
  thursday: {open: "09:00", close: "17:00"}
  friday: {open: "09:00", close: "17:00"}
  saturday: closed
  sunday: closed
after_hours_message: "Closed"
routing:
  - name: "Front Desk"
    number: "+15551110001"
    description: "general"
  - name: "Billing"
    number: "+15551110002"
    description: "billing"
faqs: []
messages:
  channels:
    - {type: "file", file_path: "messages/acme/"}
"""


def test_dtmf_defaults_to_disabled():
    cfg = BusinessConfig.from_yaml_string(_v2_yaml_with_routing())

    assert cfg.dtmf is None


def test_dtmf_config_accepts_minimal_enabled_block():
    yaml = _v2_yaml_with_routing() + """
dtmf:
  enabled: true
  digits:
    "1":
      action: transfer
      routing: "Front Desk"
      acknowledgment_en: "Transferring you to the front desk."
"""
    cfg = BusinessConfig.from_yaml_string(yaml)

    assert cfg.dtmf is not None
    assert cfg.dtmf.enabled is True
    assert "1" in cfg.dtmf.digits
    assert cfg.dtmf.digits["1"].action == "transfer"
    assert cfg.dtmf.digits["1"].routing == "Front Desk"


def test_dtmf_rejects_invalid_digit_key():
    yaml = _v2_yaml_with_routing() + """
dtmf:
  enabled: true
  digits:
    "10":
      action: end_call
      acknowledgment_en: "Goodbye."
"""
    with pytest.raises(ValidationError, match="invalid keys"):
        BusinessConfig.from_yaml_string(yaml)


def test_dtmf_rejects_invalid_action():
    yaml = _v2_yaml_with_routing() + """
dtmf:
  enabled: true
  digits:
    "1":
      action: launch_missiles
      acknowledgment_en: "Boom."
"""
    with pytest.raises(ValidationError, match="launch_missiles"):
        BusinessConfig.from_yaml_string(yaml)


def test_dtmf_transfer_action_requires_routing_to_exist():
    yaml = _v2_yaml_with_routing() + """
dtmf:
  enabled: true
  digits:
    "1":
      action: transfer
      routing: "Mystery Department"
      acknowledgment_en: "Transferring."
"""
    with pytest.raises(ValidationError) as exc:
        BusinessConfig.from_yaml_string(yaml)
    assert "Mystery Department" in str(exc.value)


def test_dtmf_transfer_action_requires_routing_field():
    """A transfer action with no `routing` field at all must be rejected by
    the BusinessConfig cross-field validator, distinct from the "routing
    value does not match a known entry" case covered above.
    """
    yaml = _v2_yaml_with_routing() + """
dtmf:
  enabled: true
  digits:
    "1":
      action: transfer
      acknowledgment_en: "Transferring."
"""
    with pytest.raises(ValidationError, match=r"no `routing`"):
        BusinessConfig.from_yaml_string(yaml)


def test_dtmf_repeat_menu_requires_menu_announcement_en():
    yaml = _v2_yaml_with_routing() + """
dtmf:
  enabled: true
  digits:
    "*":
      action: repeat_menu
      acknowledgment_en: "Here it is again."
"""
    with pytest.raises(ValidationError, match="menu_announcement_en"):
        BusinessConfig.from_yaml_string(yaml)


def test_dtmf_action_requires_acknowledgment_en():
    yaml = _v2_yaml_with_routing() + """
dtmf:
  enabled: true
  digits:
    "9":
      action: end_call
"""
    with pytest.raises(ValidationError, match="acknowledgment_en"):
        BusinessConfig.from_yaml_string(yaml)


def test_email_summary_defaults():
    from receptionist.config import EmailSummaryConfig
    s = EmailSummaryConfig()
    assert s.enabled is True
    assert s.model == "gpt-5-mini"
    assert s.reasoning_effort == "medium"
    assert s.api_key_env == "OPENAI_API_KEY"
    assert s.timeout_seconds == 20.0
    assert s.max_transcript_chars == 24000


def test_email_config_gets_default_summary_block():
    from receptionist.config import EmailConfig
    cfg = EmailConfig.model_validate({
        "from": "ai@example.com",
        "sender": {"type": "resend", "resend": {"api_key": "re_x"}},
    })
    assert cfg.summary.enabled is True
    assert cfg.summary.model == "gpt-5-mini"


def test_email_summary_rejects_bad_values():
    from receptionist.config import EmailSummaryConfig
    with pytest.raises(ValueError):
        EmailSummaryConfig(model="   ")
    with pytest.raises(ValueError):
        EmailSummaryConfig(timeout_seconds=0)
    with pytest.raises(ValueError):
        EmailSummaryConfig(max_transcript_chars=0)


def test_email_summary_parses_from_yaml_block():
    from receptionist.config import EmailConfig
    cfg = EmailConfig.model_validate({
        "from": "ai@example.com",
        "sender": {"type": "resend", "resend": {"api_key": "re_x"}},
        "summary": {"enabled": False, "model": "gpt-5.5", "reasoning_effort": None},
    })
    assert cfg.summary.enabled is False
    assert cfg.summary.model == "gpt-5.5"
    assert cfg.summary.reasoning_effort is None
