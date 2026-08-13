"""HTTP dispatch orchestration for a claimed event."""

from __future__ import annotations

import logging
from typing import Any

from hms_outbox.config.endpoint_registry import EndpointRegistry
from hms_outbox.constants import ERROR_ENDPOINT_NOT_CONFIGURED
from hms_outbox.http.client import OutboxHttpClient
from hms_outbox.http.errors import DispatchFailure, DispatchSuccess
from hms_outbox.models.event import OutboxEvent
from hms_outbox.replay.metrics import ReplayMetrics

logger = logging.getLogger("hms_outbox.dispatcher")


class EventDispatcher:
    """Dispatches a claimed event to its configured HTTP endpoint."""

    def __init__(
        self,
        *,
        registry: EndpointRegistry,
        http_client: OutboxHttpClient,
        metrics: ReplayMetrics | None = None,
        log_payload: bool = False,
    ) -> None:
        self.registry = registry
        self.http_client = http_client
        self.metrics = metrics or ReplayMetrics()
        self.log_payload = log_payload

    async def dispatch(self, event: OutboxEvent) -> DispatchSuccess | DispatchFailure:
        endpoint = self.registry.get(event.event_type)
        if endpoint is None:
            return DispatchFailure(
                error_code=ERROR_ENDPOINT_NOT_CONFIGURED,
                last_error=f"No endpoint configured for event type {event.event_type}",
                retryable=False,
            )

        body = event.dispatch_body()
        log_extra: dict[str, Any] = {
            "event_id": str(event.event_id),
            "organization_id": event.organization_id,
            "event_type": event.event_type,
            "event_group": event.event_group,
            "group_sequence": event.group_sequence,
            "reference_type": event.reference_type,
            "reference": event.reference,
            "worker_id": event.worker_id,
            "retry_count": event.retry_count,
            "status": event.status,
            "endpoint": endpoint.url,
        }
        if self.log_payload:
            log_extra["payload"] = event.payload
            logger.warning(
                "Dispatching event with payload logging enabled (unsafe for production)",
                extra=log_extra,
            )
        else:
            logger.info("Dispatching outbox event", extra=log_extra)

        result = await self.http_client.post_event(
            url=endpoint.url,
            event_id=event.event_id,
            event_type=event.event_type,
            organization_id=event.organization_id,
            body=body,
            timeout_ms=endpoint.timeout_ms,
        )
        self.metrics.add_duration("http_request_duration_ms_total", result.duration_ms)
        if isinstance(result, DispatchSuccess):
            self.metrics.incr("http_2xx_total")
        elif result.status_code is not None:
            if 400 <= result.status_code < 500:
                self.metrics.incr("http_4xx_total")
            elif 500 <= result.status_code < 600:
                self.metrics.incr("http_5xx_total")
            if result.error_code in {"HTTP_TIMEOUT"} or "timeout" in result.last_error.lower():
                self.metrics.incr("timeout_total")
        elif "timeout" in result.error_code.lower():
            self.metrics.incr("timeout_total")
        return result
