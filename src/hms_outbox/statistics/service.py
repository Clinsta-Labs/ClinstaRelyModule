"""Statistics service (framework-neutral)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from hms_outbox.db.repository import OutboxRepository
from hms_outbox.replay.metrics import ReplayMetrics


class StatisticsService:
    """Aggregates DB status counts with optional live worker metrics."""

    def __init__(
        self,
        repository: OutboxRepository,
        *,
        metrics: ReplayMetrics | None = None,
        configured_workers: int = 0,
    ) -> None:
        self.repository = repository
        self.metrics = metrics
        self.configured_workers = configured_workers

    def get_statistics(self, session: Session) -> dict[str, Any]:
        stats = self.repository.statistics(session)
        active = self.metrics.active_workers if self.metrics else 0
        stats["workers"] = {
            "configured": self.configured_workers,
            "active": active,
        }
        if self.metrics:
            stats["metrics"] = self.metrics.snapshot()
        return stats

    async def get_statistics_async(self, session: AsyncSession) -> dict[str, Any]:
        stats = await self.repository.statistics_async(session)
        active = self.metrics.active_workers if self.metrics else 0
        stats["workers"] = {
            "configured": self.configured_workers,
            "active": active,
        }
        if self.metrics:
            stats["metrics"] = self.metrics.snapshot()
        return stats


class StatisticsServiceFacade:
    """Convenience facade that opens its own sessions."""

    def __init__(
        self,
        repository: OutboxRepository,
        *,
        sync_factory: sessionmaker[Session] | None = None,
        async_factory: async_sessionmaker[AsyncSession] | None = None,
        metrics: ReplayMetrics | None = None,
        configured_workers: int = 0,
    ) -> None:
        self._inner = StatisticsService(
            repository, metrics=metrics, configured_workers=configured_workers
        )
        self.sync_factory = sync_factory
        self.async_factory = async_factory

    def get_statistics(self) -> dict[str, Any]:
        if self.sync_factory is None:
            raise RuntimeError("sync session factory not configured")
        with self.sync_factory() as session:
            return self._inner.get_statistics(session)

    async def get_statistics_async(self) -> dict[str, Any]:
        if self.async_factory is None:
            raise RuntimeError("async session factory not configured")
        async with self.async_factory() as session:
            return await self._inner.get_statistics_async(session)
