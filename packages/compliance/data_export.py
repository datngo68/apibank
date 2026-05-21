"""Build GDPR data export ZIP cho 1 user.

Output: ZIP chứa multiple JSON file (user.json, sessions.json, api_keys.json,
orders.json, transactions.json, invoices.json, wallet_tx.json,
notifications.json). KHÔNG xuất `credentials_enc`/`secret_enc`/`password_hash`.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import (
    ApiKey,
    BankAccount,
    Invoice,
    Notification,
    Order,
    Transaction,
    User,
    WalletTransaction,
)
from packages.db.models import (
    Session as SessionModel,
)

logger = logging.getLogger(__name__)


def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    return obj


def _row_to_dict(row: Any, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for col in row.__table__.columns:
        if col.name in exclude:
            continue
        result[col.name] = _serialize(getattr(row, col.name))
    return result


async def build_zip_for_user(
    session: AsyncSession, user: User, *, base_dir: str = "exports"
) -> str:
    """Build ZIP, trả về path. Idempotent: ghi đè nếu file cũ tồn tại."""
    # Path I/O đồng bộ — chấp nhận với job admin tay (không hot path).
    Path(base_dir).mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    out_path = str(Path(base_dir) / f"user-{user.id}.zip")

    user_data = _row_to_dict(user, exclude=("password_hash",))

    sessions = list(
        (
            await session.scalars(
                select(SessionModel).where(SessionModel.user_id == user.id)
            )
        ).all()
    )
    api_keys = list(
        (
            await session.scalars(
                select(ApiKey).where(ApiKey.user_id == user.id)
            )
        ).all()
    )
    bank_accounts = list(
        (
            await session.scalars(
                select(BankAccount).where(BankAccount.user_id == user.id)
            )
        ).all()
    )
    orders = list(
        (
            await session.scalars(
                select(Order).where(Order.user_id == user.id)
            )
        ).all()
    )
    bank_ids = [b.id for b in bank_accounts]
    transactions: list[Transaction] = []
    if bank_ids:
        transactions = list(
            (
                await session.scalars(
                    select(Transaction).where(
                        Transaction.bank_account_id.in_(bank_ids)
                    )
                )
            ).all()
        )
    invoices = list(
        (
            await session.scalars(
                select(Invoice).where(Invoice.user_id == user.id)
            )
        ).all()
    )
    wallet_tx = list(
        (
            await session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.user_id == user.id
                )
            )
        ).all()
    )
    notifications = list(
        (
            await session.scalars(
                select(Notification).where(Notification.user_id == user.id)
            )
        ).all()
    )

    payload = {
        "user.json": user_data,
        "sessions.json": [
            _row_to_dict(s, exclude=("token_hash",)) for s in sessions
        ],
        "api_keys.json": [
            _row_to_dict(k, exclude=("key_hash",)) for k in api_keys
        ],
        "bank_accounts.json": [
            _row_to_dict(b, exclude=("credentials_enc",)) for b in bank_accounts
        ],
        "orders.json": [_row_to_dict(o) for o in orders],
        "transactions.json": [
            _row_to_dict(t, exclude=("raw_json",)) for t in transactions
        ],
        "invoices.json": [_row_to_dict(i) for i in invoices],
        "wallet_transactions.json": [_row_to_dict(w) for w in wallet_tx],
        "notifications.json": [
            _row_to_dict(n, exclude=("payload_json",)) for n in notifications
        ],
    }

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in payload.items():
            zf.writestr(name, json.dumps(body, ensure_ascii=False, indent=2))

    return out_path


__all__ = ["build_zip_for_user"]
