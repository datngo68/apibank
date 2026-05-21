"""Routes /api/v1/auth/* — đăng ký, đăng nhập, 2FA, sessions, password.

Mọi route ở đây dùng cookie session (không phải Bearer API key). FE gọi bằng
fetch(..., {credentials: "include"}) và gửi header X-CSRF-Token.

Email gửi đi (verify, reset) hiện ghi log + console; production sẽ thay bằng SMTP
ở Phase 2.9.
"""

from __future__ import annotations

import secrets as _secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.db.models import (
    EmailToken,
    OAuthIdentity,
    TwoFactor,
    User,
)
from packages.db.models import (
    Session as SessionModel,
)
from packages.db.session import get_session
from packages.schemas.auth import (
    AuthMeResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    GenericMessage,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    ResendVerifyRequest,
    ResetPasswordRequest,
    SessionInfo,
    TwoFactorChallengeRequest,
    TwoFactorDisableRequest,
    TwoFactorEnrollResponse,
    TwoFactorVerifyRequest,
    TwoFactorVerifyResponse,
    UpdateProfileRequest,
    UserPublic,
    VerifyEmailRequest,
)
from packages.security import oauth_google
from packages.security.audit import record_audit
from packages.security.captcha import verify_captcha
from packages.security.email_tokens import (
    KIND_RESET,
    KIND_VERIFY,
    consume_email_token,
    issue_email_token,
)
from packages.security.passwords import hash_password, needs_rehash, verify_password
from packages.security.rate_limit import InMemoryRateLimiter
from packages.security.sessions import (
    COOKIE_NAME,
    issue_session,
    revoke_all_sessions,
    revoke_session,
)
from packages.security.tokens import generate_token, hash_token
from packages.security.twofa import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    provisioning_qr_data_uri,
    provisioning_uri,
    verify_recovery_code,
    verify_totp,
)
from packages.security.user_auth import current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

LOGIN_LOCKOUT_THRESHOLD = 5
# Exponential backoff lock duration theo số lần fail liên tiếp (>= threshold).
# Index = (failed_login_count - LOGIN_LOCKOUT_THRESHOLD), cap ở slot cuối.
LOGIN_LOCKOUT_DURATIONS: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=24),
)
# Tương thích test cũ: alias cho slot cũ.
LOGIN_LOCKOUT_DURATION = timedelta(minutes=15)
PENDING_2FA_TTL = timedelta(minutes=5)
TOTP_REPLAY_WINDOW = timedelta(seconds=90)
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30

# Rate-limit theo email cho các endpoint nhạy cảm: capacity hits / 60s window.
_AUTH_RL_CAPACITY = 10
_auth_email_limiter = InMemoryRateLimiter(capacity=_AUTH_RL_CAPACITY, window_seconds=60)
# Per-IP cho register/forgot/login: chặn 1 IP rotate qua nhiều email.
_AUTH_IP_RL_CAPACITY = 30
_auth_ip_limiter = InMemoryRateLimiter(
    capacity=_AUTH_IP_RL_CAPACITY, window_seconds=60
)


async def _enforce_auth_rate_limit(action: str, email: str) -> None:
    """Throw 429 nếu user/IP spam endpoint /login, /forgot, /2fa/*, /register theo email.

    Dùng InMemoryRateLimiter (per-process) — single-host đủ; đa-host nên thay
    bằng Redis bucket riêng hoặc dùng RateLimitMiddleware identifier theo email.
    """
    decision = await _auth_email_limiter.hit(f"auth:{action}:{email.lower()}")
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many auth attempts; try again later",
            headers={"Retry-After": str(int(decision.retry_after_seconds))},
        )


async def _enforce_ip_rate_limit(action: str, ip: str | None) -> None:
    """Throw 429 khi 1 IP gọi register/forgot/login quá nhiều (chặn bot rotate email)."""
    if not ip:
        return
    decision = await _auth_ip_limiter.hit(f"auth-ip:{action}:{ip}")
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests from this IP",
            headers={"Retry-After": str(int(decision.retry_after_seconds))},
        )


