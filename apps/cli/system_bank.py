"""`apimb system-bank set --account-id ba_xxx` — đánh dấu bank nhận topup."""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import update

from packages.db.models import BankAccount
from packages.db.session import get_sessionmaker


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("system-bank", help="manage system bank account for topup")
    pp = p.add_subparsers(dest="action", required=True)
    setp = pp.add_parser("set", help="set system bank")
    setp.add_argument("--account-id", required=True)
    setp.set_defaults(func=lambda args: asyncio.run(_set(args)))
    unset = pp.add_parser("unset", help="unset all system banks")
    unset.set_defaults(func=lambda args: asyncio.run(_unset(args)))


async def _set(args: argparse.Namespace) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        target = await session.get(BankAccount, args.account_id)
        if target is None:
            print("bank account not found", flush=True)
            return 1
        await session.execute(
            update(BankAccount).values(is_system_account=False)
        )
        target.is_system_account = True
        await session.commit()
    print(f"system bank set to {args.account_id}")
    return 0


async def _unset(_: argparse.Namespace) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        await session.execute(update(BankAccount).values(is_system_account=False))
        await session.commit()
    print("all system banks unset")
    return 0
