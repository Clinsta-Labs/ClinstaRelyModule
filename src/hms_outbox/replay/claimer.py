"""Atomic event claiming."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from hms_outbox.config.settings import OutboxSettings
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.models.event import OutboxEvent


class EventClaimer:
    """Claims the next FIFO-eligible event for a worker."""

    def __init__(self, repository: OutboxRepository, settings: OutboxSettings) -> None:
        self.repository = repository
        self.settings = settings

    def claim(self, session: Session, worker_id: str) -> OutboxEvent | None:
        return self.repository.claim_next(
            session,
            worker_id=worker_id,
            initial_retry_delay_ms=self.settings.initial_retry_delay_ms,
            retry_backoff_multiplier=self.settings.retry_backoff_multiplier,
            max_retry_delay_ms=self.settings.max_retry_delay_ms,
        )

    async def claim_async(self, session: AsyncSession, worker_id: str) -> OutboxEvent | None:
        return await self.repository.claim_next_async(
            session,
            worker_id=worker_id,
            initial_retry_delay_ms=self.settings.initial_retry_delay_ms,
            retry_backoff_multiplier=self.settings.retry_backoff_multiplier,
            max_retry_delay_ms=self.settings.max_retry_delay_ms,
        )
