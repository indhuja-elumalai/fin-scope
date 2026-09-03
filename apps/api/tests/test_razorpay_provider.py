"""Unit tests for RazorpayClient (app/providers/razorpay.py) -- Phase 10,
Milestone 1.

Mirrors test_reasoning_provider.py's discipline exactly: httpx.post is
mocked with the standard library only, no network access, no real
Razorpay credentials, and no live call is made anywhere in this file --
none of this ever touches a real Razorpay endpoint, TEST-mode or
otherwise. That is Milestone 4's job, explicitly gated and separately
approved.

Two things this file exists to lock in, distinctly:
1. The TEST-mode construction guard (safety rule 1) -- a client can never
   be constructed for a live-looking key, or without explicit
   test_mode_confirmed=True, regardless of what the caller intends.
2. The request/response mechanics (Basic Auth, Orders API contract,
   idempotent receipt pass-through, error sanitization) once a client
   *has* been legitimately constructed -- the same shape of coverage
   test_reasoning_provider.py gives HostedReasoningProvider.
"""
from unittest.mock import Mock, patch

import httpx
import pytest

from app.providers.razorpay import (
    RazorpayClient,
    RazorpayClientError,
    RazorpayConfigurationError,
)

# --- Construction guard (safety rule 1: TEST MODE ONLY) --------------------


def test_refuses_to_construct_with_live_key_even_if_confirmed():
    with pytest.raises(RazorpayConfigurationError):
        RazorpayClient("rzp_live_abc123", "secret", test_mode_confirmed=True)


def test_refuses_to_construct_with_unrecognized_key_prefix():
    with pytest.raises(RazorpayConfigurationError):
        RazorpayClient("not_a_razorpay_key", "secret", test_mode_confirmed=True)


def test_refuses_to_construct_with_test_key_but_not_confirmed():
    """A rzp_test_ key alone is not sufficient -- test_mode_confirmed must
    also be explicitly True. Neither guard alone is trusted."""
    with pytest.raises(RazorpayConfigurationError):
        RazorpayClient("rzp_test_abc123", "secret", test_mode_confirmed=False)


def test_constructs_successfully_with_test_key_and_explicit_confirmation():
    client = RazorpayClient("rzp_test_abc123", "secret", test_mode_confirmed=True)
    assert isinstance(client, RazorpayClient)


def test_construction_never_makes_a_network_call():
    """Constructing a client -- valid or invalid -- must never itself issue
    an HTTP request. Patching httpx.post to raise proves nothing in this
    constructor path reaches it."""
    with patch("app.providers.razorpay.httpx.post", side_effect=AssertionError("must not call")):
        RazorpayClient("rzp_test_abc123", "secret", test_mode_confirmed=True)
        with pytest.raises(RazorpayConfigurationError):
            RazorpayClient("rzp_live_abc123", "secret", test_mode_confirmed=True)


# --- create_order request mechanics ----------------------------------------


def _client() -> RazorpayClient:
    return RazorpayClient("rzp_test_abc123", "secret_value", test_mode_confirmed=True)


def test_create_order_sends_basic_auth_and_expected_body():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "order_TEST123",
        "status": "created",
        "amount": 5000,
        "currency": "INR",
        "receipt": "decision_abc",
        "amount_paid": 0,
        "amount_due": 5000,
    }

    with patch("app.providers.razorpay.httpx.post", return_value=mock_response) as mock_post:
        order = _client().create_order(amount=5000, currency="INR", receipt="decision_abc")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.razorpay.com/v1/orders"
    assert kwargs["auth"] == ("rzp_test_abc123", "secret_value")
    assert kwargs["json"] == {"amount": 5000, "currency": "INR", "receipt": "decision_abc"}
    assert kwargs["timeout"] == 30.0

    assert order.id == "order_TEST123"
    assert order.status == "created"
    assert order.amount == 5000
    assert order.amount_due == 5000
    assert order.amount_paid == 0


