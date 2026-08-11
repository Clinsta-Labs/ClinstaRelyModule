"""Fix recovery exhaustion helper — clean implementation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from hms_outbox.config.settings import OutboxSettings
from hms_outbox.constants import ERROR_PROCESSING_TIMEOUT, EventStatus
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.replay.metrics import ReplayMetrics
from hms_outbox.replay.retry_policy import RetryPolicy

logger = logging.getLogger("hms_outbox.recovery")


class ProcessingRecovery:
    """Recovers events stuck in PROCESSING beyond the configured timeout."""

    def __init__(
        self,
        *,
        repository: OutboxRepository,
        settings: OutboxSettings,
        retry_policy: RetryPolicy,
        metrics: ReplayMetrics | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.retry_policy = retry_policy
        self.metrics = metrics or ReplayMetrics()

    def recover(self, session: Session) -> int:
        recovered = self.repository.recover_stale_processing(
            session, timeout_ms=self.settings.processing_timeout_ms
        )
        if recovered:
            self.metrics.incr("processing_timeout_total", len(recovered))
            self._exhaust_if_needed(session)
            logger.warning(
                "Recovered stale PROCESSING events",
                extra={"count": len(recovered), "event_ids": [str(i) for i in recovered]},
            )
        return len(recovered)

    async def recover_async(self, session: AsyncSession) -> int:
        recovered = await self.repository.recover_stale_processing_async(
            session, timeout_ms=self.settings.processing_timeout_ms
        )
        if recovered:
            self.metrics.incr("processing_timeout_total", len(recovered))
            await self._exhaust_if_needed_async(session)
            logger.warning(
                "Recovered stale PROCESSING events",
                extra={"count": len(recovered), "event_ids": [str(i) for i in recovered]},
            )
        return len(recovered)

    def _exhaust_if_needed(self, session: Session) -> None:
        now = datetime.now(timezone.utc)
        max_retry = self.settings.max_retry_count
        stmt = update(self.repository.model).where(
            self.repository.model.status == EventStatus.FAILED.value,
            self.repository.model.error_code == ERROR_PROCESSING_TIMEOUT,
        )
        if max_retry == 0:
            pass
        else:
            stmt = stmt.where(self.repository.model.retry_count >= max_retry)
        session.execute(
            stmt.values(status=EventStatus.RETRY_EXHAUSTED.value, updated_at=now)
        )

    async def _exhaust_if_needed_async(self, session: AsyncSession) -> None:
        now = datetime.now(timezone.utc)
        max_retry = self.settings.max_retry_count
        stmt = update(self.repository.model).where(
            self.repository.model.status == EventStatus.FAILED.value,
            self.repository.model.error_code == ERROR_PROCESSING_TIMEOUT,
        )
        if max_retry > 0:
            stmt = stmt.where(self.repository.model.retry_count >= max_retry)
        await session.execute(
            stmt.values(status=EventStatus.RETRY_EXHAUSTED.value, updated_at=now)
        )


class RecoveryLoop:
    """Periodically runs processing recovery."""

    def __init__(
        self,
        *,
        recovery: ProcessingRecovery,
        session_factory: async_sessionmaker[AsyncSession],
        interval_ms: int = 5000,
    ) -> None:
        self.recovery = recovery
        self.session_factory = session_factory
        self.interval_ms = interval_ms
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        import asyncio

        while not self._stopped:
            try:
                async with self.session_factory() as session:
                    async with session.begin():
                        await self.recovery.recover_async(session)
            except Exception:  # noqa: BLE001
                logger.exception("Recovery loop iteration failed")
            await asyncio.sleep(self.interval_ms / 1000.0)
