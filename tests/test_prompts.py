from receptionist.config import BusinessConfig
from receptionist.prompts import build_system_prompt


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
  - name: "Billing"
    number: "+15551234569"
    description: "Payment questions"
faqs:
  - question: "Where are you located?"
    answer: "123 Main Street."
  - question: "Do you accept insurance?"
    answer: "Yes, most plans."
messages:
  delivery: "file"
  file_path: "./messages/test/"
"""


def _make_config():
    return BusinessConfig.from_yaml_string(EXAMPLE_YAML)


def test_prompt_contains_business_name():
    prompt = build_system_prompt(_make_config())
    assert "Test Dental" in prompt


def test_prompt_contains_personality():
    prompt = build_system_prompt(_make_config())
    assert "friendly receptionist" in prompt


def test_prompt_contains_faq_content():
    prompt = build_system_prompt(_make_config())
    assert "Where are you located?" in prompt
    assert "123 Main Street." in prompt


def test_prompt_contains_routing_info():
    prompt = build_system_prompt(_make_config())
    assert "Front Desk" in prompt
    assert "Billing" in prompt


def test_prompt_contains_hours():
    prompt = build_system_prompt(_make_config())
    assert "Monday" in prompt
    assert "08:00" in prompt


def test_prompt_contains_after_hours_instructions():
    prompt = build_system_prompt(_make_config())
    assert "currently closed" in prompt


def test_prompt_contains_ending_calls_guidance():
    """Issue #10: the system prompt must teach the LLM when to call end_call
    and — equally important — when NOT to call it."""
    prompt = build_system_prompt(_make_config())
    assert "ENDING CALLS" in prompt
    assert "end_call" in prompt
    # Negative guard: don't end calls just because of silence
    assert "Do NOT call end_call" in prompt or "do NOT call end_call" in prompt
    # Negative guard: never as the first reply
    assert "first reply" in prompt or "greet them" in prompt


# ---- multi-language tests ----


V2_YAML_MULTILANG = """
business:
  name: "Test Dental"
  type: "dental office"
  timezone: "America/New_York"
voice:
  voice_id: "marin"
languages:
  primary: "en"
  allowed: ["en", "es", "fr"]
greeting: "Thank you for calling Test Dental."
personality: "You are a friendly receptionist."
hours:
  monday: closed
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "We are currently closed."
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./messages/test/"
"""


V2_YAML_SINGLE_LANG = """
business:
  name: "Test Dental"
  type: "dental office"
  timezone: "America/New_York"
voice:
  voice_id: "marin"
languages:
  primary: "en"
  allowed: ["en"]
