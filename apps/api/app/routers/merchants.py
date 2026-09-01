"""Merchant API.

Minimal create/list/get surface: merchants are the tenant boundary every
financial event attaches to. Update/delete are not part of the approved
Phase 2 scope.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.domain import merchants as merchant_domain
from app.schemas.merchant import MerchantCreate, MerchantRead

router = APIRouter(
    prefix="/v1/merchants",
    tags=["merchants"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=MerchantRead, status_code=status.HTTP_201_CREATED)
def create_merchant(payload: MerchantCreate, db: Session = Depends(get_db)) -> MerchantRead:
    merchant = merchant_domain.create_merchant(db, name=payload.name, segment=payload.segment)
    return MerchantRead.model_validate(merchant)


@router.get("", response_model=list[MerchantRead])
def list_merchants(
    limit: int = 50, offset: int = 0, db: Session = Depends(get_db)
) -> list[MerchantRead]:
    merchants, _total = merchant_domain.list_merchants(db, limit=limit, offset=offset)
    return [MerchantRead.model_validate(m) for m in merchants]


@router.get("/{merchant_id}", response_model=MerchantRead)
def get_merchant(merchant_id: uuid.UUID, db: Session = Depends(get_db)) -> MerchantRead:
    merchant = merchant_domain.get_merchant(db, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
    return MerchantRead.model_validate(merchant)
