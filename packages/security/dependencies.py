"""Dependencies cho /v1/* endpoints (Bearer API key).

- `authenticated_api_key`: resolve raw key → ApiKey, cập nhật last_used_at/ip best-effort,
  enforce expires_at + revoked_at.
- `require_scope("orders:read")`: dependency factory check scope; admin scope (`admin:*`) bypass.
- `enforce_subscription_and_quota`: chặn endpoint /v1/* nếu user hết hạn subscription
  hoặc vượt quota plan.
- `enforce_resource_ownership`: helper kiểm `bank_account.user_id == api_key.user_id`
  (admin scope bypass) — dùng cho GET/cancel order, list transactions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config.settings import get_settings
from packages.db.models import ApiKey, BankAccount, Plan, User
from packages.db.session import get_sessionmaker
from packages.security.idempotency import resolve_api_key


async def authenticated_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
) -> ApiKey:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing api key")
    raw_key = authorization.removeprefix("Bearer ").strip()
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        api_key = await resolve_api_key(session, raw_key=raw_key, salt=settings.api_key_salt)
        if api_key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
        # Enforce expires_at: nếu hết hạn → 401 (resolve_api_key không kiểm hộ).
        expires_at = api_key.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < now:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="api key expired"
                )
        # Enforce IP allowlist nếu key có set.
        allowlist = list(getattr(api_key, "ip_allowlist_json", None) or [])
        client_host = request.client.host if request.client else None
        if allowlist and client_host:
            import ipaddress

            try:
                client_ip = ipaddress.ip_address(client_host)
            except ValueError:
                client_ip = None
            if client_ip is not None:
                allowed = False
                for cidr in allowlist:
                    try:
                        if client_ip in ipaddress.ip_network(cidr, strict=False):
                            allowed = True
                            break
                    except ValueError:
                        continue
                if not allowed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="ip not allowlisted for this api key",
                    )
        # Best-effort cập nhật last_used_at + last_used_ip.
        try:
            api_key.last_used_at = now
            if client_host:
                api_key.last_used_ip = client_host[:64]
            await session.commit()
        except Exception:  # noqa: BLE001 — không cản trở request nếu update fail
            await session.rollback()
    request.state.api_key_id = api_key.id
    return api_key


def require_scope(scope: str) -> Callable[..., Awaitable[ApiKey]]:
    """Dependency factory yêu cầu scope cụ thể (admin:* bypass).

    Trước đây hàm này có bug: dùng `api_key: ApiKey = authenticated_api_key`
    (không bọc Depends), khiến FastAPI nhận function reference làm giá trị mặc
    định thay vì resolve dependency → check scope không bao giờ chạy. Sửa lại
    bằng cách bọc Depends(...) chuẩn.
    """

    async def dependency(api_key: ApiKey = Depends(authenticated_api_key)) -> ApiKey:
        scopes = api_key.scopes or []
        if scope not in scopes and "admin:*" not in scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing scope")
        return api_key

    return dependency


async def enforce_subscription_and_quota(
    request: Request,
    api_key: ApiKey = Depends(authenticated_api_key),
) -> ApiKey:
    """Dùng cho endpoint /v1/* cần subscription active.

    - Admin scope (`admin:*`) bypass.
    - User_id của API key phải có Subscription active. Nếu chưa link user_id (legacy
      single-tenant) → bypass để giữ tương thích.
    - Tăng quota counter; trả 429 nếu vượt.
    """
    scopes = set(api_key.scopes or [])
    if "admin:*" in scopes:
        return api_key

    user_id = api_key.user_id
    if not user_id:
        return api_key

    from packages.billing import subscription as subscription_pkg
    from packages.billing.quota import get_quota_tracker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        sub = await subscription_pkg.get_active_subscription(session, user_id)
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="no active subscription",
            )
        plan = await session.get(Plan, sub.plan_id)
        limit_day = int(plan.daily_quota) if plan else 0
        limit_month = int(plan.monthly_quota) if plan else 0

    tracker = get_quota_tracker()
    status_quota = await tracker.hit(
        user_id, limit_day=limit_day, limit_month=limit_month
    )
    if status_quota.exceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="plan quota exceeded",
            headers={"X-RateLimit-Used": str(status_quota.used_today)},
        )

    request.state.user_id = user_id
    return api_key


async def assert_bank_account_owned(
    session: AsyncSession,
    api_key: ApiKey,
    bank_account_id: str,
) -> None:
    """Raise 404 nếu `bank_account_id` không thuộc user của api_key.

    Admin scope `admin:*` bypass kiểm tra này. API key legacy (chưa link user_id)
    cũng bypass để giữ tương thích single-tenant.
    """
    scopes = set(api_key.scopes or [])
    if "admin:*" in scopes or not api_key.user_id:
        return
    bank = await session.get(BankAccount, bank_account_id)
    if bank is None or bank.user_id != api_key.user_id:
        # Trả 404 (không 403) để không leak existence.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


# tránh import vòng cho legacy callers
_ = User
