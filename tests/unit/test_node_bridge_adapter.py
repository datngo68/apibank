from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from packages.banks.base import BankAuthError
from packages.banks.mb.node_bridge import MBNodeBridgeAdapter


@pytest.fixture
def adapter() -> MBNodeBridgeAdapter:
    return MBNodeBridgeAdapter(base_url="http://bridge.test")


async def test_login_raises_bank_auth_error_on_http_failure(
    adapter: MBNodeBridgeAdapter,
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    adapter._client = httpx.AsyncClient(transport=transport, base_url="http://bridge.test")

    with pytest.raises(BankAuthError):
        await adapter.login()


async def test_health_returns_true_on_200(adapter: MBNodeBridgeAdapter) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "ok"}))
    adapter._client = httpx.AsyncClient(transport=transport, base_url="http://bridge.test")

    assert await adapter.health() is True


async def test_get_balance_parses_decimal(adapter: MBNodeBridgeAdapter) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"balance": "12345"}))
    adapter._client = httpx.AsyncClient(transport=transport, base_url="http://bridge.test")

    balance = await adapter.get_balance("12345")

    assert balance == Decimal("12345")


async def test_list_transactions_streams_mapped_records(adapter: MBNodeBridgeAdapter) -> None:
    posted = datetime(2026, 5, 16, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transactions": [
                    {
                        "refNo": "FT_BR_1",
                        "transactionDate": "16/05/2026",
                        "amount": 100000,
                        "description": "PAY DH1",
                        "counterAccount": "999",
                        "counterName": "X",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    adapter._client = httpx.AsyncClient(transport=transport, base_url="http://bridge.test")

    items = []
    async for item in adapter.list_transactions("123", posted, posted):
        items.append(item)

    assert len(items) == 1
    assert items[0].bank_ref_no == "FT_BR_1"
    assert items[0].amount == Decimal("100000")
