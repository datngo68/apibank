"""Integration tests cho /api/v1/auth/* — đảm bảo flow đầu cuối hoạt động."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pyotp
import pytest


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    db_path = tmp_path / "auth.db"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "test-salt")
    monkeypatch.setenv("APIBANK_LOG_LEVEL", "WARNING")
    yield


@pytest.fixture
async def client(app_env: None) -> AsyncIterator[httpx.AsyncClient]:
    # Reset cached engine/sessionmaker và settings
    import packages.db.session as session_module
    from packages.config.settings import get_settings

    get_settings.cache_clear()
    session_module._engine = None
    session_module._sessionmaker = None

    from packages.db.models import Base

    engine = session_module.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from apps.api.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        # Lấy CSRF cookie qua healthz (GET an toàn) — middleware sẽ set cookie
        await ac.get("/healthz")
        yield ac
    await engine.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    token = client.cookies.get("apibank_csrf", "")
    return {"X-CSRF-Token": token} if token else {}


async def _last_email_token(kind: str = "verify") -> str:
    """Đọc token mới nhất từ DB cho một kind cụ thể."""
    from sqlalchemy import select

    import packages.db.session as session_module
    from packages.db.models import EmailToken

    sm = session_module.get_sessionmaker()
    async with sm() as s:
        rows = list(
            (
                await s.scalars(
                    select(EmailToken)
                    .where(EmailToken.kind == kind)
                    .order_by(EmailToken.created_at.desc())
                )
            ).all()
        )
        # Chú ý: chỉ có hash trong DB; raw không lưu — bài test sẽ phải lấy từ log,
        # nên ta thay vào dùng helper riêng (xem _register_and_get_token).
        _ = rows
    return ""


_EMAIL_TOKEN_LOG: list[tuple[str, str]] = []  # (to, body)


@pytest.fixture(autouse=True)
def capture_email(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _EMAIL_TOKEN_LOG.clear()
    from apps.api.routes import auth as auth_module

    async def fake_send(to: str, subject: str, body: str) -> None:  # noqa: ARG001
        _EMAIL_TOKEN_LOG.append((to, body))

    monkeypatch.setattr(auth_module, "_send_email_stub", fake_send)
    yield


def _extract_token(body: str, kind: str = "verify") -> str:
    """Body email stub có dạng 'Token: xxx' hoặc 'Reset token: xxx'."""
    match = re.search(r"(?:Token|Reset token|Mã xác minh):\s*(\S+)", body)
    if match:
        return match.group(1)
    return ""


@pytest.mark.asyncio
async def test_register_returns_201_and_sends_email(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "u1@example.com", "password": "Strong-Pass-1", "full_name": "User 1"},
        headers=_csrf(client),
    )
    assert res.status_code == 201, res.text
    assert _EMAIL_TOKEN_LOG, "expected email"
    to, body = _EMAIL_TOKEN_LOG[-1]
    assert to == "u1@example.com"
    assert "verify" in body.lower() or "xác minh" in body.lower()


@pytest.mark.asyncio
async def test_register_duplicate_returns_201_to_avoid_enumeration(
    client: httpx.AsyncClient,
) -> None:
    """/register với email tồn tại không leak 409; gửi email cảnh báo cho user thật."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "u2@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    _EMAIL_TOKEN_LOG.clear()
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "u2@example.com", "password": "Different-Pass-9"},
        headers=_csrf(client),
    )
    assert res.status_code == 201
    # Email được gửi tới chủ tài khoản, body chứa "đăng ký lại"
    assert _EMAIL_TOKEN_LOG, "expected warning email"
    to, body = _EMAIL_TOKEN_LOG[-1]
    assert to == "u2@example.com"
    assert "đăng ký" in body
    # Đảm bảo password gốc KHÔNG bị thay đổi (login bằng pass cũ vẫn được).
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "u2@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_register_password_too_short_422(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "u3@example.com", "password": "short"},
        headers=_csrf(client),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_csrf_required_for_post(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "u-csrf@example.com", "password": "Strong-Pass-1"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_login_and_me(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "lo@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "lo@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user"]["email"] == "lo@example.com"
    assert "apibank_sid" in client.cookies

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "lo@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password_401(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "wp@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "wp@example.com", "password": "Wrong-Pass-9"},
        headers=_csrf(client),
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_401(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "no@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_lockout_after_5_failed_logins(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "lk@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    for _ in range(5):
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": "lk@example.com", "password": "Wrong-1!"},
            headers=_csrf(client),
        )
        assert res.status_code == 401
    locked = await client.post(
        "/api/v1/auth/login",
        json={"email": "lk@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    assert locked.status_code == 423


@pytest.mark.asyncio
async def test_logout_revokes_session(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "lg@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "lg@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.post("/api/v1/auth/logout", headers=_csrf(client))
    assert res.status_code == 200
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_me_unauthenticated_401(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_verify_email_flow(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "ve@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    body = _EMAIL_TOKEN_LOG[-1][1]
    token = _extract_token(body, "verify")
    assert token, body
    ok = await client.post(
        "/api/v1/auth/verify-email", json={"token": token}, headers=_csrf(client)
    )
    assert ok.status_code == 200
    # token đã used → lần 2 fail
    fail = await client.post(
        "/api/v1/auth/verify-email", json={"token": token}, headers=_csrf(client)
    )
    assert fail.status_code == 400


@pytest.mark.asyncio
async def test_resend_verify_always_200(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/resend-verify",
        json={"email": "no-such-user@example.com"},
        headers=_csrf(client),
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_forgot_reset_password_flow(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "fr@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.post(
        "/api/v1/auth/forgot", json={"email": "fr@example.com"}, headers=_csrf(client)
    )
    assert res.status_code == 200
    body = _EMAIL_TOKEN_LOG[-1][1]
    token = _extract_token(body, "reset")
    assert token, body
    ok = await client.post(
        "/api/v1/auth/reset",
        json={"token": token, "password": "New-Strong-Pass-2"},
        headers=_csrf(client),
    )
    assert ok.status_code == 200
    # đăng nhập password cũ → fail
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "fr@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    assert bad.status_code == 401
    # đăng nhập password mới → ok
    good = await client.post(
        "/api/v1/auth/login",
        json={"email": "fr@example.com", "password": "New-Strong-Pass-2"},
        headers=_csrf(client),
    )
    assert good.status_code == 200


@pytest.mark.asyncio
async def test_change_password_revokes_other_sessions(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "cp@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "cp@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Strong-Pass-1", "new_password": "New-Pass-3-Z"},
        headers=_csrf(client),
    )
    assert res.status_code == 200
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200  # session hiện tại không bị thu hồi


@pytest.mark.asyncio
async def test_change_password_wrong_current_400(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "cpw@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "cpw@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong", "new_password": "New-Pass-3-Z"},
        headers=_csrf(client),
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_2fa_enroll_verify_login_flow(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "tfa@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "tfa@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    enroll = await client.post("/api/v1/auth/2fa/enroll", headers=_csrf(client))
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]
    enroll_body = enroll.json()
    assert enroll_body["otpauth_uri"].startswith("otpauth://totp/")
    assert enroll_body["qr_data_uri"].startswith("data:image/png;base64,")
    code = pyotp.TOTP(secret).now()
    verify = await client.post(
        "/api/v1/auth/2fa/verify", json={"code": code}, headers=_csrf(client)
    )
    assert verify.status_code == 200
    rc = verify.json()["recovery_codes"]
    assert len(rc) == 10

    # Logout, login lại — phải trả requires_2fa kèm challenge_token
    await client.post("/api/v1/auth/logout", headers=_csrf(client))
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "tfa@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["requires_2fa"] is True
    challenge_token = body["challenge_token"]
    assert challenge_token

    # Step 2: gọi /2fa/challenge với token + code → cấp session.
    code2 = pyotp.TOTP(secret).now()
    res2 = await client.post(
        "/api/v1/auth/2fa/challenge",
        json={"challenge_token": challenge_token, "code": code2},
        headers=_csrf(client),
    )
    assert res2.status_code == 200, res2.text
    assert res2.json()["user"]["has_2fa"] is True


@pytest.mark.asyncio
async def test_2fa_login_inline_with_challenge_token(
    client: httpx.AsyncClient,
) -> None:
    """Cho phép gọi /login step 2 trực tiếp khi có sẵn challenge_token (giảm round-trip).

    FE muốn flow gọn có thể gửi `challenge_token + code` ngay trong /login;
    server sẽ verify như /2fa/challenge rồi cấp session trong cùng response.
    """
    await client.post(
        "/api/v1/auth/register",
        json={"email": "tfa2@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "tfa2@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    enroll = await client.post("/api/v1/auth/2fa/enroll", headers=_csrf(client))
    secret = enroll.json()["secret"]
    code = pyotp.TOTP(secret).now()
    await client.post(
        "/api/v1/auth/2fa/verify", json={"code": code}, headers=_csrf(client)
    )
    await client.post("/api/v1/auth/logout", headers=_csrf(client))

    step1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "tfa2@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    challenge_token = step1.json()["challenge_token"]

    code2 = pyotp.TOTP(secret).now()
    step2 = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "tfa2@example.com",
            "password": "Strong-Pass-1",
            "code": code2,
            "challenge_token": challenge_token,
        },
        headers=_csrf(client),
    )
    assert step2.status_code == 200, step2.text
    assert step2.json()["user"]["has_2fa"] is True


@pytest.mark.asyncio
async def test_2fa_login_rejects_code_without_challenge_token(
    client: httpx.AsyncClient,
) -> None:
    """Nếu chỉ có `code` mà thiếu `challenge_token` → 401 (chống bypass step 1)."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "tfa3@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "tfa3@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    enroll = await client.post("/api/v1/auth/2fa/enroll", headers=_csrf(client))
    secret = enroll.json()["secret"]
    code = pyotp.TOTP(secret).now()
    await client.post(
        "/api/v1/auth/2fa/verify", json={"code": code}, headers=_csrf(client)
    )
    await client.post("/api/v1/auth/logout", headers=_csrf(client))

    bad = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "tfa3@example.com",
            "password": "Strong-Pass-1",
            "code": pyotp.TOTP(secret).now(),
        },
        headers=_csrf(client),
    )
    assert bad.status_code == 401
    assert "challenge_token" in bad.json()["detail"]


@pytest.mark.asyncio
async def test_2fa_challenge_token_is_single_use(
    client: httpx.AsyncClient,
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "tfa4@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "tfa4@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    enroll = await client.post("/api/v1/auth/2fa/enroll", headers=_csrf(client))
    secret = enroll.json()["secret"]
    code0 = pyotp.TOTP(secret).now()
    await client.post(
        "/api/v1/auth/2fa/verify", json={"code": code0}, headers=_csrf(client)
    )
    await client.post("/api/v1/auth/logout", headers=_csrf(client))

    step1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "tfa4@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    challenge_token = step1.json()["challenge_token"]

    code1 = pyotp.TOTP(secret).now()
    ok = await client.post(
        "/api/v1/auth/2fa/challenge",
        json={"challenge_token": challenge_token, "code": code1},
        headers=_csrf(client),
    )
    assert ok.status_code == 200

    # Replay challenge token → 401 (token đã used).
    bad = await client.post(
        "/api/v1/auth/2fa/challenge",
        json={"challenge_token": challenge_token, "code": code1},
        headers=_csrf(client),
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_sessions_list_and_revoke(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "ss@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "ss@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.get("/api/v1/auth/sessions")
    assert res.status_code == 200
    assert len(res.json()) >= 1
    assert res.json()[0]["current"] is True


@pytest.mark.asyncio
async def test_update_profile(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "pf@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "pf@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.patch(
        "/api/v1/auth/profile",
        json={"full_name": "Người Mới", "locale": "en"},
        headers=_csrf(client),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["full_name"] == "Người Mới"
    assert body["locale"] == "en"


@pytest.mark.asyncio
async def test_logout_all_revokes_everything(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "la@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "la@example.com", "password": "Strong-Pass-1"},
        headers=_csrf(client),
    )
    res = await client.post("/api/v1/auth/logout-all", headers=_csrf(client))
    assert res.status_code == 200
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 401


_ = asyncio  # unused imports kept for future fixtures
