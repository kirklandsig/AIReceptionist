# receptionist/messaging/__main__.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from receptionist.config import load_config
from receptionist.messaging.failures import resolve_failures_dir
from receptionist.messaging.failures_cli import list_failures

DEFAULT_CONFIG_DIR = Path("config/businesses")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m receptionist.messaging",
        description="Messaging utilities.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    lf = sub.add_parser("list-failures", help="List records in each business's .failures/ directory.")
    lf.add_argument("--business", help="Only scan one business. Default: all.")

    args = parser.parse_args(argv)

    if args.command != "list-failures":
        parser.error(f"Unknown command: {args.command}")
        return 2

    yaml_files = sorted(DEFAULT_CONFIG_DIR.glob("*.yaml"))
    if args.business:
        yaml_files = [p for p in yaml_files if p.stem == args.business]
        if not yaml_files:
            print(f"No config found for business {args.business!r}", file=sys.stderr)
            return 2

    search_paths: list[str] = []
    for yaml_path in yaml_files:
        config = load_config(yaml_path)
        # Derive the failures dir using the same rules as resolve_failures_dir:
        # prefer a FileChannel's file_path; otherwise fall back to the messages slug.
        failures_dir = resolve_failures_dir(config.messages.channels, config.business.name)
        # list_failures takes the PARENT of .failures (the scan root)
        search_paths.append(str(failures_dir.parent))

    return list_failures(search_paths)


if __name__ == "__main__":
    sys.exit(main())
