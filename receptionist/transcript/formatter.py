# receptionist/transcript/formatter.py
from __future__ import annotations

import json
from typing import Sequence

from receptionist.transcript.capture import SpeakerRole, TranscriptSegment
from receptionist.transcript.metadata import CallMetadata


def to_json(segments: Sequence[TranscriptSegment], metadata: CallMetadata) -> str:
    payload = {
        "metadata": metadata.to_dict(),
        "segments": [
            {
                "role": s.role.value,
                "text": s.text,
                "created_at": s.created_at,
                "language": s.language,
                "tool_arguments": s.tool_arguments,
                "tool_output": s.tool_output,
            }
            for s in segments
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def to_markdown(segments: Sequence[TranscriptSegment], metadata: CallMetadata) -> str:
    lines: list[str] = []
    lines.append(f"# Call transcript — {metadata.business_name}")
    lines.append("")
    lines.append(f"- Call ID: `{metadata.call_id}`")
    lines.append(f"- Caller: {metadata.caller_phone or 'Unknown'}")
    lines.append(f"- Start: {metadata.start_ts}")
    if metadata.end_ts:
        lines.append(f"- End: {metadata.end_ts}")
    if metadata.duration_seconds is not None:
        lines.append(f"- Duration: {int(metadata.duration_seconds)}s")
    if metadata.outcome:
        lines.append(f"- Outcome: {metadata.outcome}")
    if metadata.languages_detected:
        lines.append(f"- Languages: {', '.join(sorted(metadata.languages_detected))}")
    if metadata.faqs_answered:
        lines.append(f"- FAQs answered: {', '.join(metadata.faqs_answered)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for seg in segments:
        if seg.role == SpeakerRole.USER:
            lang = f" _({seg.language})_" if seg.language else ""
            lines.append(f"**Caller:**{lang} {seg.text}")
        elif seg.role == SpeakerRole.ASSISTANT:
            lines.append(f"**Agent:** {seg.text}")
        elif seg.role == SpeakerRole.TOOL:
            lines.append(f"**Tool:** {seg.text}")
            if seg.tool_arguments:
                lines.append(f"  - arguments: `{seg.tool_arguments}`")
            if seg.tool_output:
                lines.append(f"  - output: {seg.tool_output}")
        lines.append("")

    return "\n".join(lines)
