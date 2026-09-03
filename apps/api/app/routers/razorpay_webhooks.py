"""Razorpay webhook receiver -- Phase 10, Milestone 2.

Deliberately NOT behind app.auth.require_api_key (see that module's own
docstring, written during Phase 1: "This dependency must NOT be used on
webhook routes ... those authenticate via Razorpay signature verification
instead"). Authentication here is entirely the HMAC signature check
below -- there is no X-API-Key on an inbound webhook from Razorpay.

async def specifically so this endpoint can `await request.body()` and
verify the signature against the exact RAW bytes Razorpay sent, before
any JSON parsing happens -- the one deliberate deviation from the rest of
this codebase's sync router style (see app.domain.razorpay_webhooks
module docstring for the pure/orchestration split underneath this). A
signature computed over a re-serialized/re-parsed body can silently
differ from Razorpay's, which is exactly the class of bug Phase 10 safety
rule 8 ("use the raw request body for HMAC verification") exists to
prevent.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.domain import events as event_domain
from app.domain import razorpay_webhooks as webhook_domain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["razorpay-webhooks"])


@router.post("/razorpay")
async def receive_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Response:
    settings = get_settings()
    raw_body = await request.body()

    # --- Authentication: signature first, on every request, before any
    # other check -- see module docstring / safety rule 8. ---
    if not x_razorpay_signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing signature")
    if not settings.razorpay_webhook_secret:
        # Configuration failure, not the caller's fault -- never leak
        # "secret is unset" detail to the response either way, and never
        # fall through to "verification skipped".
        logger.error("Razorpay webhook received but RAZORPAY_WEBHOOK_SECRET is not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook receiver is not configured",
        )
    if not webhook_domain.verify_signature(
        raw_body, x_razorpay_signature, settings.razorpay_webhook_secret
    ):
        # Deliberately generic -- never echoes back the signature we
        # computed or received (safety rule 8: never expose
        # webhook-secret/API-secret details in API responses).
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    if not x_razorpay_event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing x-razorpay-event-id"
        )

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON body"
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook body must be a JSON object"
        )

    razorpay_event_type = body.get("event")
    if not isinstance(razorpay_event_type, str) or not razorpay_event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook body has no 'event' field"
        )

    merchant_id = _resolve_merchant_id(settings.razorpay_default_merchant_id)

    try:
        result = webhook_domain.process_webhook(
            db,
            razorpay_event_id=x_razorpay_event_id,
            razorpay_event_type=razorpay_event_type,
            body=body,
            merchant_id=merchant_id,
        )
    except webhook_domain.MalformedPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unprocessable {razorpay_event_type} payload",
        ) from exc
    except event_domain.MerchantNotFoundError as exc:
        # Configuration failure (RAZORPAY_DEFAULT_MERCHANT_ID does not
        # name a real merchant) -- not ledger-recorded (process_webhook
        # never reaches its ledger write on this path), so a retry after
        # the operator fixes the mapping will actually reprocess.
        db.rollback()
        logger.error("Razorpay webhook: configured merchant %s does not exist", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook receiver is not configured",
        ) from exc
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
        # unanticipated persistence/DB failure must become a 5xx that
        # Razorpay will retry, never a silent 2xx and never a leaked
        # internal error string. No ledger row was written for this
        # path (see module docstring), so a retry actually reprocesses.
        db.rollback()
        logger.exception(
            "Unhandled error processing Razorpay webhook event_id=%s", x_razorpay_event_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook could not be processed",
        ) from exc

    if result.outcome == webhook_domain.OUTCOME_ACCEPTED:
        response_status = (
            status.HTTP_201_CREATED if result.financial_event_created else status.HTTP_200_OK
        )
    else:
        response_status = status.HTTP_200_OK

    return JSONResponse(
        status_code=response_status,
        content={
            "outcome": result.outcome,
            "financial_event_id": (
                str(result.financial_event_id) if result.financial_event_id else None
            ),
        },
    )


def _resolve_merchant_id(configured_value: str | None) -> uuid.UUID:
    if not configured_value:
        logger.error("Razorpay webhook received but RAZORPAY_DEFAULT_MERCHANT_ID is not set")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook receiver is not configured",
        )
    try:
        return uuid.UUID(configured_value)
    except ValueError as exc:
        logger.error("RAZORPAY_DEFAULT_MERCHANT_ID is not a valid UUID")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook receiver is not configured",
        ) from exc
