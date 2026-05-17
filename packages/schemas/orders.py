from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    amount_vnd: Decimal = Field(gt=0)
    bank_account_id: str
    description: str | None = None
    customer_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = Field(default=900, gt=0, le=86400)


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    amount_vnd: Decimal
    status: str
    bank_account_id: str
    expired_at: datetime
    paid_tx_id: str | None
    paid_at: datetime | None
    customer_ref: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
