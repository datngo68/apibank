from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WebhookCreate(BaseModel):
    url: HttpUrl
    secret: str = Field(min_length=16)
    active: bool = True
    headers: dict[str, Any] = Field(default_factory=dict)


class WebhookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    active: bool
    headers_json: dict[str, Any]
    created_at: datetime
