from __future__ import annotations

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from receptionist.config import APIKeyVoiceAuth, CodexOAuthVoiceAuth, StaticOAuthVoiceAuth
from receptionist.voice_auth import (
    VoiceAuthError,
    _clear_token_cache,
    _write_auth_json,
    inspect_codex_auth_file,
    resolve_voice_bearer,
    resolve_voice_bearer_async,
)


@pytest.fixture(autouse=True)
def clear_voice_auth_cache():
    _clear_token_cache()
    yield
    _clear_token_cache()


def test_resolve_none_preserves_plugin_env_fallback():
    assert resolve_voice_bearer(None) is None


def test_resolve_api_key_default_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    auth = APIKeyVoiceAuth(type="api_key")
    assert resolve_voice_bearer(auth) == "sk-test"


def test_resolve_api_key_custom_env(monkeypatch):
    monkeypatch.setenv("ACME_OPENAI_KEY", "sk-acme")
    auth = APIKeyVoiceAuth(type="api_key", env="ACME_OPENAI_KEY")
    assert resolve_voice_bearer(auth) == "sk-acme"


def test_resolve_api_key_missing_env_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    auth = APIKeyVoiceAuth(type="api_key")
    with pytest.raises(VoiceAuthError, match="OPENAI_API_KEY"):
        resolve_voice_bearer(auth)


def test_resolve_oauth_codex_reads_access_token(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(
        json.dumps({"tokens": {"access_token": "oauth-access-token"}}),
        encoding="utf-8",
    )
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    assert resolve_voice_bearer(auth) == "oauth-access-token"


def test_resolve_oauth_codex_reads_unexpired_access_token_without_refresh(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    access_token = _jwt(exp=datetime.now(timezone.utc) + timedelta(minutes=30))
    path.write_text(
        json.dumps({"tokens": {"access_token": access_token, "refresh_token": "refresh"}}),
        encoding="utf-8",
    )
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("refresh should not be called")

    monkeypatch.setattr("receptionist.voice_auth.httpx.post", fake_post)
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    assert resolve_voice_bearer(auth) == access_token
    assert called is False


def test_resolve_oauth_codex_refreshes_expired_access_token(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    expired = _jwt(exp=datetime.now(timezone.utc) - timedelta(minutes=5))
    fresh = _jwt(exp=datetime.now(timezone.utc) + timedelta(minutes=30))
    path.write_text(
        json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": "old-id",
                "access_token": expired,
                "refresh_token": "old-refresh",
                "account_id": "acct",
            },
        }),
        encoding="utf-8",
    )

    def fake_post(url, *, json, timeout):
        assert url == "https://auth.openai.com/oauth/token"
        assert json["grant_type"] == "refresh_token"
        assert json["refresh_token"] == "old-refresh"
        assert json["client_id"] == "app_EMoamEEZ73f0CkXaXp7hrann"
        assert timeout == 20
        return httpx.Response(200, json={
            "id_token": "new-id",
            "access_token": fresh,
            "refresh_token": "new-refresh",
        })

    monkeypatch.setattr("receptionist.voice_auth.httpx.post", fake_post)
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    assert resolve_voice_bearer(auth) == fresh

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["tokens"]["id_token"] == "new-id"
    assert saved["tokens"]["access_token"] == fresh
    assert saved["tokens"]["refresh_token"] == "new-refresh"
    assert saved["tokens"]["account_id"] == "acct"
    assert saved["last_refresh"]


def test_resolve_oauth_codex_removes_refresh_lock_file(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    expired = _jwt(exp=datetime.now(timezone.utc) - timedelta(minutes=5))
    fresh = _jwt(exp=datetime.now(timezone.utc) + timedelta(minutes=30))
    path.write_text(
        json.dumps({"tokens": {"access_token": expired, "refresh_token": "refresh"}}),
        encoding="utf-8",
    )

    def fake_post(*args, **kwargs):
        return httpx.Response(200, json={"access_token": fresh})

    monkeypatch.setattr("receptionist.voice_auth.httpx.post", fake_post)
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    assert resolve_voice_bearer(auth) == fresh
    assert not (tmp_path / ".auth.json.refresh.lock").exists()


def test_resolve_oauth_codex_uses_cache_when_file_still_expired(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    expired = _jwt(exp=datetime.now(timezone.utc) - timedelta(minutes=5))
    fresh = _jwt(exp=datetime.now(timezone.utc) + timedelta(minutes=30))
    path.write_text(
        json.dumps({"tokens": {"access_token": expired, "refresh_token": "refresh"}}),
        encoding="utf-8",
    )
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"access_token": fresh})

    monkeypatch.setattr("receptionist.voice_auth.httpx.post", fake_post)
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    assert resolve_voice_bearer(auth) == fresh

    # Simulate another worker/process not seeing the write yet: put the old
    # expired token back on disk. This process should still reuse its fresh cache.
    path.write_text(
        json.dumps({"tokens": {"access_token": expired, "refresh_token": "refresh"}}),
        encoding="utf-8",
    )
    assert resolve_voice_bearer(auth) == fresh
    assert calls == 1


