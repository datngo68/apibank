"""GET /v1/bank-accounts — list a user's bank accounts via Bearer API key.

Phân biệt với ``/api/v1/me/bank-accounts`` (dùng cookie session): route này
đứng dưới prefix ``/v1`` cùng với ``orders`` / ``transactions``, dùng API key
để third-party (vd 9router) có thể fetch danh sách bank account của user
trước khi tạo order — giúp UI tích hợp render dropdown thay vì bắt admin
paste UUID thủ công.

Scope mới ``bank_accounts:read``. ``admin:*`` bypass + thấy mọi bank account.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import ApiKey, BankAccount
from packages.db.session import get_session
from packages.schemas.me import BankAccountRead
from packages.security.dependencies import enforce_subscription_and_quota

router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


def _has_scope(api_key: ApiKey, scope: str) -> bool:
    scopes = set(api_key.scopes or [])
    return scope in scopes or "admin:*" in scopes


@router.get("", response_model=list[BankAccountRead])
async def list_bank_accounts(
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> list[BankAccountRead]:
    """List bank accounts visible to the API key's user.

    - Scope ``bank_accounts:read`` (or ``admin:*``) required.
    - Non-admin keys: chỉ thấy bank accounts của user gắn với key.
    - Admin keys (``admin:*``): thấy tất cả (dùng cho ops console / SDK admin).
    - Legacy keys không gắn user_id: bypass filter để giữ tương thích
      single-tenant trước Phase 2.
    """

    if not _has_scope(api_key, "bank_accounts:read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing scope")

    scopes = set(api_key.scopes or [])
    is_admin = "admin:*" in scopes

    stmt = (
        select(BankAccount)
        .where(BankAccount.status != "deleted")
        .order_by(BankAccount.created_at.desc())
    )
    if not is_admin and api_key.user_id:
        stmt = stmt.where(BankAccount.user_id == api_key.user_id)

    rows = list((await session.scalars(stmt)).all())
    return [BankAccountRead.model_validate(row, from_attributes=True) for row in rows]
