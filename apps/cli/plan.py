"""`apimb plan seed/list/upsert`."""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal

from sqlalchemy import select

from packages.billing.plans_seed import seed_plans
from packages.db.models import Plan
from packages.db.session import get_sessionmaker


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("plan", help="manage subscription plans")
    pp = p.add_subparsers(dest="action", required=True)

    seed = pp.add_parser("seed", help="seed default plans")
    seed.set_defaults(func=lambda args: asyncio.run(_seed(args)))

    listing = pp.add_parser("list", help="list plans")
    listing.set_defaults(func=lambda args: asyncio.run(_list(args)))

    upsert = pp.add_parser("upsert", help="create/update a plan")
    upsert.add_argument("--code", required=True)
    upsert.add_argument("--name", required=True)
    upsert.add_argument("--price", type=int, required=True, help="price in VND")
    upsert.add_argument("--days", type=int, required=True)
    upsert.add_argument("--daily-quota", type=int, default=0)
    upsert.add_argument("--monthly-quota", type=int, default=0)
    upsert.add_argument("--description", default=None)
    upsert.add_argument("--features-json", default="{}")
    upsert.set_defaults(func=lambda args: asyncio.run(_upsert(args)))


async def _seed(_: argparse.Namespace) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        n = await seed_plans(session)
        await session.commit()
    print(f"seeded {n} plan(s)")
    return 0


async def _list(_: argparse.Namespace) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        rows = list(
            (
                await session.scalars(
                    select(Plan).order_by(Plan.sort_order, Plan.price_vnd)
                )
            ).all()
        )
        for p in rows:
            print(f"{p.code}\t{p.name}\t{int(p.price_vnd):,} VND\t{p.duration_days}d\tactive={p.active}")
    return 0


async def _upsert(args: argparse.Namespace) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        plan = (
            await session.scalars(select(Plan).where(Plan.code == args.code))
        ).first()
        features = json.loads(args.features_json or "{}")
        if plan is None:
            plan = Plan(
                code=args.code,
                name=args.name,
                description=args.description,
                price_vnd=Decimal(args.price),
                duration_days=args.days,
                daily_quota=args.daily_quota,
                monthly_quota=args.monthly_quota,
                features_json=features,
                active=True,
            )
            session.add(plan)
        else:
            plan.name = args.name
            plan.description = args.description
            plan.price_vnd = Decimal(args.price)
            plan.duration_days = args.days
            plan.daily_quota = args.daily_quota
            plan.monthly_quota = args.monthly_quota
            plan.features_json = features
            plan.active = True
        await session.commit()
    print(f"upserted plan {args.code}")
    return 0
