"""Domain exceptions for billing module."""

from __future__ import annotations


class BillingError(Exception):
    """Base exception."""


class InsufficientFundsError(BillingError):
    """User không đủ số dư để debit."""


class IdempotencyConflictError(BillingError):
    """Idempotency key đã tồn tại nhưng nội dung khác."""


class PlanNotFoundError(BillingError):
    """Plan không tồn tại hoặc đã ngừng bán."""


class SystemBankNotConfiguredError(BillingError):
    """Chưa có bank account đánh dấu is_system_account=True."""


class CouponError(BillingError):
    """Base cho mọi lỗi coupon."""


class CouponNotFoundError(CouponError):
    """Mã không tồn tại hoặc đã bị tắt."""


class CouponExpiredError(CouponError):
    """Mã đã hết hạn hoặc chưa tới ngày bắt đầu."""


class CouponExhaustedError(CouponError):
    """Mã đã dùng hết tổng lượt redeem."""


class CouponAlreadyRedeemedError(CouponError):
    """User đã dùng tối đa số lượt cho phép."""


class CouponNotApplicableError(CouponError):
    """Mã không áp dụng cho plan / số tiền hiện tại."""


class CouponConflictError(CouponError):
    """Coupon code đã tồn tại (admin tạo trùng)."""
