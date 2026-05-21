"""Settings APIBank.

Phân biệt rõ 2 secret độc lập:
- ``api_key_salt``: dùng để băm `ApiKey.key_hash` (HMAC-style salted SHA-256).
- ``session_secret_key``: dùng cho ``starlette.SessionMiddleware`` (cookie admin
  Jinja, OAuth google state). KHÔNG được trùng ``api_key_salt``.

Ở môi trường production (``environment in {"prod", "production"}``), validator
sẽ raise ngay khi boot nếu các secret còn để giá trị mặc định "CHANGE_ME" hoặc
quá ngắn (<32 ký tự). Mục đích: tránh deploy production bằng .env.example.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})

_WEAK_SECRET_HINTS = (
    "CHANGE_ME",
    "change_me",
    "dev-only",
    "changeme",
)
_MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APIBANK_", env_file=".env", extra="ignore")

    app_name: str = "APIBank"
    environment: str = "local"
    db_url: str = "sqlite+aiosqlite:///./apibank.db"
    redis_url: str = "redis://localhost:6379/0"
    fernet_keys: str = Field(default="")
    sentry_dsn: str | None = None
    log_level: str = "INFO"
    poll_interval: int = 20
    webhook_max_attempts: int = 7
    api_key_salt: str = "dev-only-change-me"
    session_secret_key: str = ""
    cookie_secure: bool | None = None
    mb_bridge_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    embed_workers: bool = False
    # Turnstile/hCaptcha: chỉ enforce khi `captcha_secret` set.
    captcha_provider: str = "turnstile"  # turnstile | hcaptcha
    captcha_site_key: str = ""
    captcha_secret: str = ""
    # Encrypt-at-rest cho PII (transactions.content, audit_log JSON). Tắt mặc
    # định ở dev/local để không vỡ test cũ. Bật bằng APIBANK_ENCRYPT_PII=true.
    encrypt_pii: bool = False
    # Audit log retention: số ngày giữ lại; > giá trị này sẽ bị purge bởi
    # job ``audit_log_retention_job`` (scheduler). 0 = không purge (mặc định).
    audit_log_retention_days: int = 0

    @model_validator(mode="after")
    def _post_validate(self) -> Settings:
        # Nếu admin chưa cấu hình session_secret_key, tự sinh từ api_key_salt
        # cho môi trường local (giữ tương thích ngược); ở production buộc phải set.
        env = (self.environment or "").lower()
        if not self.session_secret_key:
            if env in PRODUCTION_ENVIRONMENTS:
                raise ValueError(
                    "APIBANK_SESSION_SECRET_KEY is required in production "
                    "(use `apimb fernet generate` or `python -c \"import secrets; "
                    "print(secrets.token_urlsafe(48))\"`)."
                )
            # local/dev: dùng api_key_salt làm fallback một lần để không vỡ session cũ.
            object.__setattr__(self, "session_secret_key", self.api_key_salt)

        if env in PRODUCTION_ENVIRONMENTS:
            for name, value in (
                ("api_key_salt", self.api_key_salt),
                ("session_secret_key", self.session_secret_key),
            ):
                if any(hint in value for hint in _WEAK_SECRET_HINTS):
                    raise ValueError(
                        f"APIBANK_{name.upper()} chứa giá trị mặc định không an toàn "
                        f"({_WEAK_SECRET_HINTS!r}). Hãy đổi trước khi chạy production."
                    )
                if len(value) < _MIN_SECRET_LENGTH:
                    raise ValueError(
                        f"APIBANK_{name.upper()} phải có độ dài >= {_MIN_SECRET_LENGTH} ký tự "
                        f"trong production (hiện tại: {len(value)})."
                    )
            if not self.fernet_keys:
                raise ValueError(
                    "APIBANK_FERNET_KEYS bắt buộc trong production (dùng `apimb fernet generate`)."
                )

        # api_key_salt và session_secret_key phải KHÁC nhau để tránh cross-use:
        # ai biết salt sẽ không tự động giải được cookie session.
        if (
            env in PRODUCTION_ENVIRONMENTS
            and self.session_secret_key == self.api_key_salt
        ):
            raise ValueError(
                "APIBANK_SESSION_SECRET_KEY phải khác APIBANK_API_KEY_SALT trong production."
            )
        return self

    @property
    def is_production(self) -> bool:
        return (self.environment or "").lower() in PRODUCTION_ENVIRONMENTS

    @property
    def cookie_secure_effective(self) -> bool:
        """Cookie Secure flag đã resolve: nếu admin set rõ thì dùng, không thì auto theo env."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()
