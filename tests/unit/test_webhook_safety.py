"""Tests cho packages.webhook.is_safe_webhook_url + decrypt_webhook_secret."""

from __future__ import annotations

import pytest

from packages.config.settings import get_settings
from packages.webhook import (
    decrypt_webhook_secret,
    encrypt_webhook_secret,
    is_safe_webhook_url,
)


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    for key in list(__import__("os").environ):
        if key.startswith("APIBANK_"):
            monkeypatch.delenv(key, raising=False)


def _set_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "a" * 48)
    monkeypatch.setenv("APIBANK_SESSION_SECRET_KEY", "b" * 48)
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )


def test_url_safe_https_public_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod(monkeypatch)
    ok, reason = is_safe_webhook_url("https://example.com/hook")
    assert ok, reason


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/hook",
        "https://localhost/hook",
        "http://10.0.0.1/hook",
        "http://192.168.1.1/hook",
        "http://172.16.5.5/hook",
        "http://169.254.169.254/latest/meta-data/",  # AWS IMDS
        "http://[::1]/hook",
    ],
)
def test_url_unsafe_private_loopback_in_prod(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    _set_prod(monkeypatch)
    ok, reason = is_safe_webhook_url(url)
    assert not ok, f"{url} should be blocked"
    assert reason


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "",
        "https:///nohost",
    ],
)
def test_url_unsafe_scheme_or_empty(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    _set_prod(monkeypatch)
    ok, reason = is_safe_webhook_url(url)
    assert not ok
    assert reason


def test_url_dev_allows_localhost_but_blocks_imds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "local")
    ok_loop, _ = is_safe_webhook_url("http://127.0.0.1/x")
    assert ok_loop  # dev: loopback OK

    ok_imds, reason = is_safe_webhook_url("http://169.254.169.254/x")
    assert not ok_imds
    assert reason


def test_encrypt_secret_requires_fernet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    with pytest.raises(RuntimeError, match="FERNET_KEYS"):
        encrypt_webhook_secret("topsecret")


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    enc = encrypt_webhook_secret("topsecret")
    assert enc != "topsecret"
    assert decrypt_webhook_secret(enc) == "topsecret"


def test_decrypt_falls_back_when_value_is_plain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy data có thể là plain (silent fallback cũ); decrypt KHÔNG được crash."""
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    # Plain string không phải Fernet token → trả nguyên giá trị (caller cảnh báo).
    assert decrypt_webhook_secret("plain-legacy-secret") == "plain-legacy-secret"


def test_decrypt_no_fernet_returns_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    assert decrypt_webhook_secret("plain") == "plain"
