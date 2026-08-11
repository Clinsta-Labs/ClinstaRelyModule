"""Unit tests for HTTP error classification and response parsing."""

from __future__ import annotations

import httpx
import pytest

from hms_outbox.http.errors import (
    classify_http_status,
    classify_transport_error,
    parse_success_response,
    sanitize_error_message,
)


@pytest.mark.parametrize(
    "code,retryable",
    [
        (408, True),
        (425, True),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (405, False),
        (409, False),
        (422, False),
    ],
)
def test_classify_http_status(code: int, retryable: bool) -> None:
    is_retryable, error_code = classify_http_status(code)
    assert is_retryable is retryable
    assert error_code == f"HTTP_{code}"


def test_parse_valid_response() -> None:
    result = parse_success_response(
        200,
        {
            "success": True,
            "replyReferenceType": "JOURNAL_ENTRY",
            "replyReference": "JE-1",
        },
    )
    assert getattr(result, "reply_reference") == "JE-1"


def test_parse_http_201() -> None:
    result = parse_success_response(
        201,
        {"success": True, "replyReferenceType": "JE", "replyReference": "1"},
    )
    assert getattr(result, "status_code") == 201


def test_http_204_is_failure() -> None:
    result = parse_success_response(204, None)
    assert getattr(result, "retryable") is False
    assert getattr(result, "error_code") == "INVALID_RESPONSE"


def test_missing_reply_reference() -> None:
    result = parse_success_response(
        200, {"success": True, "replyReferenceType": "JE"}
    )
    assert getattr(result, "error_code") == "INVALID_RESPONSE"


def test_missing_reply_reference_type() -> None:
    result = parse_success_response(
        200, {"success": True, "replyReference": "JE-1"}
    )
    assert getattr(result, "error_code") == "INVALID_RESPONSE"


def test_malformed_body() -> None:
    result = parse_success_response(200, ["not", "object"])
    assert getattr(result, "error_code") == "INVALID_RESPONSE"


def test_transport_timeout() -> None:
    failure = classify_transport_error(httpx.ReadTimeout("timeout"))
    assert failure.retryable
    assert failure.error_code == "HTTP_TIMEOUT"


def test_connection_refused() -> None:
    failure = classify_transport_error(httpx.ConnectError("Connection refused"))
    assert failure.retryable
    assert failure.error_code == "CONNECTION_REFUSED"


def test_sanitize_secrets() -> None:
    assert "redacted" in sanitize_error_message("Authorization: Bearer abc").lower()
