"""`apimb api-key create` — admin shortcut, in raw key."""

from __future__ import annotations

import argparse
import asyncio
import json

from packages.db.session import get_sessionmaker
from packages.security.bootstrap import create_api_key


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("api-key", help="manage API keys (admin shortcut)")
    pp = p.add_subparsers(dest="action", required=True)

    create = pp.add_parser("create")
    create.add_argument("--owner", default="default")
    create.add_argument("--scope", action="append", help="repeat for multiple scopes")
    create.set_defaults(func=lambda args: asyncio.run(_create(args)))


async def _create(args: argparse.Namespace) -> int:
    scopes = args.scope or ["orders:write", "orders:read"]
    sm = get_sessionmaker()
    async with sm() as session:
        raw, record = await create_api_key(session, owner_id=args.owner, scopes=scopes)
        await session.commit()
    print(json.dumps({"api_key": raw, "id": record.id, "scopes": record.scopes}, indent=2))
    return 0
