# receptionist/retention/__main__.py
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from receptionist.config import load_config
from receptionist.retention.sweeper import sweep_business

logger = logging.getLogger("receptionist")

DEFAULT_CONFIG_DIR = Path("config/businesses")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m receptionist.retention",
        description="Retention utilities for AIReceptionist artifacts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sweep = sub.add_parser("sweep", help="Delete artifacts older than configured TTL.")
    sweep.add_argument("--dry-run", action="store_true", help="List files that would be deleted without deleting them.")
    sweep.add_argument("--business", help="Only sweep one business (YAML filename stem). Default: all.")
    sweep.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.command != "sweep":
        parser.error(f"Unknown command: {args.command}")
        return 2

    yaml_files = sorted(DEFAULT_CONFIG_DIR.glob("*.yaml"))
    if args.business:
        yaml_files = [p for p in yaml_files if p.stem == args.business]
        if not yaml_files:
            print(f"No config found for business {args.business!r}", file=sys.stderr)
            return 2

    total_deleted = 0
    total_errors = 0

    for path in yaml_files:
        config = load_config(path)
        print(f"\n=== {path.stem} ({config.business.name}) ===")
        results = sweep_business(config, dry_run=args.dry_run)
        for label, result in results.items():
            if args.dry_run:
                print(f"  [{label}] would delete {len(result.would_delete)}, keep {len(result.kept)}")
                for p in result.would_delete:
                    print(f"    - would delete: {p}")
            else:
                print(f"  [{label}] deleted {len(result.deleted)}, kept {len(result.kept)}, errors {len(result.errors)}")
                total_deleted += len(result.deleted)
                total_errors += len(result.errors)
                for p, exc in result.errors:
                    print(f"    ! error on {p}: {exc}", file=sys.stderr)

    if not args.dry_run:
        print(f"\nTotal deleted: {total_deleted}, total errors: {total_errors}")
        if total_errors > 0 and total_deleted == 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
