"""Wallet ledger.

Quy ước:
- `User.balance_vnd` là cache balance hiện tại; nguồn chân lý là `WalletTransaction`.
- Mỗi credit/debit là 1 row có `idempotency_key` UNIQUE để re-call an toàn.
- Tất cả thao tác phải nằm trong cùng AsyncSession; caller chịu trách nhiệm commit
  và xử lý concurrency. Trên Postgres sẽ thêm `SELECT ... FOR UPDATE` (skip với
  SQLite vì SQLite serialize sẵn). Async SQLAlchemy fallback an toàn nhờ
  unique constraint của idempotency_key.

Invariant kiểm chứng được:
  sum(amount_vnd) trên user_id = User.balance_vnd  (tại mọi thời điểm sau commit).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing.errors import (
    IdempotencyConflictError,
    InsufficientFundsError,
)
from packages.db.models import User, WalletTransaction

WalletType = Literal["topup", "debit", "refund", "adjust"]


async def _lock_user(session: AsyncSession, user_id: str) -> User | None:
    bind = session.bind
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        stmt = select(User).where(User.id == user_id).with_for_update()
        return (await session.scalars(stmt)).first()
    return await session.get(User, user_id)


async def _existing_by_idempotency(
    session: AsyncSession, key: str
) -> WalletTransaction | None:
    stmt = select(WalletTransaction).where(WalletTransaction.idempotency_key == key)
    return (await session.scalars(stmt)).first()


async def _apply(
    session: AsyncSession,
    *,
    user_id: str,
    type_: WalletType,
    amount_vnd: Decimal,
    idempotency_key: str,
    ref_kind: str | None,
    ref_id: str | None,
    note: str | None,
    created_by: str | None,
) -> WalletTransaction:
    """Hạt nhân ghi sổ. Caller phải truyền signed amount theo quy ước:
    credit/refund > 0; debit < 0 (debit dương sẽ tự đảo dấu ngoài).
    """
    if amount_vnd == 0:
        raise ValueError("amount must be non-zero")

    existing = await _existing_by_idempotency(session, idempotency_key)
    if existing is not None:
        # idempotent: nếu trùng key cùng user và amount → trả lại
        if (
            existing.user_id != user_id
            or Decimal(existing.amount_vnd) != amount_vnd
            or existing.type != type_
        ):
            raise IdempotencyConflictError(
                f"idempotency key {idempotency_key!r} reused with different payload"
            )
        return existing

    user = await _lock_user(session, user_id)
    if user is None:
        raise ValueError(f"user {user_id} not found")

    new_balance = Decimal(user.balance_vnd) + amount_vnd
    if new_balance < 0:
        raise InsufficientFundsError(
            f"balance {user.balance_vnd} insufficient for amount {amount_vnd}"
        )

    user.balance_vnd = new_balance
    record = WalletTransaction(
        user_id=user_id,
        type=type_,
        amount_vnd=amount_vnd,
        balance_after=new_balance,
        ref_kind=ref_kind,
        ref_id=ref_id,
        idempotency_key=idempotency_key,
        note=note,
        created_by=created_by,
    )
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Race với commit khác cùng key — re-fetch và trả lại
        await session.rollback()
        existing = await _existing_by_idempotency(session, idempotency_key)
        if existing is None:
            raise IdempotencyConflictError(str(exc)) from exc
        return existing
    return record


async def credit(
    session: AsyncSession,
    *,
    user_id: str,
    amount_vnd: Decimal | int,
    idempotency_key: str,
    ref_kind: str | None = None,
    ref_id: str | None = None,
    note: str | None = None,
    created_by: str | None = None,
) -> WalletTransaction:
    amt = Decimal(amount_vnd)
    if amt <= 0:
        raise ValueError("credit amount must be positive")
    return await _apply(
        session,
        user_id=user_id,
        type_="topup",
        amount_vnd=amt,
        idempotency_key=idempotency_key,
        ref_kind=ref_kind,
        ref_id=ref_id,
        note=note,
        created_by=created_by,
    )


async def debit(
    session: AsyncSession,
    *,
    user_id: str,
    amount_vnd: Decimal | int,
    idempotency_key: str,
    ref_kind: str | None = None,
    ref_id: str | None = None,
    note: str | None = None,
    created_by: str | None = None,
) -> WalletTransaction:
    amt = Decimal(amount_vnd)
    if amt <= 0:
        raise ValueError("debit amount must be positive")
    return await _apply(
        session,
        user_id=user_id,
        type_="debit",
        amount_vnd=-amt,
        idempotency_key=idempotency_key,
        ref_kind=ref_kind,
        ref_id=ref_id,
        note=note,
        created_by=created_by,
    )


async def refund(
    session: AsyncSession,
    *,
    user_id: str,
    amount_vnd: Decimal | int,
    idempotency_key: str,
    ref_kind: str | None = None,
    ref_id: str | None = None,
    note: str | None = None,
    created_by: str | None = None,
) -> WalletTransaction:
    amt = Decimal(amount_vnd)
    if amt <= 0:
        raise ValueError("refund amount must be positive")
    return await _apply(
        session,
        user_id=user_id,
        type_="refund",
        amount_vnd=amt,
        idempotency_key=idempotency_key,
        ref_kind=ref_kind,
        ref_id=ref_id,
        note=note,
        created_by=created_by,
    )


async def adjust(
    session: AsyncSession,
    *,
    user_id: str,
    amount_vnd: Decimal | int,
    idempotency_key: str,
    note: str | None,
    created_by: str | None,
) -> WalletTransaction:
    amt = Decimal(amount_vnd)
    if amt == 0:
        raise ValueError("adjust amount must be non-zero")
    return await _apply(
        session,
        user_id=user_id,
        type_="adjust",
        amount_vnd=amt,
        idempotency_key=idempotency_key,
        ref_kind="manual",
        ref_id=None,
        note=note,
        created_by=created_by,
    )


async def list_transactions(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int = 50,
    before_id: str | None = None,
) -> list[WalletTransaction]:
    stmt = (
        select(WalletTransaction)
        .where(WalletTransaction.user_id == user_id)
        .order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
        .limit(limit)
    )
    if before_id:
        stmt = stmt.where(WalletTransaction.id < before_id)
    rows = list((await session.scalars(stmt)).all())
    return rows
