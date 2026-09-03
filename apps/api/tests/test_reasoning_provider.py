"""Unit tests for HostedReasoningProvider (app/providers/reasoning.py).

Unlike test_reasoning.py (which exercises the domain/API layer through a
FakeReasoningProvider and never touches this class), these tests exercise
the real adapter directly -- the one class in the codebase that talks to
the hosted reasoning API. httpx.post is mocked with the standard library
only (no respx/responses dependency, no network access, no real API key --
none of this ever spends a real Anthropic API credit), specifically to
lock in one security-relevant behavior: an upstream error response must
never leak provider-supplied text into the exception message that
ultimately becomes InvestigationReasoning.failure_reason and is returned
by the API / shown in the UI. This was a real, manually-discovered issue (a
real HTTP 400 "insufficient credits" response included account-specific
billing text in its error body) rather than a hypothetical one, which is
what justifies a dedicated unit test here instead of only the existing
FakeReasoningProvider coverage in test_reasoning.py.

Phase 9 added: model/timeout are now constructor keyword arguments (see
HostedReasoningProvider.__init__) sourced from Settings.anthropic_model /
Settings.anthropic_timeout_seconds rather than hardcoded module constants
-- test_model_and_timeout_are_used_in_the_real_request and
test_default_model_and_timeout_when_not_specified below cover that the
values actually reach the outgoing request, and that the Phase 9 default
(claude-sonnet-5) applies when a caller does not override it. Every test
in this file that constructs HostedReasoningProvider without model=/
timeout_seconds= is exercising those same defaults, unchanged from before.
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


def test_successful_response_is_parsed_into_raw_hypotheses():
    """The happy path this file otherwise never exercises (test_reasoning.py
    covers it end-to-end, but always through FakeReasoningProvider, never
    through this class's own JSON parsing)."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [
            {
                "type": "text",
                "text": (
                    '{"hypotheses": [{"hypothesis_id": "h1", "rank": 1, '
                    '"title": "Retry storm", "explanation": "Clustered failures.", '
                    '"confidence": "medium", "supporting_evidence": ["e1"], '
                    '"contradicting_evidence": [], "uncertainty": "More data would help."}]}'
                ),
            }
        ]
    }

    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response):
        result = provider.generate_hypotheses(_context())

    assert len(result.hypotheses) == 1
    hypothesis = result.hypotheses[0]
    assert hypothesis.hypothesis_id == "h1"
    assert hypothesis.rank == 1
    assert hypothesis.confidence == "medium"
    assert hypothesis.supporting_evidence == ["e1"]
    assert hypothesis.contradicting_evidence == []


def test_malformed_reasoning_response_missing_required_field_raises():
    """Structurally valid JSON, but a hypothesis missing a required key
    (rank) -- distinct from test_malformed_json_body_raises_..., which
    covers JSON that does not even parse."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [
            {
                "type": "text",
                "text": '{"hypotheses": [{"hypothesis_id": "h1", "title": "Missing rank"}]}',
            }
        ]
    }

    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response):
        with pytest.raises(ReasoningProviderError):
            provider.generate_hypotheses(_context())


def test_default_model_and_timeout_when_not_specified():
    """Phase 9 default model is claude-sonnet-5; default timeout matches
    the value the provider hardcoded before Phase 9 (30 seconds) -- both
    apply when a caller constructs HostedReasoningProvider with only an
    api_key, exactly like app.routers.investigations.get_reasoning_provider
    did before Phase 9 added explicit Settings-sourced values."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": [{"type": "text", "text": '{"hypotheses": []}'}]}

    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response) as mock_post:
        provider.generate_hypotheses(_context())

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["model"] == "claude-sonnet-5"
    assert kwargs["timeout"] == 30.0


def test_model_and_timeout_are_used_in_the_real_request():
    """The configured model/timeout (as app.routers.investigations.
    get_reasoning_provider would pass them, sourced from
    Settings.anthropic_model / Settings.anthropic_timeout_seconds) actually
    reach the outgoing httpx.post call -- not just stored and ignored."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": [{"type": "text", "text": '{"hypotheses": []}'}]}

    provider = HostedReasoningProvider(
        api_key="test-key", model="claude-sonnet-5-custom-test", timeout_seconds=12.5
    )
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response) as mock_post:
        provider.generate_hypotheses(_context())

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.anthropic.com/v1/messages"
    assert kwargs["json"]["model"] == "claude-sonnet-5-custom-test"
    assert kwargs["timeout"] == 12.5
    assert kwargs["headers"]["x-api-key"] == "test-key"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"


def test_workspace_header_sent_when_workspace_id_configured():
    """Some Anthropic API keys are identity-linked to a Console workspace
    and require anthropic-workspace-id to authenticate at all -- sent only
    when HostedReasoningProvider is actually given one."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": [{"type": "text", "text": '{"hypotheses": []}'}]}

    provider = HostedReasoningProvider(api_key="test-key", workspace_id="wrkspc_test_123")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response) as mock_post:
        provider.generate_hypotheses(_context())

    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["anthropic-workspace-id"] == "wrkspc_test_123"
    # Every other header is still present and unchanged.
    assert kwargs["headers"]["x-api-key"] == "test-key"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"
    assert kwargs["headers"]["content-type"] == "application/json"


def test_workspace_header_absent_when_not_configured():
    """Default (no workspace_id passed, matching every pre-Phase-9-workspace
    construction of HostedReasoningProvider) -- the request must be
    byte-for-byte unchanged from before this header existed."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": [{"type": "text", "text": '{"hypotheses": []}'}]}

    provider = HostedReasoningProvider(api_key="test-key")
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response) as mock_post:
        provider.generate_hypotheses(_context())

    _, kwargs = mock_post.call_args
    assert "anthropic-workspace-id" not in kwargs["headers"]
    assert set(kwargs["headers"].keys()) == {"x-api-key", "anthropic-version", "content-type"}


def test_workspace_header_absent_when_explicitly_none():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": [{"type": "text", "text": '{"hypotheses": []}'}]}

    provider = HostedReasoningProvider(api_key="test-key", workspace_id=None)
    with patch("app.providers.reasoning.httpx.post", return_value=mock_response) as mock_post:
        provider.generate_hypotheses(_context())

    _, kwargs = mock_post.call_args
    assert "anthropic-workspace-id" not in kwargs["headers"]
