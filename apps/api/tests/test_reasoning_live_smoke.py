"""ONE deliberate, real Anthropic API call -- opt-in only, never automatic.

This entire file is SKIPPED (not run, not collected-and-errored -- skipped)
unless RUN_LIVE_CLAUDE_TEST=1 is explicitly set in the environment. It is
never part of a normal `pytest` invocation, never runs in CI (no CI
configuration in this repository sets that variable, and none should), and
makes exactly one HTTP request to the real hosted reasoning API when it
does run -- no retry, no loop, no fallback provider, no second attempt on
failure. This is the one and only place in the test suite that is allowed
to spend a real Anthropic API credit, and only when a human deliberately
asks it to:

    RUN_LIVE_CLAUDE_TEST=1 pytest tests/test_reasoning_live_smoke.py -v -s

Requires a real ANTHROPIC_API_KEY already configured in .env (see
app.config.Settings). This file never hardcodes, reads from anywhere else,
prints, or logs that key -- it only passes it through to
HostedReasoningProvider exactly as app.routers.investigations.
get_reasoning_provider() already does for a real request.
"""
import os

import pytest

from app.config import get_settings
from app.providers.reasoning import (
    EvidenceRef,
    HostedReasoningProvider,
    ReasoningContext,
    ReasoningProviderError,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_CLAUDE_TEST") != "1",
    reason="live Anthropic smoke test is opt-in only -- set RUN_LIVE_CLAUDE_TEST=1 to run it",
)


def test_one_real_hypothesis_generation_call() -> None:
    """Exactly one real call to HostedReasoningProvider.generate_hypotheses,
    against a small hand-built ReasoningContext -- never through the
    database, never through the FastAPI app, never through /reason. This
    is a smoke test (does the real wire call actually work end-to-end),
    not a correctness evaluation -- run app.eval.reasoning_eval separately
    and offline against whatever this call's result is used to produce.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY is not configured -- nothing to smoke-test")

    provider = HostedReasoningProvider(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        timeout_seconds=settings.anthropic_timeout_seconds,
        workspace_id=settings.anthropic_workspace_id,
    )

    context = ReasoningContext(
        investigation_id="00000000-0000-0000-0000-000000000000",
        incident_detected=True,
        evidence_event_count=3,
        event_type_counts={"payment_failed": 3},
        dominant_signal_event_type="payment_failed",
        dominant_signal_share="1.0000",
        impact_breakdown=[{"currency": "INR", "amount": "150.00"}],
        impact_amount_unknown_count=0,
        evidence=[
            EvidenceRef(
                event_id="11111111-1111-1111-1111-111111111111",
                event_type="payment_failed",
                source="manual",
                amount="50.00",
                currency="INR",
                occurred_at="2026-01-01T00:00:00+00:00",
            ),
            EvidenceRef(
                event_id="22222222-2222-2222-2222-222222222222",
                event_type="payment_failed",
                source="manual",
                amount="50.00",
                currency="INR",
                occurred_at="2026-01-01T00:05:00+00:00",
            ),
            EvidenceRef(
                event_id="33333333-3333-3333-3333-333333333333",
                event_type="payment_failed",
                source="manual",
                amount="50.00",
                currency="INR",
                occurred_at="2026-01-01T00:10:00+00:00",
            ),
        ],
    )

    try:
        result = provider.generate_hypotheses(context)  # the one deliberate live call
    except ReasoningProviderError as exc:
        pytest.fail(f"live call to the real Anthropic API failed: {exc}")

    print(f"\nreceived {len(result.hypotheses)} hypothes(is/es) from the real provider")
    for h in result.hypotheses:
        print(f"  - [{h.confidence}] {h.title}")

    # Structural sanity only -- not a grounding/quality evaluation. Real
    # evidence-grounding validation belongs to app.domain.reasoning, and
    # controlled measurement belongs to app.eval.reasoning_eval, both
    # exercised offline elsewhere in this suite.
    assert isinstance(result.hypotheses, list)
