"""Coupon validation + redemption.

API:
- ``normalize_code`` chuẩn hoá code (uppercase, trim).
- ``get_active_coupon`` tìm coupon còn hiệu lực theo code (active + window).
- ``compute_discount`` tính discount cho 1 plan price (không update DB).
- ``validate_for_user`` check rule (plan whitelist, min_amount, max_per_user, …).
- ``redeem`` atomically increment ``redeemed_count`` (guard race) + ghi
  ``CouponRedemption``. Trả về row redemption đã add (chưa flush).

Caller (purchase flow) chịu trách nhiệm commit().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.billing.errors import (
    CouponAlreadyRedeemedError,
    CouponExhaustedError,
    CouponExpiredError,
    CouponNotApplicableError,
    CouponNotFoundError,
)
from packages.db.models import Coupon, CouponRedemption


def normalize_code(code: str) -> str:
    return code.strip().upper()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class CouponBreakdown:
    """Kết quả áp coupon trên 1 mức giá."""

    coupon_id: str
    code: str
    discount_type: str
    original_amount_vnd: Decimal
    discount_vnd: Decimal
    final_amount_vnd: Decimal


async def get_active_coupon(session: AsyncSession, code: str) -> Coupon:
    """Tìm coupon active + trong window. Raise nếu không hợp lệ."""
    normalized = normalize_code(code)
    stmt = select(Coupon).where(Coupon.code == normalized)
    coupon = (await session.scalars(stmt)).first()
    if coupon is None or not coupon.active:
        raise CouponNotFoundError(f"coupon {normalized!r} không tồn tại")

    now = datetime.now(UTC)
    valid_from = _aware(coupon.valid_from)
    valid_until = _aware(coupon.valid_until)
    if valid_from is not None and now < valid_from:
        raise CouponExpiredError("Mã chưa tới ngày bắt đầu")
    if valid_until is not None and now >= valid_until:
        raise CouponExpiredError("Mã đã hết hạn")
    if (
        coupon.max_redemptions is not None
        and coupon.redeemed_count >= coupon.max_redemptions
    ):
        raise CouponExhaustedError("Mã đã hết lượt sử dụng")
    return coupon


def compute_discount(coupon: Coupon, amount_vnd: Decimal) -> CouponBreakdown:
    """Tính discount cho 1 mức giá. Tròn về VND nguyên (Decimal(1))."""
    amount = Decimal(amount_vnd).quantize(Decimal(1))

    if coupon.min_amount_vnd is not None and amount < Decimal(coupon.min_amount_vnd):
        raise CouponNotApplicableError(
            f"Đơn tối thiểu {int(coupon.min_amount_vnd):,} VND để áp mã"
        )

    if coupon.discount_type == "percent":
        if coupon.percent_off is None:
            raise CouponNotApplicableError("Mã percent thiếu cấu hình percent_off")
        discount = (amount * Decimal(coupon.percent_off) / Decimal(100)).quantize(
            Decimal(1)
        )
        if coupon.max_discount_vnd is not None:
            discount = min(discount, Decimal(coupon.max_discount_vnd))
    elif coupon.discount_type == "fixed":
        if coupon.amount_off_vnd is None:
            raise CouponNotApplicableError("Mã fixed thiếu cấu hình amount_off_vnd")
        discount = Decimal(coupon.amount_off_vnd)
    else:  # pragma: no cover — defensive
        raise CouponNotApplicableError(
            f"Loại giảm giá không hỗ trợ: {coupon.discount_type}"
        )

    discount = max(Decimal(0), min(discount, amount))
    final_amount = (amount - discount).quantize(Decimal(1))
    return CouponBreakdown(
        coupon_id=coupon.id,
        code=coupon.code,
        discount_type=coupon.discount_type,
        original_amount_vnd=amount,
        discount_vnd=discount,
        final_amount_vnd=final_amount,
    )


async def validate_for_user(
    session: AsyncSession,
    coupon: Coupon,
    *,
    user_id: str,
    plan_code: str,
) -> None:
    """Check rule áp dụng cho user/plan. Raise nếu fail."""
    plan_codes = list(coupon.plan_codes_json or [])
    if plan_codes and plan_code not in plan_codes:
        raise CouponNotApplicableError(
            f"Mã không áp dụng cho gói {plan_code!r}"
        )

    used = await session.scalar(
        select(func.count(CouponRedemption.id))
        .where(CouponRedemption.coupon_id == coupon.id)
        .where(CouponRedemption.user_id == user_id)
    )
    if (used or 0) >= coupon.max_per_user:
        raise CouponAlreadyRedeemedError("Bạn đã dùng hết lượt cho mã này")


async def preview(
    session: AsyncSession,
    *,
    code: str,
    user_id: str,
    plan_code: str,
    amount_vnd: Decimal,
) -> CouponBreakdown:
    """Validate + tính discount, không ghi DB. Dùng cho endpoint preview."""
    coupon = await get_active_coupon(session, code)
    await validate_for_user(session, coupon, user_id=user_id, plan_code=plan_code)
    return compute_discount(coupon, amount_vnd)


async def redeem(
    session: AsyncSession,
    *,
    coupon: Coupon,
    user_id: str,
    plan_code: str,
    amount_vnd: Decimal,
    invoice_id: str | None = None,
    subscription_id: str | None = None,
) -> tuple[CouponBreakdown, CouponRedemption]:
    """Áp + ghi nhận redeem. Caller commit().

    Concurrency: dùng UPDATE có WHERE redeemed_count < max_redemptions để tránh
    race khi 2 request cùng dùng lượt cuối. Nếu rowcount=0 → raise.
    """
    breakdown = compute_discount(coupon, amount_vnd)
    await validate_for_user(session, coupon, user_id=user_id, plan_code=plan_code)

    if coupon.max_redemptions is not None:
        result = await session.execute(
            update(Coupon)
            .where(Coupon.id == coupon.id)
            .where(Coupon.redeemed_count < coupon.max_redemptions)
            .values(redeemed_count=Coupon.redeemed_count + 1)
        )
        if (result.rowcount or 0) == 0:  # type: ignore[attr-defined]
            raise CouponExhaustedError("Mã đã hết lượt sử dụng")
    else:
        await session.execute(
            update(Coupon)
            .where(Coupon.id == coupon.id)
            .values(redeemed_count=Coupon.redeemed_count + 1)
        )

    redemption = CouponRedemption(
        coupon_id=coupon.id,
        coupon_code=coupon.code,
        user_id=user_id,
        invoice_id=invoice_id,
        subscription_id=subscription_id,
        plan_code=plan_code,
        amount_before_vnd=breakdown.original_amount_vnd,
        discount_vnd=breakdown.discount_vnd,
        amount_after_vnd=breakdown.final_amount_vnd,
    )
    session.add(redemption)
    await session.flush()
    return breakdown, redemption
