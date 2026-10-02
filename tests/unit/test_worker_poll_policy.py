from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.worker import main


@pytest.mark.asyncio
async def test_should_poll_when_policy_is_disabled() -> None:
    account = SimpleNamespace(id="ba-1", poll_only_when_pending=False)

    assert await main._should_poll(account, datetime.now(UTC)) is True


@pytest.mark.asyncio
async def test_should_not_poll_without_active_pending_order(monkeypatch) -> None:
    async def no_order(_account_id: str, _now: datetime) -> bool:
        return False

    monkeypatch.setattr(main, "_has_active_pending_order", no_order)
    account = SimpleNamespace(id="ba-1", poll_only_when_pending=True)

    assert await main._should_poll(account, datetime.now(UTC)) is False


@pytest.mark.asyncio
async def test_should_poll_with_active_pending_order(monkeypatch) -> None:
    async def has_order(_account_id: str, _now: datetime) -> bool:
        return True

    monkeypatch.setattr(main, "_has_active_pending_order", has_order)
    account = SimpleNamespace(id="ba-1", poll_only_when_pending=True)

    assert await main._should_poll(account, datetime.now(UTC)) is True
