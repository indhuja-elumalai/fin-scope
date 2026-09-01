"""Pydantic request/response schemas for financial events."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.domain.events import KNOWN_EVENT_TYPES


class EventCreate(BaseModel):
    merchant_id: uuid.UUID
    event_type: str
    source: str = Field(min_length=1, max_length=100)
    external_reference: str | None = Field(default=None, max_length=255)
    amount: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: str | None = Field(default=None, max_length=100)
    payload: dict = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, value: str) -> str:
        if value not in KNOWN_EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of {sorted(KNOWN_EVENT_TYPES)}, got {value!r}"
            )
        return value


class EventRead(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    event_type: str
    source: str
    external_reference: str | None
    amount: Decimal | None
    currency: str | None
    status: str | None
    payload: dict
    occurred_at: datetime
    ingested_at: datetime

    model_config = {"from_attributes": True}


class EventListResponse(BaseModel):
    items: list[EventRead]
    total: int
    limit: int
    offset: int
