from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import ApiKey, BankAccount
from packages.db.repositories import OrderRepository
from packages.db.session import get_session
from packages.schemas.orders import OrderCreate, OrderRead
from packages.security.api_keys import hash_request
from packages.security.audit import record_audit
from packages.security.dependencies import (
    assert_bank_account_owned,
    enforce_subscription_and_quota,
)
from packages.security.idempotency import (
    build_idempotency_record,
    reuse_or_create_idempotent_response,
)

router = APIRouter(prefix="/orders", tags=["orders"])


def _require_scope(api_key: ApiKey, scope: str) -> None:
    scopes = api_key.scopes or []
    if scope not in scopes and "admin:*" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing scope")


async def _enforce_order_ownership(
    session: AsyncSession, api_key: ApiKey, order_bank_account_id: str
) -> None:
    """Trả 404 nếu order không thuộc user của api_key (admin:* bypass)."""
    scopes = set(api_key.scopes or [])
    if "admin:*" in scopes or not api_key.user_id:
        return
    bank = await session.get(BankAccount, order_bank_account_id)
    if bank is None or bank.user_id != api_key.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")


@router.post("", response_model=OrderRead)
async def create_order(
    payload: OrderCreate,
    request: Request,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> OrderRead:
    _require_scope(api_key, "orders:write")
    # Trước khi tạo order, đảm bảo bank_account thuộc user của api_key.
    await assert_bank_account_owned(session, api_key, payload.bank_account_id)

    request_hash = hash_request(payload.model_dump(mode="json"))
    try:
        existing = await reuse_or_create_idempotent_response(
            session,
            api_key_id=api_key.id,
            key=idempotency_key,
            request_hash=request_hash,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return OrderRead.model_validate(existing.response_json)

    repo = OrderRepository(session)
    order = await repo.create_order(payload, idempotency_key=idempotency_key)
    body = OrderRead.model_validate(order)
    session.add(
        build_idempotency_record(
            api_key_id=api_key.id,
            key=idempotency_key,
            request_hash=request_hash,
            response_payload=body.model_dump(mode="json"),
        )
    )
    await record_audit(
        session,
        actor=api_key.id,
        action="order.create",
        target_type="order",
        target_id=order.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        after=body.model_dump(mode="json"),
    )
    await session.commit()
    response.status_code = status.HTTP_201_CREATED
    return body


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: str,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> OrderRead:
    _require_scope(api_key, "orders:read")
    repo = OrderRepository(session)
    order = await repo.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    await _enforce_order_ownership(session, api_key, order.bank_account_id)
    return OrderRead.model_validate(order)


@router.post("/{order_id}:cancel", response_model=OrderRead)
async def cancel_order(
    order_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    api_key: ApiKey = Depends(enforce_subscription_and_quota),
) -> OrderRead:
    _require_scope(api_key, "orders:write")
    repo = OrderRepository(session)
    # Lookup trước khi cancel để check ownership.
    existing = await repo.get_order(order_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    await _enforce_order_ownership(session, api_key, existing.bank_account_id)
    order = await repo.cancel_order(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    await record_audit(
        session,
        actor=api_key.id,
        action="order.cancel",
        target_type="order",
        target_id=order.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        after={"status": order.status},
    )
    await session.commit()
    return OrderRead.model_validate(order)