greeting: "Thank you for calling Test Dental."
personality: "You are a friendly receptionist."
hours:
  monday: closed
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "We are currently closed."
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./messages/test/"
"""


def test_prompt_mentions_primary_language():
    config = BusinessConfig.from_yaml_string(V2_YAML_MULTILANG)
    prompt = build_system_prompt(config)
    assert "English" in prompt  # primary is "en"


def test_prompt_lists_allowed_languages_when_multiple():
    config = BusinessConfig.from_yaml_string(V2_YAML_MULTILANG)
    prompt = build_system_prompt(config)
    assert "Spanish" in prompt
    assert "French" in prompt


def test_prompt_instructs_llm_to_refuse_unsupported_language():
    config = BusinessConfig.from_yaml_string(V2_YAML_MULTILANG)
    prompt = build_system_prompt(config)
    assert "switch to" in prompt.lower() or "respond in" in prompt.lower()


def test_prompt_single_language_skips_multi_language_block():
    """When allowed has only one language, the multi-language refusal block is unnecessary."""
    config = BusinessConfig.from_yaml_string(V2_YAML_SINGLE_LANG)
    prompt = build_system_prompt(config)
    assert "English" in prompt
    assert "Spanish" not in prompt
    assert "French" not in prompt


def test_prompt_single_language_redirects_on_foreign_input():
    """Regression: single-language block must instruct the LLM on how to
    handle out-of-whitelist input. The earlier terse form ("Speak English.")
    let gpt-realtime-1.5 wobble — it would respond in Spanish while claiming
    it only spoke English. The stronger block tells the model explicitly
    to redirect and NOT mirror the caller's language.
    """
    config = BusinessConfig.from_yaml_string(V2_YAML_SINGLE_LANG)
    prompt = build_system_prompt(config)
    # Must tell the LLM to stay in primary even on foreign input
    assert "only" in prompt.lower()
    # Must include a redirect instruction
    assert "continue in English" in prompt or "ask them to continue" in prompt.lower()
    # Must explicitly warn against mirroring the caller's language
    assert "do not" in prompt.lower() or "don't" in prompt.lower()


# ---- calendar block tests ----


CALENDAR_YAML = """
business: { name: "Test Dental", type: "dental office", timezone: "America/New_York" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Thank you for calling Test Dental."
personality: "You are a friendly receptionist."
hours:
  monday: { open: "09:00", close: "17:00" }
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "We are currently closed."
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./messages/test/"
calendar:
  enabled: false
  auth:
    type: "service_account"
    service_account_file: "/tmp/fake.json"
  appointment_duration_minutes: 30
  buffer_minutes: 15
  buffer_placement: "after"
  booking_window_days: 30
  earliest_booking_hours_ahead: 2
"""


def test_prompt_omits_calendar_block_when_calendar_disabled():
    """When calendar.enabled is False, the prompt does NOT include the CALENDAR section."""
    config = BusinessConfig.from_yaml_string(CALENDAR_YAML)
    prompt = build_system_prompt(config)
    assert "CALENDAR" not in prompt
    assert "check_availability" not in prompt
    assert "book_appointment" not in prompt


def test_prompt_includes_calendar_block_when_enabled(tmp_path):
    """When calendar.enabled is True and the auth file exists, prompt includes CALENDAR section."""
    sa_file = tmp_path / "sa.json"
    sa_file.write_text("{}", encoding="utf-8")
    yaml_text = CALENDAR_YAML.replace(
        "enabled: false",
        "enabled: true",
    ).replace(
        "/tmp/fake.json",
        str(sa_file).replace("\\", "/"),  # forward slashes for YAML compat on Windows
    )
    config = BusinessConfig.from_yaml_string(yaml_text)
    prompt = build_system_prompt(config)
    assert "CALENDAR" in prompt
    assert "check_availability" in prompt
    assert "book_appointment" in prompt
    assert "confirm" in prompt.lower()
    assert "fabricate" in prompt.lower() or "never make up" in prompt.lower()
    # Email-invite instruction: agent must ask, not assume
    assert "calendar invite" in prompt.lower()
    assert "caller_email" in prompt
    # "never make up" + "email address" — wrapped across lines in the prompt
    assert "never make up" in prompt.lower()
    assert "email address" in prompt.lower()
    # Phone + email read-back discipline (digit-by-digit and letter-by-letter)
    assert "digit-by-digit" in prompt.lower() or "digit by digit" in prompt.lower()
    assert "spell out" in prompt.lower() or "letter-by-letter" in prompt.lower()


# ---- intake block tests ----


INTAKES_YAML = """
business: { name: "Test Law", type: "law office", timezone: "America/New_York" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en"] }
greeting: "Thank you for calling Test Law."
personality: "You are a friendly receptionist. The intake takes about 30 minutes."
hours:
  monday: { open: "09:00", close: "17:00" }
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
  saturday: closed
  sunday: closed
after_hours_message: "We are currently closed."
routing: []
faqs: []
messages:
  channels:
    - type: "file"
      file_path: "./messages/test/"
intakes:
  enabled: true
  preamble_en: "This takes about 30 minutes."
  submission:
    file_path: "./messages/test/intakes/"
  case_types:
    - key: workers_comp
      display_name: "Workers' Compensation"
      questions:
        - key: full_name
          prompt_en: "What is your full legal name?"
          required: true
          critical: true
        - key: injury_description
          prompt_en: "Briefly describe what happened."
          required: true
          critical: false
"""


def test_intakes_prompt_does_not_hardcode_duration():
    config = BusinessConfig.from_yaml_string(INTAKES_YAML)
    prompt = build_system_prompt(config)
    assert "15-20 minutes" not in prompt
    assert "use the preamble in the" in prompt.lower()


def test_intakes_prompt_limits_per_character_readback_to_contact_fields():
    config = BusinessConfig.from_yaml_string(INTAKES_YAML)
    prompt = build_system_prompt(config)
    assert "Do NOT read back non-critical answers" in prompt
    assert "phone numbers, Social Security numbers, and email addresses" in prompt


INTAKE_ONLY_YAML = """
agent:
  mode: intake_only
business: { name: "Test Law", type: "law office", timezone: "America/New_York" }
voice: { voice_id: "marin" }
languages: { primary: "en", allowed: ["en", "es"] }
greeting: "Thank you for calling Test Law's automated intake system."
personality: "You are Riley, an automated intake assistant. The intake takes about 30 minutes."
hours:
  monday: { open: "09:00", close: "17:00" }
  tuesday: closed
  wednesday: closed
  thursday: closed
  friday: closed
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
  channels:
    - type: "file"
      file_path: "./messages/test/"
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
intakes:
  enabled: true
  preamble_en: "This takes about 30 minutes."
  submission:
    file_path: "./messages/test/intakes/"
  case_types:
    - key: workers_comp
      display_name: "Workers' Compensation"
      questions:
        - key: full_name
          prompt_en: "What is your full legal name?"
          required: true
          critical: true
info_packets:
  enabled: true
  default_packet: firm_overview
  packets:
    - key: firm_overview
      display_name: "Firm Overview"
      email_subject: "Information from Example Law"
      email_body: "Thank you for completing an intake."
"""


def test_intake_only_prompt_identifies_intake_system():
    config = BusinessConfig.from_yaml_string(INTAKE_ONLY_YAML)
    prompt = build_system_prompt(config)
    assert "automated intake" in prompt.lower()
    assert "ready" in prompt.lower()
    assert "30 minutes" in prompt


def test_intake_only_prompt_suppresses_receptionist_behavior():
    config = BusinessConfig.from_yaml_string(INTAKE_ONLY_YAML)
    prompt = build_system_prompt(config)
    assert "DEPARTMENTS YOU CAN TRANSFER TO" not in prompt
    assert "When asked about business hours" not in prompt
    assert "FREQUENTLY ASKED QUESTIONS" not in prompt


def test_info_packets_prompt_requires_consent_and_confirmed_email():
    config = BusinessConfig.from_yaml_string(INTAKE_ONLY_YAML)
    prompt = build_system_prompt(config)
    assert "send_info_packet" in prompt
    assert "permission" in prompt.lower() or "consent" in prompt.lower()
    # Two-step protocol: first call returns the address to read back,
    # the send requires a second call with destination_confirmed=true.
    assert "destination_confirmed=true" in prompt
    assert "letter by letter" in prompt.lower()
    assert "read" in prompt.lower()


def test_prompt_forbids_silence_after_tool_use_in_both_modes():
    """Shared behavioral rule: the agent must speak after every tool call.
    Emitted in both receptionist and intake_only prompt modes."""
    rule = "Never remain silent after using a tool"
    receptionist_prompt = build_system_prompt(_make_config())
    assert rule in receptionist_prompt
    intake_only_prompt = build_system_prompt(
        BusinessConfig.from_yaml_string(INTAKE_ONLY_YAML),
    )
    assert rule in intake_only_prompt


def test_prompt_includes_dtmf_menu_when_enabled(v2_yaml):
    from receptionist.config import BusinessConfig
    from receptionist.prompts import build_system_prompt

    yaml = v2_yaml + """
dtmf:
  enabled: true
  menu_announcement_en: "Press 1 for the front desk, 0 to leave a message."
  digits:
    "1":
      action: transfer
      routing: "Front Desk"
      acknowledgment_en: "Transferring."
"""
    config = BusinessConfig.from_yaml_string(yaml)
    prompt = build_system_prompt(config)

    assert "Press 1 for the front desk" in prompt
    assert "after the greeting" in prompt.lower()


def test_prompt_omits_dtmf_when_disabled(v2_yaml):
    from receptionist.config import BusinessConfig
    from receptionist.prompts import build_system_prompt

    config = BusinessConfig.from_yaml_string(v2_yaml)
    prompt = build_system_prompt(config)

    assert "dtmf" not in prompt.lower()
    assert "press 1" not in prompt.lower()


def test_prompt_omits_dtmf_when_no_menu_announcement_configured(v2_yaml):
    from receptionist.config import BusinessConfig
    from receptionist.prompts import build_system_prompt

    yaml = v2_yaml + """
dtmf:
  enabled: true
  digits:
    "1":
      action: transfer
      routing: "Front Desk"
      acknowledgment_en: "Transferring."
"""
    config = BusinessConfig.from_yaml_string(yaml)
    prompt = build_system_prompt(config)

    # No menu announcement configured -> no prompt addition; Riley simply
    # answers the call as usual and DTMF still works silently in the
    # background.
    assert "after the greeting" not in prompt.lower()
