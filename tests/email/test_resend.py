# tests/email/test_resend.py
from __future__ import annotations

import pytest
import respx
from httpx import Response

from receptionist.config import ResendConfig
from receptionist.email.sender import EmailSendError
from receptionist.email.resend import ResendSender


@pytest.mark.asyncio
@respx.mock
async def test_resend_posts_to_api():
    route = respx.post("https://api.resend.com/emails").mock(
        return_value=Response(200, json={"id": "abc-123"})
    )
    sender = ResendSender(ResendConfig(api_key="re_test"))
    await sender.send(
        from_="from@test", to=["to@test"], subject="Hi",
        body_text="body", body_html=None,
    )
    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer re_test"


@pytest.mark.asyncio
@respx.mock
async def test_resend_429_is_transient_with_retry_after():
    respx.post("https://api.resend.com/emails").mock(
        return_value=Response(429, headers={"Retry-After": "2"}, json={"message": "rate limited"})
    )
    sender = ResendSender(ResendConfig(api_key="re_test"))
    with pytest.raises(EmailSendError) as exc:
        await sender.send(
            from_="a@b", to=["c@d"], subject="s", body_text="t", body_html=None
        )
    assert exc.value.transient is True
    assert exc.value.retry_after == 2.0


@pytest.mark.asyncio
@respx.mock
async def test_resend_401_is_permanent():
    respx.post("https://api.resend.com/emails").mock(
        return_value=Response(401, json={"message": "unauthorized"})
    )
    sender = ResendSender(ResendConfig(api_key="re_bad"))
    with pytest.raises(EmailSendError) as exc:
        await sender.send(
            from_="a@b", to=["c@d"], subject="s", body_text="t", body_html=None
        )
    assert exc.value.transient is False


@pytest.mark.asyncio
@respx.mock
async def test_resend_5xx_is_transient():
    respx.post("https://api.resend.com/emails").mock(return_value=Response(503))
    sender = ResendSender(ResendConfig(api_key="re_test"))
    with pytest.raises(EmailSendError) as exc:
        await sender.send(
            from_="a@b", to=["c@d"], subject="s", body_text="t", body_html=None
        )
    assert exc.value.transient is True
