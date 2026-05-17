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
