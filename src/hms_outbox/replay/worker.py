"""Replay worker: claim → dispatch → update."""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hms_outbox.constants import ERROR_ENDPOINT_NOT_CONFIGURED
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.http.errors import DispatchFailure, DispatchSuccess
from hms_outbox.models.event import OutboxEvent
from hms_outbox.replay.claimer import EventClaimer
from hms_outbox.replay.dispatcher import EventDispatcher
from hms_outbox.replay.metrics import ReplayMetrics
from hms_outbox.replay.retry_policy import RetryPolicy

logger = logging.getLogger("hms_outbox.worker")


class ReplayWorker:
    """Single worker that processes one event at a time."""

    def __init__(
        self,
        *,
        worker_id: str,
        session_factory: async_sessionmaker[AsyncSession],
        claimer: EventClaimer,
        dispatcher: EventDispatcher,
        repository: OutboxRepository,
        retry_policy: RetryPolicy,
        metrics: ReplayMetrics,
        poll_interval_ms: int,
    ) -> None:
        self.worker_id = worker_id
        self.session_factory = session_factory
        self.claimer = claimer
        self.dispatcher = dispatcher
        self.repository = repository
        self.retry_policy = retry_policy
        self.metrics = metrics
        self.poll_interval_ms = poll_interval_ms
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        self.metrics.incr("active_workers")
        try:
            while not self._stopped:
                processed = await self.run_once()
                if not processed:
                    await asyncio.sleep(self.poll_interval_ms / 1000.0)
        finally:
            self.metrics.incr("active_workers", -1)

    async def run_once(self) -> bool:
        """Claim and process at most one event. Returns True if work was done."""
        event = await self._claim()
        if event is None:
            return False
        started = time.perf_counter()
        try:
            result = await self.dispatcher.dispatch(event)
            await self._apply_result(event, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Unexpected worker error",
                extra={"event_id": str(event.event_id), "worker_id": self.worker_id},
            )
            await self._apply_result(
                event,
                DispatchFailure(
                    error_code="WORKER_ERROR",
                    last_error=str(exc),
                    retryable=True,
                ),
            )
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0
            self.metrics.add_duration("event_processing_duration_ms_total", duration_ms)
            self.metrics.incr("events_processed_total")
            logger.info(
                "Finished processing attempt",
                extra={
                    "event_id": str(event.event_id),
                    "organization_id": event.organization_id,
                    "event_type": event.event_type,
                    "event_group": event.event_group,
                    "group_sequence": event.group_sequence,
                    "reference_type": event.reference_type,
                    "reference": event.reference,
                    "worker_id": self.worker_id,
                    "retry_count": event.retry_count,
                    "duration_ms": duration_ms,
                },
            )
        return True

    async def _claim(self) -> OutboxEvent | None:
        async with self.session_factory() as session:
            async with session.begin():
                return await self.claimer.claim_async(session, self.worker_id)

    async def _apply_result(
        self, event: OutboxEvent, result: DispatchSuccess | DispatchFailure
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                if isinstance(result, DispatchSuccess):
                    ok = await self.repository.mark_synced_async(
                        session,
                        event_id=event.event_id,
                        worker_id=self.worker_id,
                        reply_reference_type=result.reply_reference_type,
                        reply_reference=result.reply_reference,
                    )
                    if ok:
                        self.metrics.incr("events_synced_total")
                    return

                # Permanent configuration / non-retryable errors → RETRY_EXHAUSTED
                if (
                    result.error_code == ERROR_ENDPOINT_NOT_CONFIGURED
                    or not result.retryable
                ):
                    ok = await self.repository.mark_configuration_exhausted_async(
                        session,
                        event_id=event.event_id,
                        worker_id=self.worker_id,
                        error_code=result.error_code,
                        last_error=result.last_error,
                    )
                    if ok:
                        self.metrics.incr("events_failed_total")
                    return

                decision = self.retry_policy.on_failure(event.retry_count)
                ok = await self.repository.mark_failed_async(
                    session,
                    event_id=event.event_id,
                    worker_id=self.worker_id,
                    retry_count=decision.new_retry_count,
                    error_code=result.error_code,
                    last_error=result.last_error,
                    exhausted=decision.exhausted,
                )
                if ok:
                    self.metrics.incr("events_failed_total")
                    if not decision.exhausted:
                        self.metrics.incr("retry_total")
