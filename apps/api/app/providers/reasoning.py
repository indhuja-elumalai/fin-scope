"""Reasoning provider abstraction.

app.domain.reasoning (the caller) never talks to a specific vendor SDK or
HTTP API directly -- it only depends on the ReasoningProvider protocol
below. This is the one file in the codebase allowed to know the shape of a
specific hosted reasoning API's request/response; everything else works
with the plain ReasoningContext / RawHypothesis data shapes defined here.

Why this boundary matters for FIN-SCOPE specifically: the provider is
untrusted input. It receives a read-only, already-sanitized summary of one
investigation's facts (build_context in app.domain.reasoning) and returns
free-form structured text. app.domain.reasoning is responsible for treating
everything this module returns as a claim to be validated, not a fact to be
trusted -- this module's only job is the HTTP mechanics: build the request,
parse JSON off the wire, and raise ReasoningProviderError for anything that
prevents that (missing configuration, network failure, timeout, non-2xx,
non-JSON body). It deliberately does NOT try to validate hypothesis
structure or evidence grounding itself -- that validation belongs to
app.domain.reasoning, in one place, regardless of which provider produced
the output.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

# The hosted reasoning API endpoint itself: an internal implementation
# detail of this one adapter, not exposed as configuration -- there is no
# concrete reason yet for a caller to ever need a different URL/version.
_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_MAX_OUTPUT_TOKENS = 2048

# Phase 9 defaults for the two knobs that ARE configurable (see
# Settings.anthropic_model / Settings.anthropic_timeout_seconds in
# app.config, and HostedReasoningProvider.__init__ below). Used only as
# this class's own constructor defaults so existing call sites/tests that
# construct HostedReasoningProvider(api_key=...) without the new keyword
# arguments keep working unchanged; app.routers.investigations.
# get_reasoning_provider() always passes the real configured values
# explicitly rather than relying on these.
_DEFAULT_MODEL = "claude-sonnet-5"
_DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class EvidenceRef:
    """One evidence item as the provider is allowed to see it.

    Deliberately narrower than the full investigation evidence snapshot
    (app.domain.investigations._event_snapshot): a reasoning provider gets
    only what it needs to reason and cite, not the full internal record.
    """

    event_id: str
    event_type: str
    source: str
    amount: str | None
    currency: str | None
    occurred_at: str


@dataclass(frozen=True)
class ReasoningContext:
    """The controlled, read-only representation of one investigation that a
    reasoning provider is allowed to see.

    Built exclusively from an already-persisted Investigation row (see
    app.domain.reasoning.build_context) -- this module has no database
    access and cannot query financial_events, investigations, or any other
    table itself. This is the entire boundary of what the reasoning layer
    can know: it cannot discover evidence the investigation did not already
    record.
    """

    investigation_id: str
    incident_detected: bool
    evidence_event_count: int
    event_type_counts: dict[str, int]
    dominant_signal_event_type: str | None
    dominant_signal_share: str | None
    impact_breakdown: list[dict]
    impact_amount_unknown_count: int
    evidence: list[EvidenceRef]


@dataclass(frozen=True)
class RawHypothesis:
    """Exactly what the provider claimed, before any grounding validation.

    Every field is untrusted at this point -- confidence may not be one of
    the allowed levels, evidence IDs may not exist, ranks may collide. See
    app.domain.reasoning._validate_hypotheses for the validation this feeds
    into.
    """

    hypothesis_id: str
    rank: int
    title: str
    explanation: str
    confidence: str
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    uncertainty: str


@dataclass(frozen=True)
class RawReasoningResult:
    """The provider's raw structured output, before grounding validation."""

    hypotheses: list[RawHypothesis]


class ReasoningProviderError(Exception):
    """Reasoning could not be obtained from the provider.

    Covers every infrastructure-level failure mode: not configured, network
    error, timeout, non-2xx response, or a response that is not valid JSON
    at all. app.domain.reasoning maps this to status="unavailable" -- a
    distinct outcome from a provider response that parses as JSON but fails
    hypothesis validation (status="invalid_output"), because the two imply
    different things (retry later vs. this response was untrustworthy).
    """


class ReasoningProvider(Protocol):
    """The only interface app.domain.reasoning is allowed to depend on."""

    def generate_hypotheses(self, context: ReasoningContext) -> RawReasoningResult:
        """Return raw, not-yet-validated hypotheses for the given context.

        Raises ReasoningProviderError if no result could be obtained at all.
        Never raises for "the provider returned something that doesn't
        validate" -- that is a RawReasoningResult the caller must validate,
        not a provider-level failure.
        """
        ...