def _next_lockout_duration(failed_count: int) -> timedelta:
    over = max(0, failed_count - LOGIN_LOCKOUT_THRESHOLD)
    idx = min(over, len(LOGIN_LOCKOUT_DURATIONS) - 1)
    return LOGIN_LOCKOUT_DURATIONS[idx]


def _set_session_cookie(response: Response, raw: str, *, secure: bool | None = None) -> None:
    if secure is None:
        secure = get_settings().cookie_secure_effective
    response.set_cookie(
        COOKIE_NAME,
        raw,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def _user_has_2fa(session: AsyncSession, user: User) -> bool:
    twofa = await session.get(TwoFactor, user.id)
    return twofa is not None and twofa.enabled_at is not None


async def _build_user_public(session: AsyncSession, user: User) -> UserPublic:
    has_2fa = await _user_has_2fa(session, user)
    payload = UserPublic.model_validate(user, from_attributes=True)
    payload.has_2fa = has_2fa
    return payload


async def _send_email_stub(to: str, subject: str, body: str) -> None:
    """Gửi email qua SMTP (đọc cấu hình từ AppConfig hoặc .env).

    Tên giữ nguyên để tương thích với fixture test cũ (monkeypatch). Khi SMTP
    chưa cấu hình, send_email log warning + return False (KHÔNG log token plain).
    Tên hàm sẽ được rename trong refactor sau khi fixture test được cập nhật.
    """
    from packages.notifications.email import send_email

    await send_email(to=to, subject=subject, body=body)


# ---------------------------------------------------------------------------
# REGISTER
# ---------------------------------------------------------------------------


@router.post("/register", response_model=GenericMessage, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    email = payload.email.lower().strip()
    await verify_captcha(
        payload.captcha_token,
        remote_ip=request.client.host if request.client else None,
    )
    await _enforce_auth_rate_limit("register", email)
    await _enforce_ip_rate_limit(
        "register", request.client.host if request.client else None
    )
    existing = (await session.scalars(select(User).where(User.email == email))).first()
    if existing is not None:
        # Tránh leak account đã tồn tại — luôn trả 201 generic và gửi email
        # cảnh báo cho chủ tài khoản. Anti-enumeration.
        if existing.status == "active":
            await _send_email_stub(
                email,
                "Cố gắng đăng ký lại APIBank",
                (
                    "Có người vừa thử đăng ký bằng email của bạn trên APIBank. "
                    "Nếu là bạn, hãy đăng nhập hoặc dùng /forgot để đặt lại mật khẩu. "
                    "Nếu không phải bạn, vui lòng bỏ qua email này."
                ),
            )
        return GenericMessage(message="registered; check email to verify")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=(payload.full_name or "").strip() or None,
        role="user",
        status="active",
    )
    session.add(user)
    await session.flush()
    raw, _ = await issue_email_token(session, user, KIND_VERIFY)
    await record_audit(
        session,
        actor=user.id,
        action="auth.register",
        target_type="user",
        target_id=user.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    await _send_email_stub(
        email,
        "Xác minh email APIBank",
        (
            "Chào mừng bạn đến với APIBank.\n\n"
            f"Mã xác minh: {raw}\n"
            f"Link xác minh: /verify-email?token={raw}\n\n"
            "Link có hiệu lực 48 giờ."
        ),
    )
    return GenericMessage(message="registered; check email to verify")


# ---------------------------------------------------------------------------
# LOGIN / 2FA
# ---------------------------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    email = payload.email.lower().strip()
    await _enforce_auth_rate_limit("login", email)
    await _enforce_ip_rate_limit(
        "login", request.client.host if request.client else None
    )
    # CAPTCHA chỉ enforce sau khi đã có failed_login_count > 0 ở email này;
    # với account chưa fail thì verify chỉ pass-through (token có thể null).
    user = (await session.scalars(select(User).where(User.email == email))).first()
    now = datetime.now(UTC)

    if user is None or user.status != "active":
        # tránh leak email tồn tại
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    # Sau N lần fail trước đó, ép captcha. Tránh phiền user mỗi lần login bình
    # thường nhưng vẫn chống brute-force.
    if user.failed_login_count >= 3:
        await verify_captcha(
            payload.captcha_token,
            remote_ip=request.client.host if request.client else None,
        )

    locked_until = user.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    if locked_until is not None and locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED, detail="account temporarily locked"
        )

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= LOGIN_LOCKOUT_THRESHOLD:
            # Exponential backoff — KHÔNG reset failed_login_count để tổng số lần
            # fail vẫn được nhớ qua các chu kỳ lock.
            user.locked_until = now + _next_lockout_duration(user.failed_login_count)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    if await _user_has_2fa(session, user):
        if not payload.code:
            # Step 1 — phát hành challenge token (single-use, ngắn hạn) lưu vào
            # `email_tokens` kind=2fa. FE phải gửi lại token + code ở step 2.
            raw_challenge = generate_token(24)
            session.add(
                EmailToken(
                    user_id=user.id,
                    kind="2fa",
                    token_hash=hash_token(raw_challenge),
                    expires_at=now + PENDING_2FA_TTL,
                    created_at=now,
                )
            )
            await session.commit()
            return LoginResponse(requires_2fa=True, challenge_token=raw_challenge)
        # Step 2 — phải có challenge_token; verify nó single-use trước khi TOTP.
        if not payload.challenge_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing challenge_token",
            )
        challenge = await _consume_2fa_challenge(session, user, payload.challenge_token)
        if challenge is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or expired challenge_token",
            )
        if not await _verify_2fa_code(session, user, payload.code):
            # rollback used_at để user còn cơ hội thử lại trong cửa sổ TTL —
            # đếm số lần fail vào failed_login_count để brute-force vẫn bị lock.
            user.failed_login_count += 1
            if user.failed_login_count >= LOGIN_LOCKOUT_THRESHOLD:
                user.locked_until = now + _next_lockout_duration(user.failed_login_count)
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid 2fa code"
            )

    raw, sess = await issue_session(
        session,
        user,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    user.last_login_at = now
    user.failed_login_count = 0
    user.locked_until = None
    await record_audit(
        session,
        actor=user.id,
        action="auth.login",
        target_type="user",
        target_id=user.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        after={"session_id": sess.id},
    )
    await session.commit()
    _set_session_cookie(response, raw)
    return LoginResponse(user=await _build_user_public(session, user))


@router.post("/2fa/challenge", response_model=LoginResponse)
async def two_factor_challenge(
    payload: TwoFactorChallengeRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    """Hoàn tất login khi 2FA bật.

    Bước 1: client POST `/login` (không kèm `code`) → server trả `challenge_token`.
    Bước 2: client POST `/2fa/challenge` với `challenge_token` + `code` (TOTP hoặc
    recovery). Server verify token (single-use, TTL 5 phút) + code, rồi cấp session
    cookie như login thành công.
    """
    digest = hash_token(payload.challenge_token)
    record = (
        await session.scalars(
            select(EmailToken)
            .where(EmailToken.token_hash == digest)
            .where(EmailToken.kind == "2fa")
        )
    ).first()
    if record is None or record.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired challenge_token",
        )
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if expires < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired challenge_token",
        )
    user = await session.get(User, record.user_id)
    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )
    record.used_at = now
    if not await _verify_2fa_code(session, user, payload.code):
        user.failed_login_count += 1
        if user.failed_login_count >= LOGIN_LOCKOUT_THRESHOLD:
            user.locked_until = now + _next_lockout_duration(user.failed_login_count)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid 2fa code"
        )

    raw, sess = await issue_session(
        session,
        user,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    user.last_login_at = now
    user.failed_login_count = 0
    user.locked_until = None
    await record_audit(
        session,
        actor=user.id,
        action="auth.login_2fa",
        target_type="user",
        target_id=user.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        after={"session_id": sess.id},
    )
    await session.commit()
    _set_session_cookie(response, raw)
    return LoginResponse(user=await _build_user_public(session, user))


async def _consume_2fa_challenge(
    session: AsyncSession, user: User, raw_token: str
) -> EmailToken | None:
    """Verify + mark used `2fa` challenge token gắn với user. Trả record hoặc None."""
    digest = hash_token(raw_token)
    record = (
        await session.scalars(
            select(EmailToken)
            .where(EmailToken.token_hash == digest)
            .where(EmailToken.kind == "2fa")
            .where(EmailToken.user_id == user.id)
        )
    ).first()
    if record is None or record.used_at is not None:
        return None
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return None
    record.used_at = datetime.now(UTC)
    return record


async def _verify_2fa_code(session: AsyncSession, user: User, code: str) -> bool:
    twofa = await session.get(TwoFactor, user.id)
    if twofa is None or twofa.enabled_at is None:
        return False
    code = code.strip()
    if verify_totp(twofa.secret_enc, code):
        # Anti-replay: từ chối cùng 1 TOTP code trong cửa sổ 90s (cover ±30s
        # valid_window mặc định của verify_totp).
        last_used_at = twofa.last_totp_used_at
        if last_used_at is not None and last_used_at.tzinfo is None:
            last_used_at = last_used_at.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if (
            twofa.last_totp_code == code
            and last_used_at is not None
            and (now - last_used_at) < TOTP_REPLAY_WINDOW
        ):
            return False
        twofa.last_totp_code = code
        twofa.last_totp_used_at = now
        return True
    # thử recovery
    codes: dict[str, str] = dict(twofa.recovery_codes_enc or {})
    for key, hashed in list(codes.items()):
        if codes.get(key) == "USED":
            continue
        if verify_recovery_code(code.upper(), hashed):
            codes[key] = "USED"
            twofa.recovery_codes_enc = codes
            return True
    return False


# ---------------------------------------------------------------------------
# LOGOUT / ME
# ---------------------------------------------------------------------------


@router.post("/logout", response_model=GenericMessage)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    sid = getattr(request.state, "session_id", None)
    if sid:
        await revoke_session(session, sid)
        await session.commit()
    _clear_session_cookie(response)
    return GenericMessage(message="ok")


@router.post("/logout-all", response_model=GenericMessage)
async def logout_all(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    await revoke_all_sessions(session, user.id)
    await session.commit()
    _clear_session_cookie(response)
    return GenericMessage(message="ok")


@router.get("/me", response_model=AuthMeResponse)
async def me(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> AuthMeResponse:
    return AuthMeResponse(user=await _build_user_public(session, user))


# ---------------------------------------------------------------------------
# EMAIL VERIFY
# ---------------------------------------------------------------------------


@router.post("/verify-email", response_model=GenericMessage)
async def verify_email(
    payload: VerifyEmailRequest,
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    user = await consume_email_token(session, payload.token, KIND_VERIFY)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid token")
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    await session.commit()
    return GenericMessage(message="email verified")


@router.post("/resend-verify", response_model=GenericMessage)
async def resend_verify(
    payload: ResendVerifyRequest,
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    email = payload.email.lower()
    await _enforce_auth_rate_limit("resend_verify", email)
    user = (
        await session.scalars(select(User).where(User.email == email))
    ).first()
    if user is None or user.email_verified_at is not None:
        return GenericMessage(message="ok")  # luôn 200 để không leak
    raw, _ = await issue_email_token(session, user, KIND_VERIFY)
    await session.commit()
    await _send_email_stub(
        user.email,
        "Xác minh email APIBank",
        (
            "Bạn vừa yêu cầu gửi lại mã xác minh email.\n\n"
            f"Mã: {raw}\nLink: /verify-email?token={raw}\n\n"
            "Link có hiệu lực 48 giờ."
        ),
    )
    return GenericMessage(message="ok")


# ---------------------------------------------------------------------------
# PASSWORD RESET
# ---------------------------------------------------------------------------


@router.post("/forgot", response_model=GenericMessage)
async def forgot(
    payload: ForgotPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    email = payload.email.lower()
    await verify_captcha(
        payload.captcha_token,
        remote_ip=request.client.host if request.client else None,
    )
    await _enforce_auth_rate_limit("forgot", email)
    await _enforce_ip_rate_limit(
        "forgot", request.client.host if request.client else None
    )
    user = (
        await session.scalars(select(User).where(User.email == email))
    ).first()
    if user is not None and user.status == "active":
        raw, _ = await issue_email_token(session, user, KIND_RESET)
        await session.commit()
        await _send_email_stub(
            user.email,
            "Đặt lại mật khẩu APIBank",
            (
                "Bạn vừa yêu cầu đặt lại mật khẩu.\n\n"
                f"Reset token: {raw}\n"
                f"Link: /reset-password?token={raw}\n\n"
                "Link có hiệu lực 1 giờ. Nếu bạn không yêu cầu, vui lòng bỏ qua."
            ),
        )
    return GenericMessage(message="ok")  # luôn 200


@router.post("/reset", response_model=GenericMessage)
async def reset(
    payload: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    user = await consume_email_token(session, payload.token, KIND_RESET)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid token")
    user.password_hash = hash_password(payload.password)
    user.failed_login_count = 0
    user.locked_until = None
    # Revoke mọi session sau khi đổi mật khẩu
    await revoke_all_sessions(session, user.id)
    await session.commit()
    return GenericMessage(message="password updated")


@router.post("/change-password", response_model=GenericMessage)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="current password incorrect"
        )
    user.password_hash = hash_password(payload.new_password)
    sid = getattr(request.state, "session_id", None)
    await revoke_all_sessions(session, user.id, except_id=sid)
    await record_audit(
        session,
        actor=user.id,
        action="auth.password_change",
        target_type="user",
        target_id=user.id,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    _ = response  # giữ session hiện tại
    return GenericMessage(message="password changed")


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------


@router.post("/2fa/enroll", response_model=TwoFactorEnrollResponse)
async def enroll_2fa(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> TwoFactorEnrollResponse:
    existing = await session.get(TwoFactor, user.id)
    if existing is not None and existing.enabled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="2fa already enabled"
        )
    secret = generate_totp_secret()
    if existing is None:
        session.add(TwoFactor(user_id=user.id, secret_enc=secret, recovery_codes_enc={}))
    else:
        existing.secret_enc = secret
    await session.commit()
    otpauth = provisioning_uri(secret, account=user.email)
    return TwoFactorEnrollResponse(
        secret=secret,
        otpauth_uri=otpauth,
        qr_data_uri=provisioning_qr_data_uri(otpauth),
    )


@router.post("/2fa/verify", response_model=TwoFactorVerifyResponse)
async def verify_2fa(
    payload: TwoFactorVerifyRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> TwoFactorVerifyResponse:
    twofa = await session.get(TwoFactor, user.id)
    if twofa is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="enroll first")
    if not verify_totp(twofa.secret_enc, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid code")
    twofa.enabled_at = datetime.now(UTC)
    raw_codes = generate_recovery_codes(10)
    twofa.recovery_codes_enc = {f"rc_{i}": hash_recovery_code(c) for i, c in enumerate(raw_codes)}
    await record_audit(
        session,
        actor=user.id,
        action="auth.2fa_enable",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return TwoFactorVerifyResponse(recovery_codes=raw_codes)


@router.post("/2fa/disable", response_model=GenericMessage)
async def disable_2fa(
    payload: TwoFactorDisableRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="password incorrect"
        )
    twofa = await session.get(TwoFactor, user.id)
    if twofa is not None:
        await session.delete(twofa)
    await record_audit(
        session,
        actor=user.id,
        action="auth.2fa_disable",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return GenericMessage(message="2fa disabled")


# ---------------------------------------------------------------------------
# SESSIONS list / revoke
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SessionInfo]:
    rows = list(
        (
            await session.scalars(
                select(SessionModel)
                .where(SessionModel.user_id == user.id)
                .where(SessionModel.revoked_at.is_(None))
                .order_by(SessionModel.last_seen_at.desc())
            )
        ).all()
    )
    sid = getattr(request.state, "session_id", None)
    out: list[SessionInfo] = []
    for row in rows:
        info = SessionInfo.model_validate(row, from_attributes=True)
        info.current = row.id == sid
        out.append(info)
    return out


@router.delete("/sessions/{session_id}", response_model=GenericMessage)
async def delete_session(
    session_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    target = await session.get(SessionModel, session_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if target.revoked_at is None:
        await revoke_session(session, target.id)
        await session.commit()
    return GenericMessage(message="revoked")


# ---------------------------------------------------------------------------
# PROFILE update
# ---------------------------------------------------------------------------


@router.patch("/profile", response_model=UserPublic)
async def update_profile(
    payload: UpdateProfileRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> UserPublic:
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip() or None
    if payload.locale is not None:
        user.locale = payload.locale
    if payload.telegram_chat_id is not None:
        user.telegram_chat_id = payload.telegram_chat_id.strip() or None
    await session.commit()
    return await _build_user_public(session, user)


# Future: OAuth Google routes added when client_id provided
_ = OAuthIdentity  # giữ import để mypy không kêu


# ---------------------------------------------------------------------------
# USER TELEGRAM LINK (cho profile cá nhân)
# ---------------------------------------------------------------------------

KIND_USER_TG_LINK = "user_tg_link"


@router.post("/profile/telegram/link-chat")
async def link_user_telegram(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str | int]:
    """Sinh deep-link token để user link Telegram cá nhân.

    User mở link → bot xử lý `/start <token>` → set User.telegram_chat_id.
    Token TTL 10 phút, single-use.
    """
    from datetime import timedelta as _td

    from packages.config import runtime as _runtime
    from packages.db.models import EmailToken as _EmailToken
    from packages.db.models import utcnow as _utcnow
    from packages.notifications import telegram as _tg
    from packages.security.tokens import (
        generate_token as _gen_token,
    )
    from packages.security.tokens import (
        hash_token as _hash_token,
    )

    cfg = await _tg.resolve_telegram(session)
    if not cfg["configured"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="telegram bot not configured",
        )
    token = cfg["token"]
    bot_username = cfg.get("bot_username") or ""
    if not bot_username:
        info = await _tg.get_me(token)
        if info.get("ok"):
            bot_username = (info.get("result") or {}).get("username") or ""
            cfg_raw = await _runtime.get_config(session, _tg.TELEGRAM_KEY)
            cfg_raw["bot_username"] = bot_username
            await _runtime.set_config(
                session,
                _tg.TELEGRAM_KEY,
                cfg_raw,
                actor_id=user.id,
                encrypt_fields=_tg.TELEGRAM_ENCRYPTED_FIELDS,
            )
    if not bot_username:
        raise HTTPException(status_code=502, detail="cannot resolve bot username")

    raw = _gen_token(20)
    record = _EmailToken(
        user_id=user.id,
        kind=KIND_USER_TG_LINK,
        token_hash=_hash_token(raw),
        expires_at=_utcnow() + _td(minutes=10),
    )
    session.add(record)
    await session.commit()
    return {
        "deep_link_url": f"https://t.me/{bot_username}?start={raw}",
        "token": raw,
        "expires_in": 600,
    }


@router.delete("/profile/telegram", response_model=GenericMessage)
async def unlink_user_telegram(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> GenericMessage:
    user.telegram_chat_id = None
    await record_audit(
        session,
        actor=user.id,
        action="user.telegram.unlink",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return GenericMessage(message="unlinked")


# ---------------------------------------------------------------------------
# GOOGLE OAUTH
# ---------------------------------------------------------------------------


_GOOGLE_STATE_COOKIE = "apibank_google_state"
_GOOGLE_STATE_TTL = 600  # giây


@router.get("/google/status", response_model=dict[str, bool])
async def google_status(
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    cfg = await oauth_google.get_oauth_config(session)
    return {
        "enabled": bool(
            cfg["enabled"] and cfg["client_id"] and cfg["redirect_uri"]
        )
    }


@router.get("/captcha-config")
async def captcha_config_endpoint() -> dict[str, str | bool]:
    """Public config (site_key + provider) cho FE render widget."""
    from packages.security.captcha import captcha_public_config

    return captcha_public_config()


@router.get("/google/login")
async def google_login(
    session: AsyncSession = Depends(get_session),
) -> Response:
    cfg = await oauth_google.get_oauth_config(session)
    if not cfg["enabled"] or not cfg["client_id"] or not cfg["redirect_uri"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="google oauth disabled",
        )
    state = _secrets.token_urlsafe(24)
    url = oauth_google.build_authorize_url(
        state, client_id=cfg["client_id"], redirect_uri=cfg["redirect_uri"]
    )
    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        _GOOGLE_STATE_COOKIE,
        state,
        max_age=_GOOGLE_STATE_TTL,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure_effective,
        path="/",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return RedirectResponse(
            url=f"/login?google_error={error}", status_code=302
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing code or state",
        )
    expected_state = request.cookies.get(_GOOGLE_STATE_COOKIE)
    if not expected_state or expected_state != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid state"
        )

    cfg = await oauth_google.get_oauth_config(session)
    if not cfg["enabled"]:
        raise HTTPException(status_code=404, detail="google oauth disabled")

    try:
        info = await oauth_google.exchange_code(
            code,
            client_id=cfg["client_id"],
            client_secret=cfg["client_secret"],
            redirect_uri=cfg["redirect_uri"],
        )
    except Exception as exc:  # noqa: BLE001
        _ = exc
        return RedirectResponse(
            url="/login?google_error=exchange_failed", status_code=302
        )

    sub = info.get("sub")
    email = info.get("email")
    if not sub or not email:
        raise HTTPException(status_code=400, detail="invalid google profile")

    # Tìm OAuthIdentity hoặc User theo email
    identity = (
        await session.scalars(
            select(OAuthIdentity)
            .where(OAuthIdentity.provider == "google")
            .where(OAuthIdentity.subject == sub)
        )
    ).first()

    user: User | None = None
    if identity is not None:
        user = await session.get(User, identity.user_id)
    if user is None:
        user = (
            await session.scalars(select(User).where(User.email == email))
        ).first()

    now = datetime.now(UTC)
    if user is None:
        user = User(
            email=email,
            password_hash="!oauth",  # placeholder, không dùng để login bằng password
            full_name=info.get("name"),
            role="user",
            status="active",
            email_verified_at=now if info.get("email_verified") else None,
        )
        session.add(user)
        await session.flush()

    if identity is None:
        session.add(
            OAuthIdentity(
                user_id=user.id,
                provider="google",
                subject=sub,
                email=email,
            )
        )

    if info.get("email_verified") and user.email_verified_at is None:
        user.email_verified_at = now

    raw, sess = await issue_session(
        session,
        user,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    user.last_login_at = now
    user.failed_login_count = 0
    user.locked_until = None
    await record_audit(
        session,
        actor=user.id,
        action="auth.google_login",
        target_type="user",
        target_id=user.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        after={"session_id": sess.id, "sub": sub},
    )
    await session.commit()

    response = RedirectResponse(url="/app", status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        raw,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure_effective,
        path="/",
    )
    response.delete_cookie(_GOOGLE_STATE_COOKIE, path="/")
    return response
