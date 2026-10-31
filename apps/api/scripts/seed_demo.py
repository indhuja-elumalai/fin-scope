"""Seed FIN-SCOPE with a small, realistic demo dataset.

Usage (from apps/api, with DATABASE_URL / REDIS_URL / API_KEY set and
`alembic upgrade head` already applied):

    python scripts/seed_demo.py              # seed (safe to run repeatedly)
    python scripts/seed_demo.py --reasoning  # also run ONE real reasoning call per
                                             # incident (needs ANTHROPIC_API_KEY)

What it creates, entirely through the existing domain functions (no direct
inserts, no domain changes):

  * Aurora Retail (demo)     -- a short burst of small failed payments.
                                Runs the full loop: investigation -> simulations
                                -> decision (policy ALLOWED) -> sandbox action
                                -> outcome verification. The verifier compares
                                the projection with an independent sandbox
                                observation, so FAILED / PARTIALLY_VERIFIED is
                                an expected, honest outcome, not an error.
  * Northwind Travel (demo)  -- large failed payments plus gateway degradation.
                                Runs up to the decision, which policy escalates
                                (REQUIRES_HUMAN_APPROVAL), so no action is taken.
  * Lumen Subscriptions (demo) -- healthy traffic only. Its investigation
                                correctly reports "no incident".

Idempotency:
  * Merchants are matched by name; events use a stable `external_reference`
    under source "demo_seed", so ingestion replays instead of duplicating.
  * Events are anchored to a fixed point in time (the first seed run), and
    investigations run with `as_of` set to that anchor, so a re-run sees the
    same evidence window.
  * A merchant that already has an investigation is skipped entirely, so
    re-running never adds duplicate investigations, simulations or decisions.

Reasoning (the one AI step) is OFF by default so seeding never spends
Anthropic credits. With --reasoning it uses the same provider the API uses,
once per incident, and the result is persisted like any other run.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Allow `python scripts/seed_demo.py` from apps/api without installing a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.domain import actions as actions_domain  # noqa: E402
from app.domain import decisions as decisions_domain  # noqa: E402
from app.domain import events as events_domain  # noqa: E402
from app.domain import investigations as investigations_domain  # noqa: E402
from app.domain import merchants as merchants_domain  # noqa: E402
from app.domain import reasoning as reasoning_domain  # noqa: E402
from app.domain import simulation as simulation_domain  # noqa: E402
from app.domain import verifications as verifications_domain  # noqa: E402
from app.models.financial_event import FinancialEvent  # noqa: E402
from app.models.investigation import Investigation  # noqa: E402
from app.models.merchant import Merchant  # noqa: E402

SOURCE = "demo_seed"


@dataclass(frozen=True)
class DemoEvent:
    key: str
    event_type: str
    minutes_before_anchor: int
    amount: str | None
    status: str | None


@dataclass(frozen=True)
class DemoMerchant:
    slug: str
    name: str
    segment: str
    events: tuple[DemoEvent, ...]
    scenarios: tuple[str, ...]
    run_action: bool


DEMO_MERCHANTS: tuple[DemoMerchant, ...] = (
    DemoMerchant(
        slug="aurora",
        name="Aurora Retail (demo)",
        segment="ecommerce",
        events=(
            DemoEvent("ok-1", "payment_succeeded", 95, "1499.00", "captured"),
            DemoEvent("ok-2", "payment_succeeded", 70, "899.00", "captured"),
            DemoEvent("fail-1", "payment_failed", 48, "649.00", "failed"),
            DemoEvent("fail-2", "payment_failed", 41, "1199.00", "failed"),
            DemoEvent("ok-3", "payment_succeeded", 33, "2499.00", "captured"),
            DemoEvent("fail-3", "payment_failed", 27, "449.00", "failed"),
            DemoEvent("fail-4", "payment_failed", 19, "799.00", "failed"),
            DemoEvent("delay-1", "settlement_delayed", 12, "350.00", "pending"),
            DemoEvent("fail-5", "payment_failed", 6, "549.00", "failed"),
        ),
        scenarios=("DO_NOTHING", "RETRY_AFFECTED_PAYMENTS", "TARGET_AFFECTED_EVENT_TYPE"),
        run_action=True,
    ),
    DemoMerchant(
        slug="northwind",
        name="Northwind Travel (demo)",
        segment="travel",
        events=(
            DemoEvent("ok-1", "payment_succeeded", 85, "18450.00", "captured"),
            DemoEvent("gw-1", "gateway_degraded", 52, None, "degraded"),
            DemoEvent("fail-1", "payment_failed", 47, "24999.00", "failed"),
            DemoEvent("fail-2", "payment_failed", 39, "31250.00", "failed"),
            DemoEvent("gw-2", "gateway_degraded", 30, None, "degraded"),
            DemoEvent("fail-3", "payment_failed", 22, "18990.00", "failed"),
            DemoEvent("fail-4", "payment_failed", 14, "42100.00", "failed"),
            DemoEvent("fail-5", "payment_failed", 5, "27600.00", "failed"),
        ),
        scenarios=("DO_NOTHING", "RETRY_AFFECTED_PAYMENTS", "REROUTE_PROVIDER"),
        run_action=False,
    ),
    DemoMerchant(
        slug="lumen",
        name="Lumen Subscriptions (demo)",
        segment="saas",
        events=(
            DemoEvent("ok-1", "payment_succeeded", 55, "499.00", "captured"),
            DemoEvent("ok-2", "payment_succeeded", 40, "999.00", "captured"),
            DemoEvent("refund-1", "refund_issued", 25, "499.00", "processed"),
            DemoEvent("ok-3", "payment_succeeded", 10, "1999.00", "captured"),
        ),
        scenarios=(),
        run_action=False,
    ),
)


def _log(message: str) -> None:
    print(f"[seed-demo] {message}")


def _get_or_create_merchant(db: Session, spec: DemoMerchant) -> Merchant:
    existing = db.scalars(select(Merchant).where(Merchant.name == spec.name)).first()
    if existing is not None:
        _log(f"merchant exists: {spec.name}")
        return existing
    merchant = merchants_domain.create_merchant(db, name=spec.name, segment=spec.segment)
    _log(f"merchant created: {spec.name}")
    return merchant


def _anchor_for(db: Session, merchant: Merchant, spec: DemoMerchant) -> datetime:
    """The fixed point in time this merchant's demo events hang off.

    On the first run it is "now"; afterwards it is reconstructed from the
    already-ingested demo events, so re-runs reuse the same window.
    """
    earliest = db.scalar(
        select(func.min(FinancialEvent.occurred_at)).where(
            FinancialEvent.merchant_id == merchant.id, FinancialEvent.source == SOURCE
        )
    )
    if earliest is None:
        return datetime.now(UTC).replace(microsecond=0)
    oldest_offset = max(e.minutes_before_anchor for e in spec.events)
    return earliest + timedelta(minutes=oldest_offset)


def _ingest_events(db: Session, merchant: Merchant, spec: DemoMerchant, anchor: datetime) -> None:
    created = 0
    for item in spec.events:
        _, was_created = events_domain.ingest_event(
            db,
            merchant_id=merchant.id,
            event_type=item.event_type,
            source=SOURCE,
            external_reference=f"demo-{spec.slug}-{item.key}",
            amount=Decimal(item.amount) if item.amount is not None else None,
            currency="INR" if item.amount is not None else None,
            status=item.status,
            payload={"seed": "demo", "merchant": spec.slug, "key": item.key},
            occurred_at=anchor - timedelta(minutes=item.minutes_before_anchor),
        )
        created += int(was_created)
    _log(f"  events: {created} new, {len(spec.events) - created} already present")


def _run_loop(
    db: Session, merchant: Merchant, spec: DemoMerchant, anchor: datetime, with_reasoning: bool
) -> None:
    already = db.scalar(
        select(func.count()).select_from(Investigation).where(
            Investigation.merchant_id == merchant.id
        )
    )
    if already:
        _log(f"  investigation already exists ({already}); skipping loop")
        return

    investigation = investigations_domain.run_investigation(
        db, merchant_id=merchant.id, as_of=anchor
    )
    _log(
        f"  investigation {investigation.id}: incident={investigation.incident_detected}, "
        f"evidence={investigation.evidence_event_count}"
    )
    if not investigation.incident_detected:
        return

    if with_reasoning:
        # Imported lazily: only needed when the operator explicitly opts in.
        from app.routers.investigations import get_reasoning_provider

        provider = get_reasoning_provider()
        if provider is None:
            _log("  reasoning skipped: ANTHROPIC_API_KEY is not configured")
        else:
            result = reasoning_domain.run_reasoning(
                db, investigation_id=investigation.id, provider=provider
            )
            _log(f"  reasoning: {result.status} ({len(result.hypotheses)} hypotheses)")

    for scenario in spec.scenarios:
        sim = simulation_domain.run_simulation(
            db, investigation_id=investigation.id, scenario=scenario
        )
        _log(f"  simulation {scenario}: {sim.status}")

    if not spec.scenarios:
        return

    decision = decisions_domain.run_decision(db, investigation_id=investigation.id)
    _log(f"  decision: {decision.status}, policy={decision.policy_decision}")

    if not spec.run_action:
        return

    action, _ = actions_domain.run_action(
        db, investigation_id=investigation.id, decision_id=decision.id
    )
    _log(f"  sandbox action: {action.status}")

    verification, _ = verifications_domain.run_verification(
        db, investigation_id=investigation.id, action_id=action.id
    )
    _log(f"  verification: {verification.status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed FIN-SCOPE demo data (idempotent).")
    parser.add_argument(
        "--reasoning",
        action="store_true",
        help="Also run one real reasoning call per incident (uses ANTHROPIC_API_KEY).",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        for spec in DEMO_MERCHANTS:
            merchant = _get_or_create_merchant(db, spec)
            anchor = _anchor_for(db, merchant, spec)
            _ingest_events(db, merchant, spec, anchor)
            _run_loop(db, merchant, spec, anchor, args.reasoning)
    finally:
        db.close()
    _log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
