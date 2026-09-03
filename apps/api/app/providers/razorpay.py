"""Razorpay TEST-mode client -- Phase 10, Milestone 1.

Mirrors the boundary app.providers.reasoning.HostedReasoningProvider
already establishes for the hosted reasoning API: this is the one class in
the codebase allowed to know the shape of the Razorpay HTTP API. Nothing
above it in the call stack is allowed to import httpx or know Razorpay's
request/response shapes -- callers work with RazorpayOrder and the two
error types below only.

Why this boundary matters for FIN-SCOPE specifically (see the Phase 10
plan, safety rules 2-5): this client is never constructed from, or
reachable by, anything the reasoning provider's output touches. The LLM
reasoning layer (app.domain.reasoning) proposes hypotheses only; it has no
import path to this module and never will. Only a deterministic
orchestrator, gated on an already-persisted ALLOWED InvestigationDecision
(the same precondition app.domain.actions already enforces for Phase 7's
sandbox executor), is permitted to construct and call this client -- that
orchestration does not exist yet as of Milestone 1 and is Milestone 3's
job, not this file's.

TEST-mode-only, enforced structurally, not just by convention (safety rule
1): __init__ refuses to construct at all unless BOTH (a) key_id has the
rzp_test_ prefix Razorpay itself uses to distinguish test from live keys,
and (b) test_mode_confirmed is explicitly True. Neither check alone is
trusted -- a caller cannot satisfy this by only setting
RAZORPAY_TEST_MODE_CONFIRMED=true against a live key, and cannot satisfy
it by only holding a rzp_test_-prefixed key without the explicit
confirmation flag. This fails closed at construction time, before any
network call is ever attempted; see RazorpayConfigurationError.

No live call is made by this file itself and none is exercised by its own
tests -- every test in tests/test_razorpay_provider.py mocks httpx.post,
the same discipline test_reasoning_provider.py already applies to the
reasoning provider. Milestone 4 is the only place a real TEST-mode call is
made, gated behind an explicit env flag, on separate explicit approval.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Internal implementation detail, not exposed as configuration -- mirrors
# app.providers.reasoning._API_URL. There is no concrete reason yet for a
# caller to ever need a different base URL, and making it configurable
# would open a path to accidentally pointing this client at something
# other than Razorpay.
_API_BASE_URL = "https://api.razorpay.com/v1"

# Razorpay's own documented prefix convention for distinguishing test from
# live keys (verified against Razorpay's authentication documentation
# during Phase 10 planning) -- the structural TEST-mode guard below
# depends on this being correct; it is never inferred or guessed per call.
_TEST_KEY_PREFIX = "rzp_test_"
_LIVE_KEY_PREFIX = "rzp_live_"

_DEFAULT_TIMEOUT_SECONDS = 30.0


class RazorpayConfigurationError(Exception):
    """RazorpayClient could not be safely constructed.

    Distinct from RazorpayClientError (below) on purpose: this is a
    construction-time refusal -- no network call was ever attempted and
    none ever will be for this instance. Every raise site here is a
    fail-closed safety guard (rule 1: TEST MODE ONLY), never a transport
    or upstream failure.
    """


class RazorpayClientError(Exception):
    """A Razorpay API call could not be completed or did not return a
    trustworthy response.

    Covers network failure, timeout, non-2xx response, non-JSON body, or a
    JSON body missing a field the caller cannot safely proceed without.
    Mirrors app.providers.reasoning.ReasoningProviderError's role for the
    reasoning adapter: the one error type callers of this client need to
    handle for "the call did not succeed," regardless of cause.
    """


@dataclass(frozen=True)
class RazorpayOrder:
    """A Razorpay TEST Order, as returned by the Orders API.

    Deliberately keeps `raw` alongside the few fields callers are expected
    to need -- this client does not assume Razorpay's response shape is
    exhaustively known or fixed; anything beyond id/status/amount/currency/
    receipt/amount_paid/amount_due is read from `raw` by callers that need
    it, never guessed at or invented here.
    """

    id: str
    status: str
    amount: int
    currency: str
    receipt: str | None
    amount_paid: int
    amount_due: int
    raw: dict


class RazorpayClient:
    """Adapter for the Razorpay TEST-mode HTTP API.

    This is the only class in the codebase permitted to construct an HTTP
    request to Razorpay. Everything above this class in the call stack
    works with RazorpayOrder / RazorpayClientError only -- see the module
    docstring for the full boundary this exists to enforce.
    """

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        test_mode_confirmed: bool,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not key_id.startswith(_TEST_KEY_PREFIX):
            # Deliberately does not distinguish "looks like a live key" from
            # "looks like neither" in the exception message -- both are
            # refused identically. The distinction is only surfaced in the
            # server-side log, never in a message that could end up
            # anywhere client-facing.
            looks_live = key_id.startswith(_LIVE_KEY_PREFIX)
            logger.error(
                "Refused to construct RazorpayClient: key_id does not have the "
                "test-mode prefix (looks_live=%s)",
                looks_live,
            )
            raise RazorpayConfigurationError(
                "Razorpay key_id must be a TEST-mode key (rzp_test_ prefix); "
                "refusing to construct a client for a non-test key"
            )
        if not test_mode_confirmed:
            raise RazorpayConfigurationError(
                "Razorpay TEST mode must be explicitly confirmed "
                "(RAZORPAY_TEST_MODE_CONFIRMED) before a client can be constructed"
            )
        self._key_id = key_id
        self._key_secret = key_secret
        self._timeout_seconds = timeout_seconds

    def create_order(
        self,
        *,
        amount: int,
        currency: str,
        receipt: str,
        notes: dict[str, str] | None = None,
    ) -> RazorpayOrder:
        """Create a TEST-mode Order (POST /v1/orders).

        `amount` is in the smallest currency unit (e.g. paise for INR),
        per Razorpay's documented Orders API contract -- never a decimal
        major-unit amount. `receipt` is the caller-supplied idempotency
        key Razorpay itself enforces uniqueness on: a second create_order
        call reusing the same receipt is rejected by Razorpay as a
        duplicate, not silently turned into a second Order. Callers
        (Milestone 3's orchestrator) are responsible for deriving a stable
        receipt per decision_id -- this method does not derive one itself.
        """
        request_body: dict[str, object] = {
            "amount": amount,
            "currency": currency,
            "receipt": receipt,
        }
        if notes:
            request_body["notes"] = notes

        body = self._post("/orders", request_body)

        order_id = body.get("id")
        if not order_id:
            raise RazorpayClientError("Razorpay order response did not contain an id")

        return RazorpayOrder(
            id=str(order_id),
            status=str(body.get("status", "")),
            amount=int(body.get("amount", amount)),
            currency=str(body.get("currency", currency)),
            receipt=body.get("receipt"),
            amount_paid=int(body.get("amount_paid", 0)),
            amount_due=int(body.get("amount_due", amount)),
            raw=body,
        )

    def _post(self, path: str, json_body: dict[str, object]) -> dict:
        """Shared request/error-handling mechanics for every Razorpay call
        this client makes. Basic Auth per Razorpay's documented
        authentication scheme: key_id as username, key_secret as password
        -- httpx's `auth=` tuple handles the encoding, never done by hand.
        """
        url = f"{_API_BASE_URL}{path}"
        try:
            response = httpx.post(
                url,
                json=json_body,
                auth=(self._key_id, self._key_secret),
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise RazorpayClientError("Razorpay request timed out") from exc
        except httpx.HTTPError as exc:
            raise RazorpayClientError("Razorpay request failed") from exc

        if response.status_code >= 300:
            try:
                error_body = response.json()
                error_description = error_body.get("error", {}).get("description")
                error_code = error_body.get("error", {}).get("code")
            except (ValueError, AttributeError, TypeError):
                error_description = None
                error_code = None

            # Full upstream diagnostic detail is logged server-side only --
            # same discipline as app.providers.reasoning's sanitization of
            # non-2xx responses. The exception message propagates further
            # (eventually into a persisted rejection_reason, per the Phase
            # 10 plan's failure-mode section) and must never carry
            # provider-supplied text.
            detail = error_description or response.text[:500]
            if error_code:
                detail = f"{error_code}: {detail}"
            logger.warning(
                "Razorpay request to %s returned HTTP %s: %s", path, response.status_code, detail
            )
            raise RazorpayClientError(
                f"Razorpay request returned an error (HTTP {response.status_code})"
            )

        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise RazorpayClientError("Razorpay response was not valid JSON") from exc
        if not isinstance(body, dict):
            raise RazorpayClientError("Razorpay response was not a JSON object")
        return body
