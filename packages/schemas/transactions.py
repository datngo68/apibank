from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bank_account_id: str
    bank_ref_no: str
    amount_vnd: Decimal
    content: str
    posted_at: datetime
    raw_json: dict[str, Any]
    matched_order_id: str | None
    state: str
    inserted_at: datetime
