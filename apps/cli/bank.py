"""`apimb bank-account create` — admin shortcut tạo bank account legacy (không gắn user)."""

from __future__ import annotations

import argparse
import asyncio
import json

from packages.config.settings import get_settings
from packages.db.models import BankAccount
from packages.db.session import get_sessionmaker
from packages.security.crypto import FernetCipher


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("bank-account", help="manage bank accounts (admin)")
    pp = p.add_subparsers(dest="action", required=True)

    create = pp.add_parser("create")
    create.add_argument("--bank-code", required=True)
    create.add_argument("--account-no", required=True)
    create.add_argument("--holder", required=True)
    create.add_argument("--username", required=True)
    create.add_argument("--password", required=True)
    create.set_defaults(func=lambda args: asyncio.run(_create(args)))


async def _create(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.fernet_keys:
        print("APIBANK_FERNET_KEYS missing — run `apimb fernet generate` first", flush=True)
        return 1
    cipher = FernetCipher.from_keys(settings.fernet_keys)
    sm = get_sessionmaker()
    async with sm() as session:
        account = BankAccount(
            bank_code=args.bank_code.upper(),
            account_no=args.account_no,
            account_holder=args.holder,
            credentials_enc=cipher.encrypt(f"{args.username}:{args.password}"),
            status="active",
            polling_enabled=True,
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
    print(
        json.dumps(
            {
                "id": account.id,
                "bank_code": account.bank_code,
                "account_no": account.account_no,
            },
            indent=2,
        )
    )
    return 0
