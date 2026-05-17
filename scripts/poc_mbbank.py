from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

from packages.banks.mb.adapter import MBAdapter


async def main() -> None:
    username = os.environ["MB_USERNAME"]
    password = os.environ["MB_PASSWORD"]
    account_no = os.environ["MB_ACCOUNT_NO"]
    adapter = MBAdapter(username=username, password=password)
    await adapter.login()
    end = datetime.now(UTC)
    start = end - timedelta(days=30)
    count = 0
    async for tx in adapter.list_transactions(account_no, start, end):
        print(tx)
        count += 1
        if count >= 5:
            break


if __name__ == "__main__":
    asyncio.run(main())
