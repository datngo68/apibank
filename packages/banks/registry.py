from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.banks.acb.adapter import ACBAdapter
from packages.banks.base import BankAdapter, BankNotSupportedError
from packages.banks.bidv.adapter import BIDVAdapter
from packages.banks.mb.adapter import MBAdapter
from packages.banks.mb.node_bridge import MBNodeBridgeAdapter
from packages.banks.vcb.adapter import VCBAdapter
from packages.banks.vietin.adapter import VietinAdapter
from packages.config.settings import get_settings
from packages.db.models import BankAccount, PollCursor
from packages.security.crypto import FernetCipher

# Banks chỉ có adapter stub (raise NotImplementedError trong v0.1.0). User KHÔNG
# được tạo bank account loại này — UI ẩn chúng và backend reject.
UNSUPPORTED_BANKS: frozenset[str] = frozenset({"BIDV", "ACB", "VCB"})


def build_adapter(*, bank_code: str, username: str, password: str) -> BankAdapter:
    bank = bank_code.upper()
    if bank in UNSUPPORTED_BANKS:
        raise BankNotSupportedError(
            f"{bank} chưa có adapter hoạt động trong v0.1.0; chỉ MB và Vietinbank được hỗ trợ."
        )
    if bank == "MB":
        bridge_url = get_settings().mb_bridge_url
        if bridge_url:
            return MBNodeBridgeAdapter(base_url=bridge_url)
        return MBAdapter(username=username, password=password)
    if bank == "BIDV":
        return BIDVAdapter()
    if bank == "ACB":
        return ACBAdapter()
    if bank == "VCB":
        return VCBAdapter()
    if bank in ("VTB", "VIETIN", "VIETINBANK"):
        return VietinAdapter(username=username, password=password)
    raise BankNotSupportedError(f"unsupported bank_code: {bank_code}")


def decode_credentials(account: BankAccount, *, cipher: FernetCipher) -> tuple[str, str]:
    plain = cipher.decrypt(account.credentials_enc)
    username, _, password = plain.partition(":")
    return username, password


async def list_active_accounts(session: AsyncSession) -> list[BankAccount]:
    return list(
        (
            await session.scalars(
                select(BankAccount)
                .where(BankAccount.status == "active")
                .where(BankAccount.polling_enabled.is_(True))
            )
        ).all()
    )


async def load_cursor(session: AsyncSession, *, bank_account_id: str) -> PollCursor:
    cursor = await session.get(PollCursor, bank_account_id)
    if cursor is None:
        cursor = PollCursor(bank_account_id=bank_account_id, last_seen_at=None, last_ref_no=None)
        session.add(cursor)
        await session.flush()
    return cursor


async def save_cursor(
    session: AsyncSession,
    *,
    bank_account_id: str,
    last_seen_at: datetime | None,
    last_ref_no: str | None,
) -> None:
    cursor = await load_cursor(session, bank_account_id=bank_account_id)
    cursor.last_seen_at = last_seen_at
    cursor.last_ref_no = last_ref_no


__all__: list[str] = [
    "build_adapter",
    "decode_credentials",
    "list_active_accounts",
    "load_cursor",
    "save_cursor",
    "UNSUPPORTED_BANKS",
]

_ = Any  # silence unused import for future expansion
