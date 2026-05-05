from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx

from receptionist.config import (
    APIKeyVoiceAuth,
    CodexOAuthVoiceAuth,
    StaticOAuthVoiceAuth,
    VoiceAuth,
)

OPENAI_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_CODEX_REFRESH_URL = "https://auth.openai.com/oauth/token"
REFRESH_URL_ENV = "CODEX_REFRESH_TOKEN_URL_OVERRIDE"
REFRESH_EXPIRY_SKEW_SECONDS = 60
REFRESH_LOCK_TIMEOUT_SECONDS = 30.0
REFRESH_LOCK_STALE_SECONDS = 120.0
REFRESH_LOCK_POLL_SECONDS = 0.1


@dataclass(frozen=True)
class TokenStatus:
    access_token: str
    expires_at: int | None
    refresh_token_present: bool


@dataclass(frozen=True)
class _CachedToken:
    access_token: str
    expires_at: int | None


_CACHE_LOCK = threading.Lock()
_TOKEN_CACHE: dict[tuple[Path, str], _CachedToken] = {}
_REFRESH_LOCKS: dict[tuple[Path, str], threading.Lock] = {}


class VoiceAuthError(RuntimeError):
    """Raised when explicit Realtime voice authentication cannot be resolved."""


async def resolve_voice_bearer_async(auth: VoiceAuth | None) -> str | None:
    return await asyncio.to_thread(resolve_voice_bearer, auth)


def resolve_voice_bearer(auth: VoiceAuth | None) -> str | None:
    """Resolve the bearer string passed to RealtimeModel(api_key=...).

    Returning None is intentional only for omitted auth, preserving the
    livekit-openai plugin's existing OPENAI_API_KEY fallback.
    """
    if auth is None:
        return None
    if isinstance(auth, APIKeyVoiceAuth):
        token = os.environ.get(auth.env)
        if not token:
            raise VoiceAuthError(f"voice.auth api_key env var {auth.env!r} is not set")
        return token
    if isinstance(auth, CodexOAuthVoiceAuth):
        return _read_codex_access_token(auth.path)
    if isinstance(auth, StaticOAuthVoiceAuth):
        if auth.token is not None:
            return auth.token
        assert auth.token_env is not None
        token = os.environ.get(auth.token_env)
        if not token:
            raise VoiceAuthError(
                f"voice.auth oauth_static token_env {auth.token_env!r} is not set"
            )
        return token
    raise VoiceAuthError(f"Unsupported voice auth type: {type(auth).__name__}")


def inspect_codex_auth_file(path_str: str) -> TokenStatus:
    path = Path(path_str).expanduser()
    data = _read_auth_json(path)
    tokens = _read_tokens(data, path)
    access_token = _read_access_token(tokens, path)
    return TokenStatus(
        access_token=access_token,
        expires_at=_decode_jwt_exp(access_token),
        refresh_token_present=bool(tokens.get("refresh_token")),
    )


def _read_codex_access_token(path_str: str) -> str:
    path = Path(path_str).expanduser()
    data = _read_auth_json(path)
    tokens = _read_tokens(data, path)
    access_token = _read_access_token(tokens, path)
    refresh_token = tokens.get("refresh_token")
    expires_at = _decode_jwt_exp(access_token)
    if not _should_refresh(expires_at):
        _cache_token(path, refresh_token, access_token, expires_at)
        return access_token

    cached = _get_cached_token(path, refresh_token)
    if cached is not None and not _should_refresh(cached.expires_at):
        return cached.access_token

    if not refresh_token:
        raise VoiceAuthError(
            f"voice.auth oauth_codex access_token is expired and file is missing "
            f"tokens.refresh_token: {path}"
        )

    refresh_lock = _get_refresh_lock(path, refresh_token)
    with refresh_lock:
        with _refresh_file_lock(path):
            # Another call may have refreshed and rotated the file while we
            # waited. Re-read before POSTing so only one caller spends the
            # refresh token.
            data = _read_auth_json(path)
            tokens = _read_tokens(data, path)
            access_token = _read_access_token(tokens, path)
            refresh_token = tokens.get("refresh_token")
            expires_at = _decode_jwt_exp(access_token)
            if not _should_refresh(expires_at):
                _cache_token(path, refresh_token, access_token, expires_at)
                return access_token

            cached = _get_cached_token(path, refresh_token)
            if cached is not None and not _should_refresh(cached.expires_at):
                return cached.access_token

            if not refresh_token:
                raise VoiceAuthError(
                    f"voice.auth oauth_codex access_token is expired and file is missing "
                    f"tokens.refresh_token: {path}"
                )

            refreshed = _refresh_codex_tokens(refresh_token)
            refreshed_access_token = refreshed.get("access_token")
            if not refreshed_access_token:
                raise VoiceAuthError("voice.auth oauth_codex refresh response missing access_token")

            tokens["access_token"] = refreshed_access_token
            if refreshed.get("refresh_token"):
                tokens["refresh_token"] = refreshed["refresh_token"]
            if refreshed.get("id_token"):
                tokens["id_token"] = refreshed["id_token"]
            data["tokens"] = tokens
            data["last_refresh"] = datetime.now(timezone.utc).isoformat()
            _write_auth_json(path, data)

            new_refresh_token = tokens.get("refresh_token")
            new_expires_at = _decode_jwt_exp(refreshed_access_token)
            _cache_token(path, new_refresh_token, refreshed_access_token, new_expires_at)
            return refreshed_access_token


