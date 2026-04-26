# receptionist/booking/setup_cli.py
from __future__ import annotations

import argparse
import logging
import os
import re
import stat
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger("receptionist")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
]
DEFAULT_CONFIG_DIR = Path("config/businesses")

# Same shape as agent.py's RECEPTIONIST_CONFIG / job-metadata validation.
# Without it, `python -m receptionist.booking setup ../../etc/passwd` would
# resolve as a path against config/businesses/ — admin-only command but
# trivial to lock down.
_VALID_BUSINESS_SLUG = re.compile(r"^[a-zA-Z0-9_-]+$")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m receptionist.booking",
        description="Google Calendar setup utilities for AIReceptionist.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser(
        "setup",
        help="Walk through the OAuth consent flow for a business's calendar.",
    )
    setup.add_argument("business", help="Business slug (YAML filename stem in config/businesses/).")
    setup.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    if args.command != "setup":
        parser.error(f"Unknown command: {args.command}")
        return 2

    if not _VALID_BUSINESS_SLUG.match(args.business):
        parser.error(
            f"Invalid business slug: {args.business!r}. "
            f"Must match {_VALID_BUSINESS_SLUG.pattern} (alphanumerics, dash, underscore)."
        )
        return 2

    return _run_setup(args.business)


def _run_setup(business_slug: str) -> int:
    config_path = DEFAULT_CONFIG_DIR / f"{business_slug}.yaml"
    if not config_path.exists():
        print(
            f"Business config not found: {config_path}. "
            f"Available businesses: {sorted(p.stem for p in DEFAULT_CONFIG_DIR.glob('*.yaml'))}",
            file=sys.stderr,
        )
        return 2

    secrets_dir = Path("secrets") / business_slug
    secrets_dir.mkdir(parents=True, exist_ok=True)

    client_file = secrets_dir / "google-calendar-oauth-client.json"
    token_file = secrets_dir / "google-calendar-oauth.json"

    if not client_file.exists():
        print(
            f"\nOAuth client JSON not found at {client_file}.\n"
            f"\n"
            f"Before running setup, you need to:\n"
            f"  1. Go to https://console.cloud.google.com/apis/credentials\n"
            f"  2. Create an OAuth 2.0 Client ID (application type: Desktop app)\n"
            f"  3. Download the JSON (it looks like {{\"installed\": {{...}}}})\n"
            f"  4. Save it as {client_file}\n"
            f"\n"
            f"Then re-run: python -m receptionist.booking setup {business_slug}\n",
            file=sys.stderr,
        )
        return 2

    print(f"Starting OAuth flow for {business_slug}...")
    print("A browser window will open. Sign in with the Google account whose calendar")
    print("you want to use for appointment booking.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    creds = flow.run_local_server(port=0)  # port=0 -> pick an available port

    token_file.write_text(creds.to_json(), encoding="utf-8")
    _set_0600(token_file)

    # ASCII markers — default Windows cp1252 console can't print U+2713 ("✓").
    # Token write + chmod above already succeeded, so the unicode crash would
    # have been a confusing post-success failure.
    print(f"\n[OK] OAuth token saved to {token_file} (permissions: 0600)")
    print(f"[OK] Set auth.type: \"oauth\" and auth.oauth_token_file: \"./{token_file}\" in")
    print(f"     {config_path}")
    return 0


def _set_0600(path: Path) -> None:
    """Set the file to owner-read/write only. No-op on Windows."""
    if sys.platform == "win32":
        return
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


if __name__ == "__main__":
    sys.exit(main())
