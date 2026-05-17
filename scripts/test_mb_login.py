"""Smoke test: login MB once and fetch last transactions for the seeded account."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from packages.banks.registry import build_adapter, decode_credentials
from packages.config.settings import get_settings
from packages.db.models import BankAccount
from packages.db.session import get_engine, get_sessionmaker
from packages.security.crypto import FernetCipher


async def main() -> None:
    settings = get_settings()
    if not settings.fernet_keys:
        raise SystemExit("APIBANK_FERNET_KEYS missing")
    cipher = FernetCipher.from_keys(settings.fernet_keys)

    sm = get_sessionmaker()
    async with sm() as session:
        account = (await session.scalars(select(BankAccount))).first()
    if account is None:
        raise SystemExit("no bank account found")

    print(f"account: {account.bank_code} {account.account_no} ({account.account_holder})")
    username, password = decode_credentials(account, cipher=cipher)
    print(f"username length: {len(username)}, password length: {len(password)}")

    adapter = build_adapter(
        bank_code=account.bank_code, username=username, password=password
    )
    print("logging in (this may take 5-15s for WASM/OCR download)...")
    try:
        await adapter.login()
    except Exception as exc:
        print(f"LOGIN FAILED: {exc!r}")
        await get_engine().dispose()
        return
    print("login OK")

    end = datetime.now(UTC)
    start = end - timedelta(days=7)
    count = 0
    print("\nlast 5 transactions in past 7 days:")
    try:
        async for tx in adapter.list_transactions(account.account_no, start, end):
            print(
                f"  {tx.posted_at.isoformat()} | {tx.amount} | {tx.bank_ref_no} | {tx.content[:60]}"
            )
            count += 1
            if count >= 5:
                break
    except Exception as exc:
        print(f"LIST_TRANSACTIONS FAILED: {exc!r}")
    print(f"\ntotal printed: {count}")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