def _read_tokens(data: dict[str, Any], path: Path) -> dict[str, Any]:
    tokens = data.get("tokens") or {}
    if not isinstance(tokens, dict):
        raise VoiceAuthError(f"voice.auth oauth_codex file tokens must be an object: {path}")
    return tokens


def _read_access_token(tokens: dict[str, Any], path: Path) -> str:
    access_token = tokens.get("access_token")
    if not access_token:
        raise VoiceAuthError(
            f"voice.auth oauth_codex file is missing tokens.access_token: {path}"
        )
    return access_token


def _read_auth_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise VoiceAuthError(f"voice.auth oauth_codex file not found: {path}") from e
    except OSError as e:
        raise VoiceAuthError(f"voice.auth oauth_codex file could not be read: {path}") from e
    except json.JSONDecodeError as e:
        raise VoiceAuthError(f"voice.auth oauth_codex file is not valid JSON: {path}") from e
    if not isinstance(data, dict):
        raise VoiceAuthError(f"voice.auth oauth_codex file must contain a JSON object: {path}")
    return data


def _refresh_codex_tokens(refresh_token: str) -> dict[str, Any]:
    refresh_url = os.environ.get(REFRESH_URL_ENV, OPENAI_CODEX_REFRESH_URL)
    try:
        response = httpx.post(
            refresh_url,
            json={
                "client_id": OPENAI_CODEX_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=20,
        )
    except httpx.HTTPError as e:
        raise VoiceAuthError(f"voice.auth oauth_codex refresh request failed: {e}") from e

    if response.is_success:
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise VoiceAuthError("voice.auth oauth_codex refresh response was not JSON") from e
        if not isinstance(data, dict):
            raise VoiceAuthError("voice.auth oauth_codex refresh response was not an object")
        return data

    raise VoiceAuthError(
        f"voice.auth oauth_codex refresh failed: {response.status_code}: "
        f"{_refresh_error_message(response)}"
    )


def _refresh_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except json.JSONDecodeError:
        return response.text[:500]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)
    if isinstance(error, str):
        return error
    return str(data)[:500]


def _decode_jwt_exp(token: str) -> int | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        claims = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    exp = claims.get("exp")
    return exp if isinstance(exp, int) else None


def _should_refresh(expires_at: int | None) -> bool:
    if expires_at is None:
        return False
    return expires_at <= int(datetime.now(timezone.utc).timestamp()) + REFRESH_EXPIRY_SKEW_SECONDS


def _get_cached_token(path: Path, refresh_token: str | None) -> _CachedToken | None:
    if not refresh_token:
        return None
    with _CACHE_LOCK:
        return _TOKEN_CACHE.get((path, refresh_token))


def _get_refresh_lock(path: Path, refresh_token: str) -> threading.Lock:
    with _CACHE_LOCK:
        key = (path, refresh_token)
        lock = _REFRESH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _REFRESH_LOCKS[key] = lock
        return lock


@contextmanager
def _refresh_file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.refresh.lock")
    deadline = time.monotonic() + REFRESH_LOCK_TIMEOUT_SECONDS
    fd: int | None = None
    owner = f"{os.getpid()}:{uuid.uuid4().hex}\n"
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, owner.encode("ascii"))
            break
        except FileExistsError:
            if _remove_stale_refresh_lock(lock_path):
                continue
            if time.monotonic() >= deadline:
                raise VoiceAuthError(
                    f"voice.auth oauth_codex timed out waiting for refresh lock: {lock_path}"
                )
            time.sleep(REFRESH_LOCK_POLL_SECONDS)
        except OSError as e:
            raise VoiceAuthError(
                f"voice.auth oauth_codex could not create refresh lock: {lock_path}"
            ) from e

    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        _remove_refresh_lock_if_owner(lock_path, owner)


def _remove_stale_refresh_lock(lock_path: Path) -> bool:
    try:
        age = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if age <= REFRESH_LOCK_STALE_SECONDS:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _remove_refresh_lock_if_owner(lock_path: Path, owner: str) -> None:
    try:
        current_owner = lock_path.read_text(encoding="ascii")
    except FileNotFoundError:
        return
    except OSError:
        return
    if current_owner != owner:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _cache_token(
    path: Path, refresh_token: str | None, access_token: str, expires_at: int | None,
) -> None:
    if not refresh_token:
        return
    with _CACHE_LOCK:
        _TOKEN_CACHE[(path, refresh_token)] = _CachedToken(access_token, expires_at)


def _clear_token_cache() -> None:
    with _CACHE_LOCK:
        _TOKEN_CACHE.clear()
        _REFRESH_LOCKS.clear()


def _write_auth_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _set_0600(tmp_path)
    _replace_file(tmp_path, path)
    _set_0600(path)


def _replace_file(source: Path, target: Path) -> None:
    source.replace(target)


def _set_0600(path: Path) -> None:
    if sys.platform == "win32":
        return
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
