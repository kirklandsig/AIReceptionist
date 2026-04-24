# receptionist/messaging/failures_cli.py
from __future__ import annotations

import json
import sys
from pathlib import Path


def list_failures(search_paths: list[str]) -> int:
    """Scan each `search_path` for a `.failures/` directory and print a summary.

    Returns an exit code: 0 always on success (even if no failures). Corrupt
    JSON files are printed to stderr as warnings; they do not change the
    exit code.
    """
    total = 0
    for raw_path in search_paths:
        base = Path(raw_path)
        failures_dir = base / ".failures"
        if not failures_dir.exists():
            continue
        records = sorted(failures_dir.glob("*.json"))
        if not records:
            continue
        print(f"\n=== {failures_dir} ({len(records)} record(s)) ===")
        for record_path in records:
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"warning: corrupt JSON, skipping {record_path}: {e}", file=sys.stderr)
                continue
            channel = data.get("channel", "?")
            failed_at = data.get("failed_at", "?")
            caller = data.get("message", {}).get("caller_name", "?")
            attempts = data.get("attempts", [])
            last_error = attempts[-1].get("error_detail", "?") if attempts else "?"
            print(
                f"  [{failed_at}] channel={channel} caller={caller} "
                f"attempts={len(attempts)} last_error={last_error!r}"
            )
            total += 1

    if total == 0:
        print("No failures found.")
    return 0
