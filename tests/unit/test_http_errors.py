"""Unit tests for HTTP error classification and response parsing."""

from __future__ import annotations

import httpx
import pytest

from hms_outbox.constants import HEADER_REPLY_REFERENCE, HEADER_REPLY_REFERENCE_TYPE
from hms_outbox.http.errors import (
    DispatchFailure,
    DispatchSuccess,
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


def test_parse_valid_json_body_fallback() -> None:
    result = parse_success_response(
        200,
        {
            "success": True,
            "replyReferenceType": "JOURNAL_ENTRY",
            "replyReference": "JE-1",
        },
    )
    assert isinstance(result, DispatchSuccess)
    assert result.reply_reference == "JE-1"
    assert result.reply_reference_type == "JOURNAL_ENTRY"


def test_parse_http_201_body_fallback() -> None:
    result = parse_success_response(
        201,
        {"success": True, "replyReferenceType": "JE", "replyReference": "1"},
    )
    assert isinstance(result, DispatchSuccess)
    assert result.status_code == 201


def test_headers_are_primary_over_body() -> None:
    result = parse_success_response(
        200,
        {
            "success": True,
            "replyReferenceType": "FROM_BODY",
            "replyReference": "BODY-1",
        },
        headers={
            HEADER_REPLY_REFERENCE_TYPE: "JOURNAL_ENTRY",
            HEADER_REPLY_REFERENCE: "JE-HEADER",
        },
    )
    assert isinstance(result, DispatchSuccess)
    assert result.reply_reference_type == "JOURNAL_ENTRY"
    assert result.reply_reference == "JE-HEADER"


def test_headers_allow_arbitrary_json_body() -> None:
    result = parse_success_response(
        201,
        {"journalId": "JE-9", "ok": True},
        headers={
            HEADER_REPLY_REFERENCE_TYPE: "JOURNAL_ENTRY",
            HEADER_REPLY_REFERENCE: "JE-9",
        },
    )
    assert isinstance(result, DispatchSuccess)
    assert result.reply_reference == "JE-9"


def test_headers_succeed_with_empty_body() -> None:
    result = parse_success_response(
        204,
        None,
        headers={
            HEADER_REPLY_REFERENCE_TYPE: "JOURNAL_ENTRY",
            HEADER_REPLY_REFERENCE: "JE-204",
        },
    )
    assert isinstance(result, DispatchSuccess)
    assert result.reply_reference == "JE-204"


def test_header_names_are_case_insensitive() -> None:
    result = parse_success_response(
        200,
        None,
        headers={
            "x-outbox-reply-reference-type": "JOURNAL_ENTRY",
            "x-outbox-reply-reference": "JE-1",
        },
    )
    assert isinstance(result, DispatchSuccess)
    assert result.reply_reference_type == "JOURNAL_ENTRY"


def test_numeric_reply_reference_from_body() -> None:
    result = parse_success_response(
        200,
        {"success": True, "replyReferenceType": "JE", "replyReference": 10001},
    )
    assert isinstance(result, DispatchSuccess)
    assert result.reply_reference == "10001"


def test_http_204_without_headers_is_failure() -> None:
    result = parse_success_response(204, None)
    assert isinstance(result, DispatchFailure)
    assert result.retryable is False
    assert result.error_code == "INVALID_RESPONSE"


def test_missing_reply_reference_in_body() -> None:
    result = parse_success_response(200, {"success": True, "replyReferenceType": "JE"})
    assert isinstance(result, DispatchFailure)
    assert result.error_code == "INVALID_RESPONSE"
    assert result.retryable is False


def test_missing_reply_reference_type_in_body() -> None:
    result = parse_success_response(200, {"success": True, "replyReference": "JE-1"})
    assert isinstance(result, DispatchFailure)
    assert result.error_code == "INVALID_RESPONSE"


def test_partial_headers_are_not_mixed_with_body() -> None:
    result = parse_success_response(
        200,
        {
            "success": True,
            "replyReferenceType": "JOURNAL_ENTRY",
            "replyReference": "JE-1",
        },
        headers={HEADER_REPLY_REFERENCE_TYPE: "JOURNAL_ENTRY"},
    )
    assert isinstance(result, DispatchFailure)
    assert result.retryable is False
    assert "X-Outbox-Reply-Reference" in result.last_error


def test_blank_headers_are_invalid() -> None:
    result = parse_success_response(
        200,
        None,
        headers={
            HEADER_REPLY_REFERENCE_TYPE: "  ",
            HEADER_REPLY_REFERENCE: "JE-1",
        },
    )
    assert isinstance(result, DispatchFailure)


def test_malformed_body_without_headers_is_failure() -> None:
    result = parse_success_response(200, ["not", "object"])
    assert isinstance(result, DispatchFailure)
    assert result.error_code == "INVALID_RESPONSE"


def test_success_false_body_without_headers_is_failure() -> None:
    result = parse_success_response(
        200,
        {
            "success": False,
            "replyReferenceType": "JE",
            "replyReference": "1",
        },
    )
    assert isinstance(result, DispatchFailure)


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
