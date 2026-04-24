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
