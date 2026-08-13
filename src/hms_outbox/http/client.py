"""Async HTTP client for Outbox dispatch."""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from hms_outbox.config.settings import OutboxSettings
from hms_outbox.http.errors import (
    DispatchFailure,
    DispatchSuccess,
    classify_http_status,
    classify_transport_error,
    parse_success_response,
    sanitize_error_message,
)


class OutboxHttpClient:
    """Reusable async HTTP client with connection pooling."""

    def __init__(
        self,
        settings: OutboxSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_ms / 1000.0,
            read=settings.http_read_timeout_ms / 1000.0,
            write=settings.http_read_timeout_ms / 1000.0,
            pool=settings.http_connect_timeout_ms / 1000.0,
        )
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers=dict(settings.static_headers),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def post_event(
        self,
        *,
        url: str,
        event_id: uuid.UUID,
        event_type: str,
        organization_id: int,
        body: dict[str, Any],
        timeout_ms: int | None = None,
    ) -> DispatchSuccess | DispatchFailure:
        from hms_outbox.constants import HEADER_ORGANIZATION_ID

        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": str(event_id),
            "X-Outbox-Event-Id": str(event_id),
            "X-Outbox-Event-Type": event_type,
            HEADER_ORGANIZATION_ID: str(organization_id),
        }
        timeout: httpx.Timeout | float | None = None
        if timeout_ms is not None:
            seconds = timeout_ms / 1000.0
            timeout = httpx.Timeout(seconds)
        elif self._settings.http_total_timeout_ms:
            timeout = httpx.Timeout(self._settings.http_total_timeout_ms / 1000.0)

        started = time.perf_counter()
        try:
            response = await self._client.post(
                url, json=body, headers=headers, timeout=timeout
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            failure = classify_transport_error(exc)
            duration_ms = (time.perf_counter() - started) * 1000.0
            return DispatchFailure(
                error_code=failure.error_code,
                last_error=sanitize_error_message(failure.last_error),
                retryable=failure.retryable,
                duration_ms=duration_ms,
            )

        duration_ms = (time.perf_counter() - started) * 1000.0
        if 200 <= response.status_code < 300:
            body_json: Any = None
            if response.content:
                try:
                    body_json = response.json()
                except ValueError:
                    body_json = None
            parsed = parse_success_response(
                response.status_code, body_json, headers=response.headers
            )
            if isinstance(parsed, DispatchSuccess):
                return DispatchSuccess(
                    reply_reference_type=parsed.reply_reference_type,
                    reply_reference=parsed.reply_reference,
                    status_code=parsed.status_code,
                    duration_ms=duration_ms,
                )
            return DispatchFailure(
                error_code=parsed.error_code,
                last_error=parsed.last_error,
                retryable=parsed.retryable,
                status_code=parsed.status_code,
                duration_ms=duration_ms,
            )

        retryable, error_code = classify_http_status(response.status_code)
        detail = sanitize_error_message(response.text[:500] if response.text else "")
        return DispatchFailure(
            error_code=error_code,
            last_error=f"HTTP {response.status_code}: {detail}".strip(),
            retryable=retryable,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
