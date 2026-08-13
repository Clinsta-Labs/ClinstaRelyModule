"""HTTP error classification and response parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from hms_outbox.constants import (
    ERROR_CONNECTION_REFUSED,
    ERROR_HTTP_TIMEOUT,
    ERROR_INVALID_RESPONSE,
    ERROR_NETWORK,
    HEADER_REPLY_REFERENCE,
    HEADER_REPLY_REFERENCE_TYPE,
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


def _normalize_reply_value(value: Any) -> str | None:
    """Return a non-empty reply identity string, or None if unusable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(value).strip()
        return text or None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _header_get(headers: Mapping[str, str] | None, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    # httpx.Headers is case-insensitive; plain dicts are not.
    value = getter(name)
    if value is None:
        for key, candidate in headers.items():
            if str(key).lower() == name.lower():
                value = candidate
                break
    return _normalize_reply_value(value)


def extract_reply_from_headers(
    headers: Mapping[str, str] | None,
) -> tuple[str | None, str | None]:
    """Read reply identity from X-Outbox-Reply-Reference-* headers."""
    return (
        _header_get(headers, HEADER_REPLY_REFERENCE_TYPE),
        _header_get(headers, HEADER_REPLY_REFERENCE),
    )


def extract_reply_from_body(body: Any) -> tuple[str | None, str | None]:
    """Read spec JSON fallback: success=true plus replyReference* fields."""
    if not isinstance(body, dict) or body.get("success") is not True:
        return None, None
    return (
        _normalize_reply_value(body.get("replyReferenceType")),
        _normalize_reply_value(body.get("replyReference")),
    )


def parse_success_response(
    status_code: int,
    body: Any,
    headers: Mapping[str, str] | None = None,
) -> DispatchSuccess | DispatchFailure:
    """Resolve reply identity from a 2xx response.

    Primary: ``X-Outbox-Reply-Reference-Type`` and ``X-Outbox-Reply-Reference``.
    Fallback: spec JSON ``{success, replyReferenceType, replyReference}``.

    Both values are mandatory. Missing identity is a non-retryable failure.
    Headers take precedence; a partial header pair is not mixed with the body.
    """
    header_type, header_ref = extract_reply_from_headers(headers)
    if header_type and header_ref:
        return DispatchSuccess(
            reply_reference_type=header_type,
            reply_reference=header_ref,
            status_code=status_code,
            duration_ms=0.0,
        )
    if header_type or header_ref:
        missing = HEADER_REPLY_REFERENCE if header_type else HEADER_REPLY_REFERENCE_TYPE
        return DispatchFailure(
            error_code=ERROR_INVALID_RESPONSE,
            last_error=f"Incomplete reply headers; missing {missing}",
            retryable=False,
            status_code=status_code,
        )

    body_type, body_ref = extract_reply_from_body(body)
    if body_type and body_ref:
        return DispatchSuccess(
            reply_reference_type=body_type,
            reply_reference=body_ref,
            status_code=status_code,
            duration_ms=0.0,
        )

    return DispatchFailure(
        error_code=ERROR_INVALID_RESPONSE,
        last_error=(
            "Missing reply identity; require headers "
            f"{HEADER_REPLY_REFERENCE_TYPE} and {HEADER_REPLY_REFERENCE} "
            "or JSON success/replyReferenceType/replyReference"
        ),
        retryable=False,
        status_code=status_code,
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