def test_resolve_oauth_codex_serializes_concurrent_refreshes(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    expired = _jwt(exp=datetime.now(timezone.utc) - timedelta(minutes=5))
    fresh = _jwt(exp=datetime.now(timezone.utc) + timedelta(minutes=30))
    path.write_text(
        json.dumps({"tokens": {"access_token": expired, "refresh_token": "refresh"}}),
        encoding="utf-8",
    )
    entered_refresh = threading.Event()
    release_refresh = threading.Event()
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered_refresh.set()
        assert release_refresh.wait(timeout=2)
        return httpx.Response(200, json={
            "access_token": fresh,
            "refresh_token": "rotated-refresh",
        })

    monkeypatch.setattr("receptionist.voice_auth.httpx.post", fake_post)
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(resolve_voice_bearer, auth)
        assert entered_refresh.wait(timeout=2)
        second = pool.submit(resolve_voice_bearer, auth)
        release_refresh.set()

        assert first.result(timeout=2) == fresh
        assert second.result(timeout=2) == fresh

    assert calls == 1


def test_resolve_oauth_codex_refresh_error_raises(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    expired = _jwt(exp=datetime.now(timezone.utc) - timedelta(minutes=5))
    path.write_text(
        json.dumps({"tokens": {"access_token": expired, "refresh_token": "refresh"}}),
        encoding="utf-8",
    )

    def fake_post(*args, **kwargs):
        return httpx.Response(400, json={"error": {"message": "bad refresh"}})

    monkeypatch.setattr("receptionist.voice_auth.httpx.post", fake_post)
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    with pytest.raises(VoiceAuthError, match="bad refresh"):
        resolve_voice_bearer(auth)


def test_resolve_oauth_codex_expired_without_refresh_token_raises(tmp_path):
    path = tmp_path / "auth.json"
    expired = _jwt(exp=datetime.now(timezone.utc) - timedelta(minutes=5))
    path.write_text(json.dumps({"tokens": {"access_token": expired}}), encoding="utf-8")
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    with pytest.raises(VoiceAuthError, match="tokens.refresh_token"):
        resolve_voice_bearer(auth)


def test_inspect_codex_auth_file_reports_expiry(tmp_path):
    path = tmp_path / "auth.json"
    exp_dt = datetime.now(timezone.utc) + timedelta(minutes=30)
    token = _jwt(exp=exp_dt)
    path.write_text(
        json.dumps({"tokens": {"access_token": token, "refresh_token": "refresh"}}),
        encoding="utf-8",
    )
    status = inspect_codex_auth_file(str(path))
    assert status.access_token == token
    assert status.expires_at == int(exp_dt.timestamp())
    assert status.refresh_token_present is True


@pytest.mark.asyncio
async def test_resolve_voice_bearer_async_uses_thread_wrapper(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-async")
    auth = APIKeyVoiceAuth(type="api_key")
    assert await resolve_voice_bearer_async(auth) == "sk-async"


def test_write_auth_json_is_atomic_if_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    original = {"tokens": {"access_token": "old"}}
    path.write_text(json.dumps(original), encoding="utf-8")

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr("receptionist.voice_auth._replace_file", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        _write_auth_json(path, {"tokens": {"access_token": "new"}})
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_resolve_oauth_codex_missing_file_raises(tmp_path):
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(tmp_path / "missing.json"))
    with pytest.raises(VoiceAuthError, match="file not found"):
        resolve_voice_bearer(auth)


def test_resolve_oauth_codex_bad_json_raises(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text("{not json", encoding="utf-8")
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    with pytest.raises(VoiceAuthError, match="not valid JSON"):
        resolve_voice_bearer(auth)


def test_resolve_oauth_codex_missing_access_token_raises(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"tokens": {}}), encoding="utf-8")
    auth = CodexOAuthVoiceAuth(type="oauth_codex", path=str(path))
    with pytest.raises(VoiceAuthError, match="tokens.access_token"):
        resolve_voice_bearer(auth)


def test_resolve_static_oauth_inline_token():
    auth = StaticOAuthVoiceAuth(type="oauth_static", token="oauth-token")
    assert resolve_voice_bearer(auth) == "oauth-token"


def test_resolve_static_oauth_token_env(monkeypatch):
    monkeypatch.setenv("OPENAI_OAUTH_TOKEN", "oauth-env-token")
    auth = StaticOAuthVoiceAuth(type="oauth_static", token_env="OPENAI_OAUTH_TOKEN")
    assert resolve_voice_bearer(auth) == "oauth-env-token"


def test_resolve_static_oauth_missing_token_env_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_OAUTH_TOKEN", raising=False)
    auth = StaticOAuthVoiceAuth(type="oauth_static", token_env="OPENAI_OAUTH_TOKEN")
    with pytest.raises(VoiceAuthError, match="OPENAI_OAUTH_TOKEN"):
        resolve_voice_bearer(auth)


def _jwt(*, exp: datetime) -> str:
    def encode(data: dict[str, object]) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return ".".join([
        encode({"alg": "none", "typ": "JWT"}),
        encode({"exp": int(exp.timestamp())}),
        "sig",
    ])
