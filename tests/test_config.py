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
def test_webhook_channel_warns_on_private_or_loopback_ip(host_in_url, caplog):
    """These pass validation (legitimate in dev) but log a warning so prod
    misconfigurations are visible at startup.
    """
    from receptionist.config import WebhookChannel
    url = f"http://{host_in_url}/hook"
    with caplog.at_level("WARNING", logger="receptionist"):
        cfg = WebhookChannel(type="webhook", url=url)
    assert cfg.url == url
    assert any("loopback/private/link-local" in r.message for r in caplog.records)


def test_webhook_channel_warns_on_localhost_hostname(caplog):
    from receptionist.config import WebhookChannel
    with caplog.at_level("WARNING", logger="receptionist"):
        WebhookChannel(type="webhook", url="http://localhost:9000/hook")
    assert any("localhost" in r.message.lower() for r in caplog.records)


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
