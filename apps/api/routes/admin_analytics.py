"""Admin analytics — cohort retention, funnel, churn, LTV, geo.

Mọi endpoint require admin/owner. Tất cả query SQL pure (không gọi external)
nên có thể chạy trên SQLite/Postgres giống nhau.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import (
    Invoice,
    Subscription,
    User,
    WalletTransaction,
)
from packages.db.models import (
    Session as SessionModel,
)
from packages.db.session import get_session
from packages.security.user_auth import current_admin_user

router = APIRouter(
    prefix="/api/v1/admin/analytics", tags=["admin-analytics"]
)


@router.get("/cohort-retention")
async def cohort_retention(
    weeks: int = Query(default=8, ge=1, le=52),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Cohort theo tuần register; track active (last_login_at) ở mỗi tuần sau."""
    now = datetime.now(UTC)
    start = now - timedelta(weeks=weeks)

    # Lấy tất cả user trong horizon.
    rows = list(
        (
            await session.scalars(
                select(User).where(User.created_at >= start)
            )
        ).all()
    )

    cohorts: dict[str, list[User]] = defaultdict(list)
    for u in rows:
        # Tuần ISO của ngày register.
        c_year, c_week, _wd = u.created_at.isocalendar()
        key = f"{c_year}-W{c_week:02d}"
        cohorts[key].append(u)

    out: list[dict[str, Any]] = []
    for cohort_key, members in sorted(cohorts.items()):
        size = len(members)
        # Active per week_offset: last_login_at >= now - (weeks - offset).
        retained: dict[int, int] = {}
        for offset in range(weeks + 1):
            cutoff = now - timedelta(weeks=weeks - offset)
            count = sum(
                1
                for m in members
                if m.last_login_at is not None and m.last_login_at >= cutoff
            )
            retained[offset] = count
        out.append(
            {
                "cohort": cohort_key,
                "size": size,
                "retention": [
                    {
                        "week_offset": k,
                        "active": v,
                        "rate": round(v / size, 4) if size else 0,
                    }
                    for k, v in retained.items()
                ],
            }
        )
    return {"weeks": weeks, "cohorts": out}


@router.get("/funnel")
async def funnel(
    days: int = Query(default=30, ge=1, le=365),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Conversion funnel: register → verify → first paid sub.

    `register`: tổng user trong horizon.
    `verified`: trong số đó, có email_verified_at.
    `paid_sub`: trong số đó, có ít nhất 1 invoice paid.
    """
    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    register = int(
        (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.created_at >= since)
            )
        ).scalar_one() or 0
    )
    verified = int(
        (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.created_at >= since)
                .where(User.email_verified_at.is_not(None))
            )
        ).scalar_one() or 0
    )
    paid_sub = int(
        (
            await session.execute(
                select(func.count(func.distinct(Invoice.user_id)))
                .select_from(Invoice)
                .where(Invoice.status == "paid")
                .where(Invoice.issued_at >= since)
            )
        ).scalar_one() or 0
    )
    topup = int(
        (
            await session.execute(
                select(func.count(func.distinct(WalletTransaction.user_id)))
                .select_from(WalletTransaction)
                .where(WalletTransaction.type == "topup")
                .where(WalletTransaction.created_at >= since)
            )
        ).scalar_one() or 0
    )
    return {
        "days": days,
        "stages": [
            {"name": "register", "count": register},
            {"name": "verified", "count": verified},
            {"name": "first_topup", "count": topup},
            {"name": "paid_sub", "count": paid_sub},
        ],
    }


@router.get("/churn")
async def churn(
    months: int = Query(default=3, ge=1, le=12),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Churn = canceled+expired sub trong tháng / sub đầu tháng."""
    now = datetime.now(UTC)
    out = []
    for i in range(months):
        # Period = month i months ago.
        period_end = datetime(now.year, now.month, 1, tzinfo=UTC) - timedelta(
            days=30 * i
        )
        period_start = period_end - timedelta(days=30)
        active_at_start = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Subscription)
                    .where(Subscription.started_at < period_start)
                    .where(Subscription.expires_at > period_start)
                )
            ).scalar_one() or 0
        )
        churned = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Subscription)
                    .where(Subscription.status.in_(("canceled", "expired")))
                    .where(Subscription.updated_at >= period_start)
                    .where(Subscription.updated_at < period_end)
                )
            ).scalar_one() or 0
        )
        out.append(
            {
                "period": period_start.date().isoformat(),
                "active_at_start": active_at_start,
                "churned": churned,
                "rate": round(churned / active_at_start, 4)
                if active_at_start
                else 0,
            }
        )
    return {"months": months, "periods": out}


@router.get("/ltv")
async def ltv(
    days: int = Query(default=180, ge=30, le=730),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """LTV approx = avg revenue per user (subscription + topup) trong horizon."""
    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    sub_rev = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(Invoice.amount_vnd), 0))
                .where(Invoice.status == "paid")
                .where(Invoice.issued_at >= since)
            )
        ).scalar_one() or 0
    )
    topup_rev = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(WalletTransaction.amount_vnd), 0))
                .where(WalletTransaction.type == "topup")
                .where(WalletTransaction.created_at >= since)
            )
        ).scalar_one() or 0
    )
    paying_users = int(
        (
            await session.execute(
                select(func.count(func.distinct(Invoice.user_id)))
                .select_from(Invoice)
                .where(Invoice.status == "paid")
                .where(Invoice.issued_at >= since)
            )
        ).scalar_one() or 0
    )
    total_users = int(
        (
            await session.execute(select(func.count()).select_from(User))
        ).scalar_one() or 0
    )

    arpu_paying = (
        (sub_rev + topup_rev) / Decimal(paying_users) if paying_users else Decimal(0)
    )
    arpu_total = (
        (sub_rev + topup_rev) / Decimal(total_users) if total_users else Decimal(0)
    )
    return {
        "days": days,
        "sub_revenue_vnd": str(sub_rev),
        "topup_revenue_vnd": str(topup_rev),
        "paying_users": paying_users,
        "total_users": total_users,
        "arpu_paying_vnd": str(arpu_paying.quantize(Decimal("1"))),
        "arpu_total_vnd": str(arpu_total.quantize(Decimal("1"))),
    }


@router.get("/geo")
async def geo_split(
    days: int = Query(default=30, ge=1, le=365),
    _: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Geo split (đơn giản): group session theo subnet /24 IPv4 hoặc /48 IPv6.

    Không có GeoIP database — admin có thể đối chiếu /24 với IP-to-country
    sau. Đây là fallback rẻ.
    """
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    rows = list(
        (
            await session.scalars(
                select(SessionModel)
                .where(SessionModel.created_at >= since)
                .where(SessionModel.ip.is_not(None))
            )
        ).all()
    )
    buckets: dict[str, int] = defaultdict(int)
    for s in rows:
        if not s.ip:
            continue
        if ":" in s.ip:
            # IPv6 → /48
            parts = s.ip.split(":")
            buckets[":".join(parts[:3]) + "::/48"] += 1
        else:
            parts = s.ip.split(".")
            if len(parts) == 4:
                buckets[".".join(parts[:3]) + ".0/24"] += 1
    top = sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)[:30]
    return {
        "days": days,
        "total_sessions": len(rows),
        "top_subnets": [{"subnet": k, "count": v} for k, v in top],
    }


__all__ = ["router"]
