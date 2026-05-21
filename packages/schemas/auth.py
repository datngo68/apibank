"""Pydantic schemas cho /api/v1/auth/* và /api/v1/me/*."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    captcha_token: str | None = Field(default=None, max_length=2048)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    code: str | None = Field(default=None, max_length=16)
    """code = TOTP hoặc recovery khi 2FA bật."""
    challenge_token: str | None = Field(default=None, max_length=128)
    """Token cấp ở step 1 khi 2FA bật. Bắt buộc nếu `code` được gửi kèm."""
    captcha_token: str | None = Field(default=None, max_length=2048)


class TwoFactorChallengeRequest(BaseModel):
    challenge_token: str = Field(min_length=10, max_length=128)
    code: str = Field(min_length=4, max_length=16)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    captcha_token: str | None = Field(default=None, max_length=2048)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10, max_length=128)


class ResendVerifyRequest(BaseModel):
    email: EmailStr


class TwoFactorEnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_data_uri: str


class TwoFactorVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class TwoFactorVerifyResponse(BaseModel):
    recovery_codes: list[str]


class TwoFactorDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str | None
    role: str
    status: str
    locale: str
    balance_vnd: Decimal
    email_verified_at: datetime | None
    has_2fa: bool = False
    telegram_chat_id: str | None = None
    last_login_at: datetime | None
    created_at: datetime

    @field_validator("balance_vnd", mode="before")
    @classmethod
    def _to_decimal(cls, v: Decimal | int | str | None) -> Decimal:
        if v is None:
            return Decimal(0)
        return Decimal(v)


class SessionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool = False


class AuthMeResponse(BaseModel):
    user: UserPublic
    requires_2fa: bool = False


class LoginResponse(BaseModel):
    user: UserPublic | None = None
    requires_2fa: bool = False
    challenge_token: str | None = None  # khi cần 2FA, FE dùng cho /2fa/challenge


class GenericMessage(BaseModel):
    message: str


class UpdateProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    locale: str | None = Field(default=None, pattern=r"^(vi|en)$")
    telegram_chat_id: str | None = Field(default=None, max_length=64)
