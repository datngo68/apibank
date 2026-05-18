"""Tests cho mã giảm giá (Coupon)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing import coupons, subscription, wallet
from packages.billing.errors import (
    CouponAlreadyRedeemedError,
    CouponExhaustedError,
    CouponExpiredError,
    CouponNotApplicableError,
    CouponNotFoundError,
)
from packages.billing.plans_seed import seed_plans
from packages.db.models import Coupon, CouponRedemption, Invoice, User
from packages.security.passwords import hash_password


async def _user_with_balance(
    session: AsyncSession, balance: int = 100_000, *, email: str = "u@a.com"
) -> User:
    user = User(email=email, password_hash=hash_password("xxxxxxxx"), full_name="U")
    session.add(user)
    await session.flush()
    if balance:
        await wallet.credit(
            session,
            user_id=user.id,
            amount_vnd=balance,
            idempotency_key=f"seed:{user.id}",
        )
    return user


def _make_coupon(**kwargs: object) -> Coupon:
    base: dict[str, object] = {
        "code": "SAVE10",
        "discount_type": "percent",
        "percent_off": 10,
        "max_per_user": 1,
        "redeemed_count": 0,
        "plan_codes_json": [],
        "active": True,
    }
    base.update(kwargs)
    return Coupon(**base)


@pytest.fixture
async def seeded(initialized_db: AsyncSession) -> AsyncSession:
    await seed_plans(initialized_db)
    await initialized_db.commit()
    return initialized_db


@pytest.mark.asyncio
async def test_compute_percent_discount() -> None:
    coupon = _make_coupon()
    bk = coupons.compute_discount(coupon, Decimal(15_000))
    assert bk.discount_vnd == Decimal(1_500)
    assert bk.final_amount_vnd == Decimal(13_500)


@pytest.mark.asyncio
async def test_compute_fixed_discount() -> None:
    coupon = _make_coupon(
        code="FIX2K",
        discount_type="fixed",
        percent_off=None,
        amount_off_vnd=Decimal(2_000),
    )
    bk = coupons.compute_discount(coupon, Decimal(15_000))
    assert bk.discount_vnd == Decimal(2_000)
    assert bk.final_amount_vnd == Decimal(13_000)


@pytest.mark.asyncio
async def test_compute_percent_caps_at_max_discount() -> None:
    coupon = _make_coupon(percent_off=50, max_discount_vnd=Decimal(5_000))
    bk = coupons.compute_discount(coupon, Decimal(20_000))
    assert bk.discount_vnd == Decimal(5_000)


@pytest.mark.asyncio
async def test_compute_fixed_does_not_exceed_amount() -> None:
    coupon = _make_coupon(
        discount_type="fixed",
        percent_off=None,
        amount_off_vnd=Decimal(100_000),
    )
    bk = coupons.compute_discount(coupon, Decimal(15_000))
    # Discount không vượt số tiền gốc.
    assert bk.discount_vnd == Decimal(15_000)
    assert bk.final_amount_vnd == Decimal(0)


@pytest.mark.asyncio
async def test_min_amount_blocks(seeded: AsyncSession) -> None:
    coupon = _make_coupon(min_amount_vnd=Decimal(50_000))
    with pytest.raises(CouponNotApplicableError):
        coupons.compute_discount(coupon, Decimal(15_000))


@pytest.mark.asyncio
async def test_get_active_coupon_uppercases(seeded: AsyncSession) -> None:
    seeded.add(_make_coupon())
    await seeded.commit()
    found = await coupons.get_active_coupon(seeded, "save10")
    assert found.code == "SAVE10"


@pytest.mark.asyncio
async def test_inactive_coupon_not_found(seeded: AsyncSession) -> None:
    seeded.add(_make_coupon(active=False))
    await seeded.commit()
    with pytest.raises(CouponNotFoundError):
        await coupons.get_active_coupon(seeded, "SAVE10")


@pytest.mark.asyncio
async def test_expired_coupon(seeded: AsyncSession) -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    seeded.add(_make_coupon(valid_until=past))
    await seeded.commit()
    with pytest.raises(CouponExpiredError):
        await coupons.get_active_coupon(seeded, "SAVE10")


@pytest.mark.asyncio
async def test_not_started_coupon(seeded: AsyncSession) -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    seeded.add(_make_coupon(valid_from=future))
    await seeded.commit()
    with pytest.raises(CouponExpiredError):
        await coupons.get_active_coupon(seeded, "SAVE10")


@pytest.mark.asyncio
async def test_exhausted_coupon(seeded: AsyncSession) -> None:
    seeded.add(_make_coupon(max_redemptions=1, redeemed_count=1))
    await seeded.commit()
    with pytest.raises(CouponExhaustedError):
        await coupons.get_active_coupon(seeded, "SAVE10")


@pytest.mark.asyncio
async def test_plan_whitelist_blocks(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 0)
    coupon = _make_coupon(plan_codes_json=["yearly"])
    seeded.add(coupon)
    await seeded.commit()
    with pytest.raises(CouponNotApplicableError):
        await coupons.validate_for_user(
            seeded, coupon, user_id=user.id, plan_code="monthly"
        )


@pytest.mark.asyncio
async def test_purchase_with_percent_coupon(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 50_000)
    seeded.add(_make_coupon())  # SAVE10 = 10%
    await seeded.commit()

    sub, invoice = await subscription.purchase(
        seeded,
        user=user,
        plan_code="monthly",
        idempotency_key="cp1",
        coupon_code="save10",
    )
    await seeded.commit()

    # 15k - 1.5k = 13.5k
    assert invoice.amount_vnd == Decimal(13_500)
    assert invoice.discount_vnd == Decimal(1_500)
    assert invoice.original_amount_vnd == Decimal(15_000)
    assert invoice.coupon_code == "SAVE10"

    refreshed = await seeded.get(User, user.id)
    assert refreshed is not None
    assert Decimal(refreshed.balance_vnd) == Decimal(36_500)

    # Redemption row được link với invoice + sub.
    redemption = (
        await seeded.scalars(
            select(CouponRedemption).where(CouponRedemption.user_id == user.id)
        )
    ).first()
    assert redemption is not None
    assert redemption.invoice_id == invoice.id
    assert redemption.subscription_id == sub.id
    assert redemption.discount_vnd == Decimal(1_500)


@pytest.mark.asyncio
async def test_purchase_increments_redeemed_count(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 50_000)
    seeded.add(_make_coupon(max_redemptions=2))
    await seeded.commit()

    await subscription.purchase(
        seeded,
        user=user,
        plan_code="monthly",
        idempotency_key="r1",
        coupon_code="SAVE10",
    )
    await seeded.commit()

    coupon = (
        await seeded.scalars(select(Coupon).where(Coupon.code == "SAVE10"))
    ).first()
    assert coupon is not None and coupon.redeemed_count == 1


@pytest.mark.asyncio
async def test_double_redeem_per_user_blocked(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 100_000)
    seeded.add(_make_coupon(max_per_user=1))
    await seeded.commit()

    await subscription.purchase(
        seeded,
        user=user,
        plan_code="monthly",
        idempotency_key="d1",
        coupon_code="SAVE10",
    )
    await seeded.commit()

    with pytest.raises(CouponAlreadyRedeemedError):
        await subscription.purchase(
            seeded,
            user=user,
            plan_code="monthly",
            idempotency_key="d2",
            coupon_code="SAVE10",
        )


@pytest.mark.asyncio
async def test_global_max_redemptions_blocks_second_user(
    seeded: AsyncSession,
) -> None:
    user1 = await _user_with_balance(seeded, 50_000, email="u1@a.com")
    user2 = await _user_with_balance(seeded, 50_000, email="u2@a.com")
    seeded.add(_make_coupon(max_redemptions=1))
    await seeded.commit()

    await subscription.purchase(
        seeded,
        user=user1,
        plan_code="monthly",
        idempotency_key="g1",
        coupon_code="SAVE10",
    )
    await seeded.commit()

    with pytest.raises(CouponExhaustedError):
        await subscription.purchase(
            seeded,
            user=user2,
            plan_code="monthly",
            idempotency_key="g2",
            coupon_code="SAVE10",
        )


@pytest.mark.asyncio
async def test_purchase_without_coupon_unchanged(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 50_000)
    _, invoice = await subscription.purchase(
        seeded, user=user, plan_code="monthly", idempotency_key="nc"
    )
    await seeded.commit()
    fresh = await seeded.get(Invoice, invoice.id)
    assert fresh is not None
    assert fresh.discount_vnd == Decimal(0)
    assert fresh.coupon_code is None
    assert fresh.original_amount_vnd is None


@pytest.mark.asyncio
async def test_preview_returns_breakdown(seeded: AsyncSession) -> None:
    user = await _user_with_balance(seeded, 0)
    seeded.add(_make_coupon())
    await seeded.commit()
    bk = await coupons.preview(
        seeded,
        code="save10",
        user_id=user.id,
        plan_code="monthly",
        amount_vnd=Decimal(15_000),
    )
    assert bk.code == "SAVE10"
    assert bk.discount_vnd == Decimal(1_500)
    # Preview không tăng redeemed_count.
    coupon = (
        await seeded.scalars(select(Coupon).where(Coupon.code == "SAVE10"))
    ).first()
    assert coupon is not None and coupon.redeemed_count == 0
