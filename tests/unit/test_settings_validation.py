"""Tests cho packages.config.settings — strong-secret validator."""

from __future__ import annotations

import pytest

from packages.config.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    # Bỏ qua mọi env APIBANK_* sẵn có để test ổn định.
    for key in list(__import__("os").environ):
        if key.startswith("APIBANK_"):
            monkeypatch.delenv(key, raising=False)


def test_local_default_uses_api_key_salt_as_session_secret_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "local")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "dev-only-change-me")  # noqa: S105
    settings = Settings()
    assert settings.session_secret_key == "dev-only-change-me"
    assert settings.is_production is False
    assert settings.cookie_secure_effective is False


def test_production_rejects_default_change_me_salt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "CHANGE_ME_TOKEN_URLSAFE_48")  # noqa: S105
    monkeypatch.setenv("APIBANK_SESSION_SECRET_KEY", "x" * 48)  # noqa: S105
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    with pytest.raises(ValueError, match="API_KEY_SALT"):
        Settings()


def test_production_rejects_short_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "short")  # noqa: S105
    monkeypatch.setenv("APIBANK_SESSION_SECRET_KEY", "y" * 48)  # noqa: S105
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    with pytest.raises(ValueError, match=">= 32"):
        Settings()


def test_production_rejects_missing_session_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "z" * 48)  # noqa: S105
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    monkeypatch.delenv("APIBANK_SESSION_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="SESSION_SECRET_KEY"):
        Settings()


def test_production_rejects_missing_fernet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "a" * 48)  # noqa: S105
    monkeypatch.setenv("APIBANK_SESSION_SECRET_KEY", "b" * 48)  # noqa: S105
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    with pytest.raises(ValueError, match="FERNET_KEYS"):
        Settings()


def test_production_rejects_session_secret_equal_api_key_salt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    same = "k" * 48
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", same)  # noqa: S105
    monkeypatch.setenv("APIBANK_SESSION_SECRET_KEY", same)  # noqa: S105
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    with pytest.raises(ValueError, match="khác"):
        Settings()


def test_production_accepts_strong_distinct_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "production")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "salt-" + "x" * 48)  # noqa: S105
    monkeypatch.setenv("APIBANK_SESSION_SECRET_KEY", "sess-" + "y" * 48)  # noqa: S105
    monkeypatch.setenv(
        "APIBANK_FERNET_KEYS",
        "primary:NhnFbDTpYks-q2AmJsBhuG_iL6VDaKL14L4vy44ZqkM=",
    )
    settings = Settings()
    assert settings.is_production is True
    assert settings.cookie_secure_effective is True


def test_cookie_secure_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIBANK_ENVIRONMENT", "local")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "dev-only-change-me")  # noqa: S105
    monkeypatch.setenv("APIBANK_COOKIE_SECURE", "true")
    settings = Settings()
    assert settings.cookie_secure_effective is True
