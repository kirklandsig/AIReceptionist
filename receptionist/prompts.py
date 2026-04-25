# receptionist/prompts.py
from __future__ import annotations

from receptionist.config import BusinessConfig


# ISO 639-1 → human name for the subset we actively test. Unknown codes
# are rendered as-is (the LLM understands ISO codes too).
_LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
    "ru": "Russian",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "uk": "Ukrainian",
}


def _language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code.lower(), code.upper())


def _build_language_block(config: BusinessConfig) -> str:
    primary = _language_name(config.languages.primary)
    allowed = [c for c in config.languages.allowed]

    if len(allowed) <= 1:
        return (
            f"LANGUAGE:\n"
            f"Speak {primary} only. Every response must be in {primary}, "
            f"even if the caller speaks another language. "
            f"If the caller speaks a language other than {primary}, "
            f"politely say in {primary} that you can only assist in {primary}, "
            f"and ask them to continue in {primary}. "
            f"Do NOT repeat yourself in the caller's language; that would undermine "
            f"the instruction to speak {primary} only."
        )

    alt_names = [_language_name(c) for c in allowed if c.lower() != config.languages.primary.lower()]
    alt_list = ", ".join(alt_names)
    all_names = [_language_name(c) for c in allowed]
    all_list = ", ".join(all_names)

    return (
        f"LANGUAGE:\n"
        f"Your primary language is {primary}. You can also respond in: {alt_list}.\n"
        f"If the caller speaks one of those languages, respond in that language for the rest of the call. "
        f"If the caller speaks a language that is NOT in this list ({all_list}), "
        f"politely say in {primary} that you can assist in {all_list}, and ask them to switch to one of those."
    )


def _build_calendar_block(config: BusinessConfig) -> str:
    """Build the CALENDAR section of the system prompt, or empty string if disabled."""
    if config.calendar is None or not config.calendar.enabled:
        return ""
    return (
        "\nCALENDAR (appointment booking):\n"
        "You can book appointments on the business calendar using two tools:\n"
        "  1. check_availability(preferred_date, preferred_time) — call this FIRST.\n"
        "     It returns up to 3 available slots near the caller's preferred time,\n"
        "     each with a human-readable time AND an iso= string.\n"
        "  2. book_appointment(caller_name, callback_number, proposed_start_iso, notes) —\n"
        "     call this AFTER the caller confirms the specific time you offered.\n"
        "     The proposed_start_iso MUST be copied exactly from a check_availability\n"
        "     response — you cannot make one up.\n"
        "\n"
        "BOOKING CONVENTIONS (follow exactly):\n"
        "  - Before booking, always say the specific time back to the caller and wait\n"
        "    for explicit confirmation: \"I'm booking you for Tuesday April 28 at 2 PM.\n"
        "    Can I confirm?\" Do NOT book without a clear \"yes.\"\n"
        "  - If check_availability says a time is too soon or too far out, politely\n"
        "    offer the caller the earliest/latest the tool permitted.\n"
        "  - If book_appointment says the slot just got taken, offer the alternatives\n"
        "    the tool returned.\n"
        "  - If the calendar can't be reached, pivot to take_message: \"I'm having\n"
        "    trouble with the calendar — can I take your info and have someone call\n"
        "    back to confirm the time?\"\n"
        "  - NEVER fabricate a time, confirmation code, or event ID.\n"
    )


def build_system_prompt(config: BusinessConfig) -> str:
    hours_lines = []
    for day_name in [
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    ]:
        day_hours = getattr(config.hours, day_name)
        display_name = day_name.capitalize()
        if day_hours is None:
            hours_lines.append(f"  {display_name}: Closed")
        else:
            hours_lines.append(f"  {display_name}: {day_hours.open} - {day_hours.close}")
    hours_block = "\n".join(hours_lines)

    routing_lines = [f"  - {e.name}: {e.description}" for e in config.routing]
    routing_block = "\n".join(routing_lines) if routing_lines else "  No routing configured."

    faq_lines = [f"  Q: {faq.question}\n  A: {faq.answer}" for faq in config.faqs]
    faq_block = "\n\n".join(faq_lines) if faq_lines else "  No FAQs configured."

    language_block = _build_language_block(config)
    calendar_block = _build_calendar_block(config)

    return f"""You are the receptionist for {config.business.name}, a {config.business.type}.

{config.personality}

{language_block}

BUSINESS HOURS (timezone: {config.business.timezone}):
{hours_block}

When the business is closed, say: {config.after_hours_message}

DEPARTMENTS YOU CAN TRANSFER TO:
{routing_block}

When a caller asks to be transferred, use the transfer_call tool with the department name.
When a caller wants to leave a message, use the take_message tool to record their name, message, and callback number.
When asked about business hours, use the get_business_hours tool.
{calendar_block}
FREQUENTLY ASKED QUESTIONS:
{faq_block}

You can answer these questions directly. For questions not covered here, offer to take a message or transfer the caller to the appropriate department.

IMPORTANT RULES:
- Be concise. Phone conversations should be efficient.
- Never make up information. If you don't know, say so and offer alternatives.
- Always confirm before transferring a call.
- If the caller seems upset, be empathetic and offer to connect them with a person.
"""
