"""Razorpay webhook ingestion -- Phase 10, Milestone 2.

Two layers, deliberately split the same way app.domain.sandbox_executor
(pure) and app.domain.actions (DB-touching orchestration) already are:

  - verify_signature() and map_webhook_payload() are pure: no database, no
    network, no randomness, no current time. Given the same input they
    always return the same output, and they raise nothing that depends on
    anything but their own arguments. This is the part that can be (and
    is, in tests/test_razorpay_webhooks_domain.py) exhaustively unit
    tested without a database.
  - process_webhook() is the DB-touching orchestrator: idempotency ledger
    lookup, calling the pure functions above, delegating the actual
    financial-state write to the EXISTING app.domain.events.ingest_event
    (never a parallel ingestion path -- see Phase 10 safety rule 5/7),
    and recording the terminal outcome. This is exercised through
    tests/test_razorpay_webhooks_router.py (TestClient, real DB), the
    same tier app.domain.actions already is.

Security boundary this module exists to enforce (Phase 10 safety rule 8):
nothing below ever mutates FinancialEvent state from a payload whose
signature has not already been verified against the raw body, and only
the three explicitly supported event types (SUPPORTED_EVENT_TYPES) can
reach ingest_event at all -- an unrecognized `event` value is acknowledged
and ignored, never processed "just in case".
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import events as event_domain
from app.models.audit_log import AuditLog
from app.models.razorpay_webhook_event import RazorpayWebhookEvent

logger = logging.getLogger(__name__)

# The only Razorpay webhook event types this phase acts on (Phase 10 plan
# section 4 / Milestone 2 scope). Adding to this set is a deliberate,
# reviewed change, never an incidental one -- see the module docstring's
# security boundary note.
SUPPORTED_EVENT_TYPES = frozenset({"payment.failed", "payment.captured", "order.paid"})

# Maps a Razorpay event type to the EXISTING FIN-SCOPE event-type
# vocabulary (app.domain.events.KNOWN_EVENT_TYPES) -- deliberately reused,
# never a second parallel vocabulary. Both payment.captured and order.paid
# represent the same underlying business fact (a payment succeeded) and
# map to the same FIN-SCOPE type; see map_webhook_payload's docstring for
# how that keeps them from producing two FinancialEvent rows for one
# payment when both webhooks are configured.
_EVENT_TYPE_MAP = {
    "payment.failed": "payment_failed",
    "payment.captured": "payment_succeeded",
    "order.paid": "payment_succeeded",
}
assert _EVENT_TYPE_MAP.keys() == SUPPORTED_EVENT_TYPES
assert set(_EVENT_TYPE_MAP.values()) <= event_domain.KNOWN_EVENT_TYPES

_WEBHOOK_SOURCE = "razorpay_webhook"

# Outcome labels persisted on RazorpayWebhookEvent.outcome -- see that
# model's docstring for why only these three (all terminal/deterministic)
# are ever ledger-recorded.
OUTCOME_ACCEPTED = "accepted"
OUTCOME_IGNORED_UNSUPPORTED = "ignored_unsupported_event"
OUTCOME_REJECTED_MALFORMED = "rejected_malformed_payload"


class InvalidSignatureError(Exception):
    """The signature header did not verify against the raw body."""


class MalformedPayloadError(Exception):
    """A supported event's payload is missing a field it cannot be safely
    processed without. Never raised for an unsupported event type -- that
    is handled as OUTCOME_IGNORED_UNSUPPORTED, not an error."""


class WebhookConfigurationError(Exception):
    """Processing cannot proceed due to missing/invalid FIN-SCOPE
    configuration (e.g. razorpay_default_merchant_id) -- not the
    payload's fault, not Razorpay's fault, and deliberately NEVER
    ledger-recorded: see process_webhook, this must stay retryable."""


def verify_signature(raw_body: bytes, signature_header: str, webhook_secret: str) -> bool:
    """HMAC-SHA256 over the RAW, unparsed request body, keyed by the
    configured webhook secret -- exactly Razorpay's documented webhook
    signature scheme (verified during Phase 10 planning). Never operates
    on a parsed/re-serialized body: re-serializing JSON can change byte
    layout (key order, whitespace) and silently break verification, which
    is why callers must pass the exact bytes read off the request.

    Constant-time comparison (hmac.compare_digest) -- a naive `==` would
    leak timing information about how many leading bytes matched.
    """
    expected = hmac.new(
        webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@dataclass(frozen=True)
class MappedFinancialEvent:
    """Pure output of map_webhook_payload -- exactly the arguments
    app.domain.events.ingest_event needs, nothing more. Never touches the
    database itself."""

    event_type: str
    external_reference: str
    amount: Decimal | None
    currency: str | None
    status: str | None
    occurred_at: datetime
    payload: dict


def _to_major_units(minor_amount: Any) -> Decimal | None:
    """Razorpay amounts are always in the smallest currency unit (paise
    for INR, cents for USD/SGD, ...) -- verified during Phase 10 planning
    against Razorpay's Orders API contract and consistent with the
    payment.captured sample payload. FinancialEvent.amount is a 2-decimal
    major-unit Numeric(18,2), matching how every other source in this
    codebase already populates it (see tests/test_events.py's "199.99").
    This divides by 100 uniformly; currencies with a different minor-unit
    exponent (e.g. JPY) are not handled specially here, an existing
    limitation of FinancialEvent.amount's fixed 2-decimal shape, not
    something introduced by this module.
    """
    if minor_amount is None:
        return None
    try:
        return Decimal(str(minor_amount)) / Decimal(100)
    except (ValueError, ArithmeticError):
        return None


def map_webhook_payload(razorpay_event_type: str, body: dict) -> MappedFinancialEvent:
    """Map a verified, parsed Razorpay webhook body into the shape
    app.domain.events.ingest_event needs. Raises MalformedPayloadError if
    a required field is missing -- never guesses, never invents a value.

    Only called for razorpay_event_type in SUPPORTED_EVENT_TYPES; callers
    are responsible for that check (process_webhook does it before this
    is ever invoked).

    external_reference is deliberately the Razorpay PAYMENT id (never the
    order id) for all three supported event types, when a payment entity
    is present in the payload -- payment.captured and order.paid can both
    fire for the same underlying payment (Razorpay's own documented
    behavior; delivery order between them is not guaranteed), and using
    the same external_reference for both lets FinancialEvent's EXISTING
    (source, external_reference) dedup in app.domain.events.ingest_event
    naturally collapse them into one row, whichever arrives first --
    reusing that existing idempotency mechanism instead of inventing a
    second one here. order.paid falls back to the order id only if no
    payment entity is present in its payload.
    """
    payload_section = body.get("payload")
    if not isinstance(payload_section, dict):
        raise MalformedPayloadError("webhook body has no 'payload' object")

    payment_entity = _entity(payload_section, "payment")

    if razorpay_event_type in ("payment.failed", "payment.captured"):
        if payment_entity is None:
            raise MalformedPayloadError(
                f"{razorpay_event_type} payload has no payload.payment.entity"
            )
        payment_id = payment_entity.get("id")
        if not payment_id:
            raise MalformedPayloadError(f"{razorpay_event_type} payment entity has no id")
        return MappedFinancialEvent(
            event_type=_EVENT_TYPE_MAP[razorpay_event_type],
            external_reference=str(payment_id),
            amount=_to_major_units(payment_entity.get("amount")),
            currency=_currency(payment_entity.get("currency")),
            status=_optional_str(payment_entity.get("status")),
            occurred_at=_occurred_at(body),
            payload=body,
        )

    if razorpay_event_type == "order.paid":
        order_entity = _entity(payload_section, "order")
        if order_entity is None:
            raise MalformedPayloadError("order.paid payload has no payload.order.entity")
        order_id = order_entity.get("id")
        if not order_id:
            raise MalformedPayloadError("order.paid order entity has no id")
        # Prefer the payment id (see docstring above); fall back to the
        # order id only when no payment entity was included -- this
        # fallback is a documented assumption, not a verified guarantee:
        # Razorpay's order.paid sample payload could not be confirmed
        # against live documentation during Phase 10 planning/Milestone 2
        # (the docs page did not render a JSON example). Verify against a
        # real Dashboard-delivered order.paid payload before Milestone 4.
        if payment_entity is not None and payment_entity.get("id"):
            external_reference = str(payment_entity["id"])
            amount_source = payment_entity
        else:
            external_reference = str(order_id)
            amount_source = order_entity
        return MappedFinancialEvent(
            event_type=_EVENT_TYPE_MAP[razorpay_event_type],
            external_reference=external_reference,
            amount=_to_major_units(
                amount_source.get("amount_paid", amount_source.get("amount"))
            ),
            currency=_currency(order_entity.get("currency")),
            status=_optional_str(order_entity.get("status")),
            occurred_at=_occurred_at(body),
            payload=body,
        )

    # Unreachable if callers respect SUPPORTED_EVENT_TYPES, but never
    # silently falls through to producing a MappedFinancialEvent for an
    # event type this module does not know how to map.
    raise MalformedPayloadError(f"no mapping defined for event type {razorpay_event_type!r}")


def _entity(payload_section: dict, key: str) -> dict | None:
    section = payload_section.get(key)
    if not isinstance(section, dict):
        return None
    entity = section.get("entity")
    return entity if isinstance(entity, dict) else None


def _optional_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _currency(value: Any) -> str | None:
    return str(value).upper() if value else None


def _occurred_at(body: dict) -> datetime:
    """The webhook envelope's own created_at (unix seconds) -- verified
    against the payment.captured sample payload during Phase 10 planning.
    Falls back to now() only if genuinely absent, so a malformed/missing
    timestamp never blocks ingestion of an otherwise-valid event."""
    created_at = body.get("created_at")
    if isinstance(created_at, (int, float)):
        try:
            return datetime.fromtimestamp(created_at, tz=UTC)
        except (ValueError, OSError, OverflowError):
            pass
    return datetime.now(UTC)


@dataclass(frozen=True)
class WebhookProcessingResult:
    outcome: str
    financial_event_id: uuid.UUID | None
    financial_event_created: bool


def process_webhook(
    db: Session,
    *,
    razorpay_event_id: str,
    razorpay_event_type: str,
    body: dict,
    merchant_id: uuid.UUID,
) -> WebhookProcessingResult:
    """Orchestrate one already-signature-verified webhook delivery.

    Callers (the router) are responsible for: reading the raw body,
    calling verify_signature() themselves BEFORE this function is ever
    invoked, and confirming both the signature and x-razorpay-event-id
    header are present. This function trusts that has already happened --
    it does not re-verify the signature, because it never sees the raw
    bytes, only the already-parsed body.

    Ledger dedup (idempotency): if razorpay_event_id already has a
    RazorpayWebhookEvent row, this is a replay of an already-terminally-
    processed delivery -- returns the previously recorded outcome without
    re-running ingest_event or writing a second AuditLog row. This is the
    ONLY place replay short-circuits; every other code path below runs in
    full for a genuinely new event_id.
    """
    existing = db.scalars(
        select(RazorpayWebhookEvent).where(
            RazorpayWebhookEvent.razorpay_event_id == razorpay_event_id
        )
    ).first()
    if existing is not None:
        return WebhookProcessingResult(
            outcome=existing.outcome,
            financial_event_id=existing.financial_event_id,
            financial_event_created=False,
        )

    if razorpay_event_type not in SUPPORTED_EVENT_TYPES:
        _record_ledger(
            db,
            razorpay_event_id=razorpay_event_id,
            razorpay_event_type=razorpay_event_type,
            outcome=OUTCOME_IGNORED_UNSUPPORTED,
            financial_event_id=None,
            raw_payload=body,
        )
        db.add(
            AuditLog(
                event_type="razorpay_webhook_ignored",
                entity_type="razorpay_webhook_event",
                entity_id=razorpay_event_id,
                actor="system",
                payload={"razorpay_event_type": razorpay_event_type},
            )
        )
        db.commit()
        return WebhookProcessingResult(
            outcome=OUTCOME_IGNORED_UNSUPPORTED, financial_event_id=None,
            financial_event_created=False,
        )

    try:
        mapped = map_webhook_payload(razorpay_event_type, body)
    except MalformedPayloadError as exc:
        _record_ledger(
            db,
            razorpay_event_id=razorpay_event_id,
            razorpay_event_type=razorpay_event_type,
            outcome=OUTCOME_REJECTED_MALFORMED,
            financial_event_id=None,
            raw_payload=body,
        )
        db.add(
            AuditLog(
                event_type="razorpay_webhook_rejected",
                entity_type="razorpay_webhook_event",
                entity_id=razorpay_event_id,
                actor="system",
                # Never the raw payload here -- only a fixed, non-secret
                # reason string, same discipline as every other
                # failure_reason in this codebase (e.g.
                # InvestigationAction.rejection_reason).
                payload={"razorpay_event_type": razorpay_event_type, "reason": str(exc)},
            )
        )
        db.commit()
        raise

    # ingest_event itself commits and may raise for reasons unrelated to
    # this payload (a genuine DB/persistence failure) -- deliberately NOT
    # caught here. The router maps that to a 5xx; no ledger row is
    # written for it (see WebhookConfigurationError / module docstring),
    # so a retried delivery will actually reprocess once whatever failed
    # is fixed.
    event, created = event_domain.ingest_event(
        db,
        merchant_id=merchant_id,
        event_type=mapped.event_type,
        source=_WEBHOOK_SOURCE,
        external_reference=mapped.external_reference,
        amount=mapped.amount,
        currency=mapped.currency,
        status=mapped.status,
        payload=mapped.payload,
        occurred_at=mapped.occurred_at,
    )

    _record_ledger(
        db,
        razorpay_event_id=razorpay_event_id,
        razorpay_event_type=razorpay_event_type,
        outcome=OUTCOME_ACCEPTED,
        financial_event_id=event.id,
        raw_payload=body,
    )
    db.add(
        AuditLog(
            event_type="razorpay_webhook_accepted",
            entity_type="razorpay_webhook_event",
            entity_id=razorpay_event_id,
            actor="system",
            payload={
                "razorpay_event_type": razorpay_event_type,
                "financial_event_id": str(event.id),
                "financial_event_created": created,
            },
        )
    )
    db.commit()

    return WebhookProcessingResult(
        outcome=OUTCOME_ACCEPTED, financial_event_id=event.id, financial_event_created=created
    )


def _record_ledger(
    db: Session,
    *,
    razorpay_event_id: str,
    razorpay_event_type: str,
    outcome: str,
    financial_event_id: uuid.UUID | None,
    raw_payload: dict,
) -> None:
    db.add(
        RazorpayWebhookEvent(
            razorpay_event_id=razorpay_event_id,
            razorpay_event_type=razorpay_event_type,
            outcome=outcome,
            financial_event_id=financial_event_id,
            raw_payload=raw_payload,
        )
    )
