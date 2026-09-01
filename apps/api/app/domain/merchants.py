"""Merchant domain operations.

Kept separate from the router so the business rules (currently minimal --
Phase 2 has no merchant-specific validation beyond the schema) are not
tangled with HTTP concerns, and so later phases can call these functions
directly without going through the API layer.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.merchant import Merchant


def create_merchant(db: Session, *, name: str, segment: str | None) -> Merchant:
    merchant = Merchant(name=name, segment=segment)
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def list_merchants(
    db: Session, *, limit: int = 50, offset: int = 0
) -> tuple[list[Merchant], int]:
    total = db.scalar(select(func.count()).select_from(Merchant)) or 0
    stmt = select(Merchant).order_by(Merchant.created_at.desc()).limit(limit).offset(offset)
    merchants = list(db.scalars(stmt))
    return merchants, total


def get_merchant(db: Session, merchant_id: uuid.UUID) -> Merchant | None:
    return db.get(Merchant, merchant_id)
