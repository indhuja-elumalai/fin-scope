"""Unit tests for HostedReasoningProvider (app/providers/reasoning.py).

Unlike test_reasoning.py (which exercises the domain/API layer through a
FakeReasoningProvider and never touches this class), these tests exercise
the real adapter directly -- the one class in the codebase that talks to
the hosted reasoning API. httpx.post is mocked with the standard library
only (no respx/responses dependency), specifically to lock in one
security-relevant behavior: an upstream error response must never leak
provider-supplied text into the exception message that ultimately becomes
InvestigationReasoning.failure_reason and is returned by the API / shown in
the UI. This was a real, manually-discovered issue (a real HTTP 400
"insufficient credits" response included account-specific billing text in
its error body) rather than a hypothetical one, which is what justifies a
dedicated unit test here instead of only the existing FakeReasoningProvider
coverage in test_reasoning.py.
"""
from unittest.mock import Mock, patch

import httpx
import pytest

from app.providers.reasoning import (
    EvidenceRef,
    HostedReasoningProvider,
    ReasoningContext,
    ReasoningProviderError,
)


def _context() -> ReasoningContext:
    return ReasoningContext(
        investigation_id="11111111-1111-1111-1111-111111111111",
        incident_detected=True,
        evidence_event_count=1,
        event_type_counts={"payment_failed": 1},
        dominant_signal_event_type="payment_failed",
        dominant_signal_share="1.0000",
        impact_breakdown=[],
        impact_amount_unknown_count=0,
        evidence=[
            EvidenceRef(
                event_id="22222222-2222-2222-2222-222222222222",
                event_type="payment_failed",
                source="manual",
                amount="10.00",
                currency="INR",
                occurred_at="2026-01-01T00:00:00+00:00",
            )
        ],
    )


def test_non_200_response_does_not_leak_upstream_error_detail():
    """Reproduces the real insufficient-credits response manually observed
    against the hosted provider: a JSON error body with account-specific
    text must never reach the exception message."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error": {
            "type": "insufficient_quota",
            "message": "Your account (acct_secret_123) has insufficient credits.",
        }
    }
    mock_response.text = (
        '{"error": {"message": "Your account (acct_secret_123) has insufficient credits."}}'
    )

    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response):
        with pytest.raises(ReasoningProviderError) as exc_info:
            provider.generate_hypotheses(_context())

    message = str(exc_info.value)
    assert "400" in message
    assert "acct_secret_123" not in message
    assert "insufficient" not in message.lower()
    assert "credits" not in message.lower()


def test_non_200_response_with_non_json_body_does_not_leak_raw_text():
    mock_response = Mock()
    mock_response.status_code = 529
    mock_response.json.side_effect = ValueError("not json")
    mock_response.text = "upstream is overloaded, retry later, ref=xyz"

    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response):
        with pytest.raises(ReasoningProviderError) as exc_info:
            provider.generate_hypotheses(_context())

    message = str(exc_info.value)
    assert "529" in message
    assert "xyz" not in message
    assert "overloaded" not in message


def test_non_200_response_still_raises_reasoning_provider_error():
    """The sanitization must not change the "unavailable" status contract --
    every non-200 response must still raise ReasoningProviderError, which
    app.domain.reasoning maps to status="unavailable"."""
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.json.side_effect = ValueError("not json")
    mock_response.text = ""

    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response):
        with pytest.raises(ReasoningProviderError):
            provider.generate_hypotheses(_context())


def test_timeout_raises_reasoning_provider_error_with_generic_message():
    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", side_effect=httpx.TimeoutException("x")):
        with pytest.raises(ReasoningProviderError) as exc_info:
            provider.generate_hypotheses(_context())
    assert "timed out" in str(exc_info.value)


def test_malformed_json_body_raises_reasoning_provider_error():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": [{"type": "text", "text": "not valid json{"}]}

    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response):
        with pytest.raises(ReasoningProviderError):
            provider.generate_hypotheses(_context())