def test_create_order_includes_notes_only_when_provided():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "order_TEST123",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "r1",
        "amount_paid": 0,
        "amount_due": 100,
    }

    with patch("app.providers.razorpay.httpx.post", return_value=mock_response) as mock_post:
        _client().create_order(
            amount=100, currency="INR", receipt="r1", notes={"investigation_id": "inv_1"}
        )
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["notes"] == {"investigation_id": "inv_1"}

    with patch("app.providers.razorpay.httpx.post", return_value=mock_response) as mock_post:
        _client().create_order(amount=100, currency="INR", receipt="r1")
    _, kwargs = mock_post.call_args
    assert "notes" not in kwargs["json"]


def test_create_order_custom_timeout_is_used():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "order_TEST123",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "r1",
        "amount_paid": 0,
        "amount_due": 100,
    }
    client = RazorpayClient(
        "rzp_test_abc123", "secret", test_mode_confirmed=True, timeout_seconds=7.5
    )
    with patch("app.providers.razorpay.httpx.post", return_value=mock_response) as mock_post:
        client.create_order(amount=100, currency="INR", receipt="r1")
    _, kwargs = mock_post.call_args
    assert kwargs["timeout"] == 7.5


def test_create_order_response_missing_id_raises():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "created"}

    with patch("app.providers.razorpay.httpx.post", return_value=mock_response):
        with pytest.raises(RazorpayClientError):
            _client().create_order(amount=100, currency="INR", receipt="r1")


def test_create_order_raw_field_preserves_full_response():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "order_TEST123",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "r1",
        "amount_paid": 0,
        "amount_due": 100,
        "entity": "order",
        "attempts": 0,
    }
    with patch("app.providers.razorpay.httpx.post", return_value=mock_response):
        order = _client().create_order(amount=100, currency="INR", receipt="r1")
    assert order.raw["entity"] == "order"
    assert order.raw["attempts"] == 0


# --- Error handling / sanitization ------------------------------------------


def test_non_2xx_response_does_not_leak_upstream_error_detail():
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error": {
            "code": "BAD_REQUEST_ERROR",
            "description": "The api key/secret provided is invalid (acct_secret_123)",
        }
    }
    mock_response.text = (
        '{"error": {"description": "The api key/secret provided is invalid '
        '(acct_secret_123)"}}'
    )

    with patch("app.providers.razorpay.httpx.post", return_value=mock_response):
        with pytest.raises(RazorpayClientError) as exc_info:
            _client().create_order(amount=100, currency="INR", receipt="r1")

    message = str(exc_info.value)
    assert "400" in message
    assert "acct_secret_123" not in message
    assert "invalid" not in message.lower()


def test_non_2xx_response_with_non_json_body_does_not_leak_raw_text():
    mock_response = Mock()
    mock_response.status_code = 502
    mock_response.json.side_effect = ValueError("not json")
    mock_response.text = "upstream gateway error, ref=xyz"

    with patch("app.providers.razorpay.httpx.post", return_value=mock_response):
        with pytest.raises(RazorpayClientError) as exc_info:
            _client().create_order(amount=100, currency="INR", receipt="r1")

    message = str(exc_info.value)
    assert "502" in message
    assert "xyz" not in message


def test_timeout_raises_razorpay_client_error():
    with patch(
        "app.providers.razorpay.httpx.post", side_effect=httpx.TimeoutException("x")
    ):
        with pytest.raises(RazorpayClientError) as exc_info:
            _client().create_order(amount=100, currency="INR", receipt="r1")
    assert "timed out" in str(exc_info.value)


def test_transport_error_raises_razorpay_client_error():
    with patch(
        "app.providers.razorpay.httpx.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with pytest.raises(RazorpayClientError):
            _client().create_order(amount=100, currency="INR", receipt="r1")


def test_malformed_json_body_raises_razorpay_client_error():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("not json")

    with patch("app.providers.razorpay.httpx.post", return_value=mock_response):
        with pytest.raises(RazorpayClientError):
            _client().create_order(amount=100, currency="INR", receipt="r1")


def test_non_dict_json_body_raises_razorpay_client_error():
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = ["not", "a", "dict"]

    with patch("app.providers.razorpay.httpx.post", return_value=mock_response):
        with pytest.raises(RazorpayClientError):
            _client().create_order(amount=100, currency="INR", receipt="r1")
