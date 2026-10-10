from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    transfer_content: str | None = None
    pay_url: str | None = None
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

    @model_validator(mode="after")
    def restore_public_code(self) -> "OrderRead":
        # Keep the unique payment URL before exposing the reusable transfer name.
        self.pay_url = self.pay_url or f"/pay/{self.code}"
        self.code = self.transfer_content or self.code
        return self
