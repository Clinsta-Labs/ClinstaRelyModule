"""Admin / operational service APIs (framework-neutral)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from hms_outbox.db.repository import OutboxRepository
from hms_outbox.statistics.service import StatisticsService


class AdminService:
    """Failed-event query and manual retry operations."""

    def __init__(
        self,
        repository: OutboxRepository,
        *,
        statistics: StatisticsService | None = None,
        sync_factory: sessionmaker[Session] | None = None,
        async_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.repository = repository
        self.statistics = statistics
        self.sync_factory = sync_factory
        self.async_factory = async_factory

    def get_failed_events(
        self,
        session: Session,
        *,
        limit: int = 50,
        offset: int = 0,
        organization_id: int | None = None,
        event_type: str | None = None,
        event_group: str | None = None,
        reference_type: str | None = None,
        reference: str | None = None,
        retry_count: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        rows, total = self.repository.list_failed(
            session,
            limit=limit,
            offset=offset,
            organization_id=organization_id,
            event_type=event_type,
            event_group=event_group,
            reference_type=reference_type,
            reference=reference,
            retry_count=retry_count,
            created_from=created_from,
            created_to=created_to,
            status=status,
        )
        return {
            "items": [e.to_dict() for e in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def get_failed_events_async(
        self,
        session: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        rows, total = await self.repository.list_failed_async(
            session, limit=limit, offset=offset, **filters
        )
        return {
            "items": [e.to_dict() for e in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_events(
        self,
        session: Session,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        rows, total = self.repository.list_events(
            session, limit=limit, offset=offset, **filters
        )
        return {
            "items": [e.to_dict() for e in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def get_events_async(
        self,
        session: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        rows, total = await self.repository.list_events_async(
            session, limit=limit, offset=offset, **filters
        )
        return {
            "items": [e.to_dict() for e in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_event(self, session: Session, event_id: uuid.UUID) -> dict[str, Any]:
        return self.repository.get_required(session, event_id).to_dict()

    async def get_event_async(
        self, session: AsyncSession, event_id: uuid.UUID
    ) -> dict[str, Any]:
        event = await self.repository.get_required_async(session, event_id)
        return event.to_dict()

    def retry_event(self, session: Session, event_id: uuid.UUID) -> dict[str, Any]:
        return self.repository.retry_event(session, event_id).to_dict()

    async def retry_event_async(
        self, session: AsyncSession, event_id: uuid.UUID
    ) -> dict[str, Any]:
        event = await self.repository.retry_event_async(session, event_id)
        return event.to_dict()

    def retry_group(
        self, session: Session, organization_id: int, event_group: str
    ) -> dict[str, Any]:
        event = self.repository.retry_group(session, organization_id, event_group)
        if event is None:
            return {"retried": False, "event": None}
        return {"retried": True, "event": event.to_dict()}

    async def retry_group_async(
        self, session: AsyncSession, organization_id: int, event_group: str
    ) -> dict[str, Any]:
        event = await self.repository.retry_group_async(
            session, organization_id, event_group
        )
        if event is None:
            return {"retried": False, "event": None}
        return {"retried": True, "event": event.to_dict()}
