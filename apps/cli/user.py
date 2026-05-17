"""`apimb user create/list/promote/reset-password`."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
from datetime import UTC, datetime

from sqlalchemy import select

from packages.db.models import User
from packages.db.session import get_sessionmaker
from packages.security.passwords import hash_password


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("user", help="manage users")
    pp = p.add_subparsers(dest="action", required=True)

    create = pp.add_parser("create", help="create a new user")
    create.add_argument("--email", required=True)
    create.add_argument("--password")
    create.add_argument("--full-name", default=None)
    create.add_argument("--admin", action="store_true", help="grant admin role")
    create.set_defaults(func=lambda args: asyncio.run(_create(args)))

    listing = pp.add_parser("list", help="list users")
    listing.add_argument("--limit", type=int, default=50)
    listing.set_defaults(func=lambda args: asyncio.run(_list(args)))

    promote = pp.add_parser("promote", help="promote user to admin")
    promote.add_argument("email")
    promote.set_defaults(func=lambda args: asyncio.run(_promote(args)))

    reset = pp.add_parser("reset-password", help="reset password (admin)")
    reset.add_argument("email")
    reset.set_defaults(func=lambda args: asyncio.run(_reset(args)))


async def _create(args: argparse.Namespace) -> int:
    password = args.password or getpass.getpass("Password: ")
    if len(password) < 8:
        print("password must be ≥ 8 characters", flush=True)
        return 1
    sm = get_sessionmaker()
    async with sm() as session:
        existing = (
            await session.scalars(select(User).where(User.email == args.email.lower()))
        ).first()
        if existing is not None:
            print("user already exists", flush=True)
            return 1
        user = User(
            email=args.email.lower(),
            password_hash=hash_password(password),
            full_name=args.full_name,
            role="admin" if args.admin else "user",
            email_verified_at=datetime.now(UTC),
        )
        session.add(user)
        await session.commit()
        print(json.dumps({"id": user.id, "email": user.email, "role": user.role}, indent=2))
    return 0


async def _list(args: argparse.Namespace) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        rows = list(
            (
                await session.scalars(
                    select(User).order_by(User.created_at.desc()).limit(args.limit)
                )
            ).all()
        )
        for u in rows:
            print(f"{u.id}\t{u.email}\t{u.role}\t{u.status}\tbalance={u.balance_vnd}")
    return 0


async def _promote(args: argparse.Namespace) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        user = (
            await session.scalars(select(User).where(User.email == args.email.lower()))
        ).first()
        if user is None:
            print("user not found", flush=True)
            return 1
        user.role = "admin"
        await session.commit()
        print(f"{user.email} promoted to admin")
    return 0


async def _reset(args: argparse.Namespace) -> int:
    password = getpass.getpass("New password: ")
    if len(password) < 8:
        print("password must be ≥ 8 characters", flush=True)
        return 1
    sm = get_sessionmaker()
    async with sm() as session:
        user = (
            await session.scalars(select(User).where(User.email == args.email.lower()))
        ).first()
        if user is None:
            print("user not found", flush=True)
            return 1
        user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        await session.commit()
        print(f"password reset for {user.email}")
    return 0
