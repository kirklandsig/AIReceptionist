# tests/conftest.py
from __future__ import annotations

import pytest


EXAMPLE_YAML_V2 = """
business:
  name: "Test Dental"
  type: "dental office"
  timezone: "America/New_York"

voice:
  voice_id: "marin"
  model: "gpt-realtime-1.5"

languages:
  primary: "en"
  allowed: ["en", "es"]

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
  channels:
    - type: "file"
      file_path: "./messages/test-dental/"

retention:
  recordings_days: 90
  transcripts_days: 90
  messages_days: 0
"""


EXAMPLE_YAML_LEGACY = """
business:
  name: "Legacy Dental"
  type: "dental office"
  timezone: "America/New_York"
voice:
  voice_id: "coral"
greeting: "Hello."
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
  delivery: "file"
  file_path: "./messages/legacy/"
"""


@pytest.fixture
def v2_yaml() -> str:
    return EXAMPLE_YAML_V2


@pytest.fixture
def legacy_yaml() -> str:
    return EXAMPLE_YAML_LEGACY