_SYSTEM_PROMPT = """You are a financial incident investigation assistant. You are given a \
deterministic evidence summary already computed by a rule-based system -- you must not \
recompute or contradict its facts (event counts, amounts, currencies, timestamps). Your only \
job is to propose plausible, ranked, evidence-grounded explanations ("hypotheses") for the \
detected pattern.

Rules you must follow exactly:
- Every event_id you cite in supporting_evidence or contradicting_evidence MUST be copied \
verbatim from the evidence list you were given. Never invent an event_id, amount, timestamp, \
merchant, currency, or event type that was not in the input.
- confidence must be exactly one of: "high", "medium", "low". This is a qualitative, \
model-derived judgment -- never a numeric probability.
- rank must be a positive integer, unique per hypothesis, starting at 1 for the most-supported \
hypothesis.
- hypothesis_id must be unique per hypothesis (e.g. "h1", "h2").
- uncertainty must name what would make this hypothesis more or less certain -- missing \
evidence, an alternative explanation you could not rule out, etc. Never claim certainty.
- You are proposing plausible explanations, not a confirmed root cause. Do not use the words \
"confirmed", "proven", or "certain" anywhere in your output.
- If the evidence is too sparse or ambiguous to support any hypothesis, return an empty \
hypotheses list rather than guessing.

Respond with ONLY a JSON object of the exact shape:
{"hypotheses": [{"hypothesis_id": str, "rank": int, "title": str, "explanation": str, \
"confidence": "high"|"medium"|"low", "supporting_evidence": [str, ...], \
"contradicting_evidence": [str, ...], "uncertainty": str}, ...]}
No prose before or after the JSON."""


class HostedReasoningProvider:
    """Adapter for a hosted reasoning API (see Settings.anthropic_api_key,
    Settings.anthropic_model, Settings.anthropic_timeout_seconds,
    Settings.anthropic_workspace_id).

    This is the only class in the codebase that constructs an HTTP request
    to the reasoning provider. Everything above this class in the call
    stack works with ReasoningContext / RawReasoningResult only.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = _DEFAULT_MODEL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        workspace_id: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._workspace_id = workspace_id

    def generate_hypotheses(self, context: ReasoningContext) -> RawReasoningResult:
        request_body = {
            "model": self._model,
            "max_tokens": _MAX_OUTPUT_TOKENS,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": _render_context(context)}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        # Some Anthropic API keys are identity-linked to a Console
        # workspace and require this header to authenticate at all -- only
        # sent when a workspace id is actually configured, so a standalone
        # key's request is byte-for-byte unchanged from before this was
        # added.
        if self._workspace_id:
            headers["anthropic-workspace-id"] = self._workspace_id
        try:
            response = httpx.post(
                _API_URL,
                json=request_body,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ReasoningProviderError("reasoning provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise ReasoningProviderError("reasoning provider request failed") from exc

        if response.status_code != 200:
            try:
                error_body = response.json()
                error_type = error_body.get("error", {}).get("type")
                error_message = error_body.get("error", {}).get("message")
            except (ValueError, AttributeError, TypeError):
                error_type = None
                error_message = None

            # Full upstream diagnostic detail (which can include
            # account/billing-specific text from the third-party provider,
            # e.g. an insufficient-credits message) is logged server-side
            # only. The exception message below is what propagates into
            # InvestigationReasoning.failure_reason and from there the API
            # response and the browser UI -- it is deliberately generic,
            # carrying only the HTTP status code, never provider-supplied
            # text. This does not change the "unavailable" status contract:
            # any non-200 response still raises ReasoningProviderError,
            # which app.domain.reasoning still maps to status="unavailable".
            detail = error_message or response.text[:500]
            if error_type:
                detail = f"{error_type}: {detail}"
            logger.warning(
                "reasoning provider returned HTTP %s: %s", response.status_code, detail
            )

            raise ReasoningProviderError(
                f"reasoning provider returned an error (HTTP {response.status_code})"
            )

        try:
            response_body = response.json()
            text = "".join(
                block.get("text", "")
                for block in response_body.get("content", [])
                if block.get("type") == "text"
            )
            parsed = json.loads(text)
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            raise ReasoningProviderError(
                "reasoning provider response was not valid structured output"
            ) from exc

        raw_hypotheses = parsed.get("hypotheses") if isinstance(parsed, dict) else None
        if not isinstance(raw_hypotheses, list):
            raise ReasoningProviderError(
                "reasoning provider response did not contain a hypotheses list"
            )

        hypotheses = []
        for item in raw_hypotheses:
            if not isinstance(item, dict):
                raise ReasoningProviderError("reasoning provider returned a malformed hypothesis")
            try:
                hypotheses.append(
                    RawHypothesis(
                        hypothesis_id=str(item["hypothesis_id"]),
                        rank=item["rank"],
                        title=str(item["title"]),
                        explanation=str(item["explanation"]),
                        confidence=str(item["confidence"]),
                        supporting_evidence=[str(e) for e in item.get("supporting_evidence", [])],
                        contradicting_evidence=[
                            str(e) for e in item.get("contradicting_evidence", [])
                        ],
                        uncertainty=str(item.get("uncertainty", "")),
                    )
                )
            except (KeyError, TypeError) as exc:
                raise ReasoningProviderError(
                    "reasoning provider returned a malformed hypothesis"
                ) from exc

        return RawReasoningResult(hypotheses=hypotheses)


def _render_context(context: ReasoningContext) -> str:
    """A compact, deterministic JSON rendering of the context for the prompt."""
    return json.dumps(
        {
            "investigation_id": context.investigation_id,
            "incident_detected": context.incident_detected,
            "evidence_event_count": context.evidence_event_count,
            "event_type_counts": context.event_type_counts,
            "dominant_signal_event_type": context.dominant_signal_event_type,
            "dominant_signal_share": context.dominant_signal_share,
            "impact_breakdown": context.impact_breakdown,
            "impact_amount_unknown_count": context.impact_amount_unknown_count,
            "evidence": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "source": e.source,
                    "amount": e.amount,
                    "currency": e.currency,
                    "occurred_at": e.occurred_at,
                }
                for e in context.evidence
            ],
        },
        indent=2,
    )
