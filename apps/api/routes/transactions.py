from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import ApiKey
from packages.db.repositories import TransactionRepository
from packages.db.session import get_session
from packages.schemas.transactions import TransactionRead
from packages.security.dependencies import (
    assert_bank_account_owned,
    enforce_subscription_and_quota,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionRead])
async def list_transactions(
    request: Request,
    from_: datetime | None = None,
    to: datetime | None = None,
    account: str | None = None,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> list[TransactionRead]:
    _ = request
    scopes = api_key.scopes or []
    if "transactions:read" not in scopes and "admin:*" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing scope")

    # Filter theo user_id của API key (admin:* bypass; legacy api_key chưa link
    # user_id cũng bypass để giữ tương thích single-tenant).
    is_admin = "admin:*" in scopes
    user_id_filter: str | None = None
    if not is_admin and api_key.user_id:
        user_id_filter = api_key.user_id
        if account is not None:
            await assert_bank_account_owned(session, api_key, account)

    repo = TransactionRepository(session)
    rows = await repo.list_transactions(
        from_=from_, to=to, account=account, user_id=user_id_filter
    )
    return [TransactionRead.model_validate(row) for row in rows]
