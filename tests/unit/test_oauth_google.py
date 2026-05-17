"""Unit tests cho packages.security.oauth_google.

Mock httpx token + userinfo endpoint qua respx, không gọi mạng thật.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from packages.security.oauth_google import (
    AUTH_URL,
    TOKEN_URL,
    USERINFO_URL,
    build_authorize_url,
    exchange_code,
)


def test_build_authorize_url_contains_required_params() -> None:
    url = build_authorize_url(
        "abc123",
        client_id="cid.apps.googleusercontent.com",
        redirect_uri="https://app.local/auth/google/callback",
    )
    assert url.startswith(AUTH_URL + "?")
    assert "client_id=cid.apps.googleusercontent.com" in url
    assert "state=abc123" in url
    assert "scope=openid+email+profile" in url
    assert "redirect_uri=https%3A%2F%2Fapp.local%2Fauth%2Fgoogle%2Fcallback" in url
    assert "response_type=code" in url


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_returns_userinfo() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1"})
    )
    respx.get(USERINFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "sub": "ggl-123",
                "email": "User@Example.COM",
                "email_verified": True,
                "name": "Người Dùng",
                "picture": "https://lh3.example.com/p.png",
            },
        )
    )
    info = await exchange_code(
        "auth-code-xyz",
        client_id="cid",
        client_secret="csecret",
        redirect_uri="https://app/cb",
    )
    assert info["sub"] == "ggl-123"
    # Email được lowercase
    assert info["email"] == "user@example.com"
    assert info["name"] == "Người Dùng"
    assert info["email_verified"] is True
    assert info["picture"].startswith("https://")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_raises_when_token_missing() -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(RuntimeError, match="missing access_token"):
        await exchange_code(
            "code",
            client_id="cid",
            client_secret="cs",
            redirect_uri="https://app/cb",
        )


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_propagates_http_error() -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(httpx.HTTPStatusError):
        await exchange_code(
            "bad",
            client_id="cid",
            client_secret="cs",
            redirect_uri="https://app/cb",
        )


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_treats_email_verified_false() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok"})
    )
    respx.get(USERINFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={"sub": "x", "email": "u@e.com", "email_verified": False, "name": "U"},
        )
    )
    info = await exchange_code(
        "c", client_id="cid", client_secret="cs", redirect_uri="https://app/cb"
    )
    assert info["email_verified"] is False
