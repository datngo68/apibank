"""Tests cho QuotaTracker (in-memory fallback)."""

from __future__ import annotations

import pytest

from packages.billing.quota import QuotaStatus, QuotaTracker, reset_quota_singleton


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_quota_singleton()


@pytest.mark.asyncio
async def test_hit_increments_day_and_month() -> None:
    tracker = QuotaTracker(redis_url=None)
    a = await tracker.hit("u1", limit_day=10, limit_month=100)
    b = await tracker.hit("u1", limit_day=10, limit_month=100)
    assert a.used_today == 1 and b.used_today == 2
    assert a.used_month == 1 and b.used_month == 2


@pytest.mark.asyncio
async def test_exceeded_flag_when_over_day_limit() -> None:
    tracker = QuotaTracker(redis_url=None)
    for _ in range(3):
        await tracker.hit("u2", limit_day=2, limit_month=0)
    last = await tracker.hit("u2", limit_day=2, limit_month=0)
    assert last.exceeded is True


@pytest.mark.asyncio
async def test_exceeded_false_when_under_limit() -> None:
    tracker = QuotaTracker(redis_url=None)
    s = await tracker.hit("u3", limit_day=100, limit_month=1000)
    assert s.exceeded is False


@pytest.mark.asyncio
async def test_isolation_between_users() -> None:
    tracker = QuotaTracker(redis_url=None)
    await tracker.hit("ux", limit_day=5)
    await tracker.hit("ux", limit_day=5)
    s = await tracker.hit("uy", limit_day=5)
    assert s.used_today == 1


@pytest.mark.asyncio
async def test_reset_clears_user_buckets() -> None:
    tracker = QuotaTracker(redis_url=None)
    await tracker.hit("rz", limit_day=10)
    await tracker.hit("rz", limit_day=10)
    await tracker.reset("rz")
    s = await tracker.hit("rz", limit_day=10)
    assert s.used_today == 1


def test_quota_status_no_limits_means_not_exceeded() -> None:
    s = QuotaStatus(used_today=999_999, used_month=999_999, limit_day=0, limit_month=0)
    assert s.exceeded is False
