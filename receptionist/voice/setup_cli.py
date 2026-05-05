from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from receptionist.voice_auth import VoiceAuthError, inspect_codex_auth_file, resolve_voice_bearer

DEFAULT_CONFIG_DIR = Path("config/businesses")
DEFAULT_CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
_VALID_BUSINESS_SLUG = re.compile(r"^[a-zA-Z0-9_-]+$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m receptionist.voice",
        description="OpenAI Realtime voice auth setup utilities for AIReceptionist.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser(
        "setup",
        help="Set up per-business OpenAI OAuth tokens using Codex login.",
    )
    setup.add_argument("business", help="Business slug (YAML filename stem in config/businesses/).")
    setup.add_argument(
        "--auth-path",
        help="Target auth.json path. Defaults to existing voice.auth.path or secrets/<business>/openai_auth.json.",
    )
    setup.add_argument(
        "--codex-auth-source",
        default=str(DEFAULT_CODEX_AUTH_PATH),
        help="Source Codex auth.json path after codex login. Default: ~/.codex/auth.json.",
    )

    args = parser.parse_args(argv)
    if args.command != "setup":
        parser.error(f"Unknown command: {args.command}")
        return 2

    if not _VALID_BUSINESS_SLUG.match(args.business):
        parser.error(
            f"Invalid business slug: {args.business!r}. "
            f"Must match {_VALID_BUSINESS_SLUG.pattern} (alphanumerics, dash, underscore)."
        )
        return 2

    return _run_setup(
        args.business,
        auth_path_override=args.auth_path,
        codex_auth_source=Path(args.codex_auth_source).expanduser(),
    )


def _run_setup(
    business_slug: str,
    *,
    auth_path_override: str | None = None,
    codex_auth_source: Path = DEFAULT_CODEX_AUTH_PATH,
) -> int:
    config_path = DEFAULT_CONFIG_DIR / f"{business_slug}.yaml"
    if not config_path.exists():
        print(
            f"Business config not found: {config_path}. "
            f"Available businesses: {sorted(p.stem for p in DEFAULT_CONFIG_DIR.glob('*.yaml'))}",
            file=sys.stderr,
        )
        return 2

    auth_path = _resolve_target_auth_path(config_path, business_slug, auth_path_override)
    try:
        token = resolve_voice_bearer(_codex_auth(auth_path))
        status = inspect_codex_auth_file(str(auth_path))
    except VoiceAuthError as e:
        print(f"OpenAI OAuth token not usable yet: {e}")
    else:
        _update_voice_auth_block(config_path, auth_path)
        print(f"[OK] OpenAI OAuth token already usable at {auth_path}")
        _print_token_status(status, token)
        print(f"[OK] Updated {config_path} voice.auth.path")
        return 0

    if _source_auth_usable(codex_auth_source):
        print(f"Using existing Codex auth file at {codex_auth_source}")
    else:
        codex = shutil.which("codex")
        if codex is None:
            print(
                "Codex CLI not found on PATH. Install it with `npm install -g @openai/codex`, "
                "then re-run this setup command.",
                file=sys.stderr,
            )
            return 2

        print(f"Starting Codex login for {business_slug}...")
        print("A browser window may open. Sign in with the ChatGPT account for this business.\n")
        result = subprocess.run([codex, "login"], check=False)
        if result.returncode != 0:
            print(f"codex login failed with exit code {result.returncode}", file=sys.stderr)
            return 2

    if not codex_auth_source.exists():
        print(f"Codex auth file not found after login: {codex_auth_source}", file=sys.stderr)
        return 2

    auth_path.parent.mkdir(parents=True, exist_ok=True)
    if codex_auth_source.resolve() != auth_path.resolve():
        shutil.copy2(codex_auth_source, auth_path)
    _set_0600(auth_path)

    try:
        token = resolve_voice_bearer(_codex_auth(auth_path))
        status = inspect_codex_auth_file(str(auth_path))
    except VoiceAuthError as e:
        print(f"Copied Codex auth file is not usable: {e}", file=sys.stderr)
        return 2

    _update_voice_auth_block(config_path, auth_path)
    print(f"\n[OK] OpenAI OAuth token saved to {auth_path}")
    _print_token_status(status, token)
    print(f"[OK] Updated {config_path} voice.auth block")
    return 0


def _codex_auth(path: Path):
    from receptionist.config import CodexOAuthVoiceAuth

    return CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))


def _source_auth_usable(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        resolve_voice_bearer(_codex_auth(path))
    except VoiceAuthError:
        return False
    return True


def _resolve_target_auth_path(
    config_path: Path, business_slug: str, override: str | None,
) -> Path:
    if override:
        return Path(override).expanduser()
    config = _load_yaml(config_path)
    voice = config.get("voice") or {}
    auth = voice.get("auth") if isinstance(voice, dict) else None
    if isinstance(auth, dict) and auth.get("type") == "oauth_codex" and auth.get("path"):
        return Path(str(auth["path"])).expanduser()
    return Path("secrets") / business_slug / "openai_auth.json"


def _update_voice_auth_block(config_path: Path, auth_path: Path) -> None:
    text = config_path.read_text(encoding="utf-8")
    config = _load_yaml(config_path)
    voice = config.get("voice")
    if not isinstance(voice, dict):
        voice = {}
    voice["auth"] = {
        "type": "oauth_codex",
        "path": _yaml_path(auth_path),
    }
    rendered = yaml.safe_dump(
        {"voice": voice}, sort_keys=False, default_flow_style=False,
    ).splitlines()
    lines = text.splitlines()
    start = _find_top_level_key(lines, "voice")
    if start is None:
        new_text = text.rstrip() + "\n" + "\n".join(rendered) + "\n"
    else:
        end = _find_next_top_level_key(lines, start + 1)
        next_lines = lines[:start] + rendered + lines[end:]
        new_text = "\n".join(next_lines) + "\n"
    config_path.write_text(new_text, encoding="utf-8")


def _load_yaml(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Business config must be a YAML mapping: {config_path}")
    return data


def _find_top_level_key(lines: list[str], key: str) -> int | None:
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for i, line in enumerate(lines):
        if pattern.match(line):
            return i
    return None


def _find_next_top_level_key(lines: list[str], start: int) -> int:
    for i in range(start, len(lines)):
        line = lines[i]
        if line.strip() and not line.startswith((" ", "\t", "#")) and ":" in line:
            return i
    return len(lines)


def _yaml_path(path: Path) -> str:
    return path.as_posix()


def _print_token_status(status, token: str | None) -> None:
    if status.expires_at:
        expires = datetime_from_timestamp(status.expires_at)
        print(f"[OK] access_token expires at {expires}")
    else:
        print("[OK] access_token present; expiry claim not available")
    if status.refresh_token_present:
        print("[OK] refresh_token present")
    print(f"[OK] bearer length: {len(token or '')}")


def datetime_from_timestamp(timestamp: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _set_0600(path: Path) -> None:
    if sys.platform == "win32":
        return
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
