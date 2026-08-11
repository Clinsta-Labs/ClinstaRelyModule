"""HTTP error classification and response parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from hms_outbox.constants import (
    ERROR_CONNECTION_REFUSED,
    ERROR_HTTP_TIMEOUT,
    ERROR_INVALID_RESPONSE,
    ERROR_NETWORK,
)

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
NON_RETRYABLE_STATUS_CODES = frozenset({400, 401, 403, 404, 405, 409, 422})


@dataclass(frozen=True, slots=True)
class DispatchSuccess:
    reply_reference_type: str
    reply_reference: str
    status_code: int
    duration_ms: float


@dataclass(frozen=True, slots=True)
class DispatchFailure:
    error_code: str
    last_error: str
    retryable: bool
    status_code: int | None = None
    duration_ms: float = 0.0


def classify_http_status(status_code: int) -> tuple[bool, str]:
    """Return (retryable, error_code) for an HTTP status."""
    error_code = f"HTTP_{status_code}"
    if status_code in RETRYABLE_STATUS_CODES:
        return True, error_code
    if status_code in NON_RETRYABLE_STATUS_CODES:
        return False, error_code
    if 500 <= status_code <= 599:
        return True, error_code
    if 400 <= status_code <= 499:
        return False, error_code
    # Unexpected 1xx/3xx etc.
    return False, error_code


def classify_transport_error(exc: BaseException) -> DispatchFailure:
    if isinstance(exc, httpx.ConnectTimeout):
        return DispatchFailure(
            error_code=ERROR_HTTP_TIMEOUT,
            last_error="HTTP connect timeout",
            retryable=True,
        )
    if isinstance(exc, httpx.ReadTimeout):
        return DispatchFailure(
            error_code=ERROR_HTTP_TIMEOUT,
            last_error="HTTP read timeout",
            retryable=True,
        )
    if isinstance(exc, httpx.TimeoutException):
        return DispatchFailure(
            error_code=ERROR_HTTP_TIMEOUT,
            last_error="HTTP timeout",
            retryable=True,
        )
    if isinstance(exc, httpx.ConnectError):
        msg = str(exc) or "connection error"
        lowered = msg.lower()
        if "refused" in lowered:
            code = ERROR_CONNECTION_REFUSED
            text = "Connection refused"
        else:
            code = ERROR_NETWORK
            text = f"Connection error: {msg}"
        return DispatchFailure(error_code=code, last_error=text, retryable=True)
    if isinstance(exc, httpx.TransportError):
        return DispatchFailure(
            error_code=ERROR_NETWORK,
            last_error=f"Transport error: {exc}",
            retryable=True,
        )
    return DispatchFailure(
        error_code=ERROR_NETWORK,
        last_error=f"Unexpected transport error: {exc}",
        retryable=True,
    )


def parse_success_response(status_code: int, body: Any) -> DispatchSuccess | DispatchFailure:
    """Validate a 2xx response body.

    HTTP 204 and empty/invalid bodies are failures because reply references
    are mandatory.
    """
    if status_code == 204:
        return DispatchFailure(
            error_code=ERROR_INVALID_RESPONSE,
            last_error="HTTP 204 has no body; replyReference is required",
            retryable=False,
            status_code=status_code,
        )
    if not isinstance(body, dict):
        return DispatchFailure(
            error_code=ERROR_INVALID_RESPONSE,
            last_error="Response body must be a JSON object",
            retryable=False,
            status_code=status_code,
        )
    if body.get("success") is not True:
        return DispatchFailure(
            error_code=ERROR_INVALID_RESPONSE,
            last_error="Response success must be true",
            retryable=False,
            status_code=status_code,
        )
    reply_type = body.get("replyReferenceType")
    reply_ref = body.get("replyReference")
    if not isinstance(reply_type, str) or not reply_type.strip():
        return DispatchFailure(
            error_code=ERROR_INVALID_RESPONSE,
            last_error="Missing or invalid replyReferenceType",
            retryable=False,
            status_code=status_code,
        )
    if not isinstance(reply_ref, str) and not isinstance(reply_ref, (int, float)):
        return DispatchFailure(
            error_code=ERROR_INVALID_RESPONSE,
            last_error="Missing or invalid replyReference",
            retryable=False,
            status_code=status_code,
        )
    if reply_ref is None or (isinstance(reply_ref, str) and not reply_ref.strip()):
        return DispatchFailure(
            error_code=ERROR_INVALID_RESPONSE,
            last_error="Missing or invalid replyReference",
            retryable=False,
            status_code=status_code,
        )
    return DispatchSuccess(
        reply_reference_type=str(reply_type),
        reply_reference=str(reply_ref),
        status_code=status_code,
        duration_ms=0.0,
    )


def sanitize_error_message(message: str, *, max_length: int = 2000) -> str:
    """Strip likely secrets from diagnostic messages."""
    lowered_tokens = (
        "authorization",
        "api-key",
        "api_key",
        "password",
        "token",
        "cookie",
        "bearer ",
        "secret",
    )
    text = message
    for token in lowered_tokens:
        if token in text.lower():
            text = "[redacted: possible secret in error detail]"
            break
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text
