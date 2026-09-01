"""Pydantic request/response schemas for merchants.

Kept separate from app.models.merchant (the ORM model) so the public API
contract can evolve independently of the database schema.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MerchantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    segment: str | None = Field(default=None, max_length=100)


class MerchantRead(BaseModel):
    id: uuid.UUID
    name: str
    segment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
