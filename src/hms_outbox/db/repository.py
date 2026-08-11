"""Outbox repository: claim, update, query, recovery, admin operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import Select, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from hms_outbox.constants import (
    ERROR_PROCESSING_TIMEOUT,
    EventStatus,
)
from hms_outbox.exceptions import EventNotFoundError, InvalidEventStateError
from hms_outbox.models.event import OutboxEvent


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OutboxRepository:
    """Database operations for Outbox events.

    Claim SQL enforces Group-FIFO eligibility in the database using
    ``FOR UPDATE SKIP LOCKED`` so multiple workers/processes coordinate safely.
    """

    def __init__(self, model: type[OutboxEvent] = OutboxEvent) -> None:
        self.model = model
        self.table_name = model.__tablename__

    # ------------------------------------------------------------------
    # Insert / get
    # ------------------------------------------------------------------

    def add(self, session: Session, event: OutboxEvent) -> OutboxEvent:
        session.add(event)
        session.flush()
        return event

    async def add_async(self, session: AsyncSession, event: OutboxEvent) -> OutboxEvent:
        session.add(event)
        await session.flush()
        return event

    def get(self, session: Session, event_id: uuid.UUID) -> OutboxEvent | None:
        return session.get(self.model, event_id)

    async def get_async(self, session: AsyncSession, event_id: uuid.UUID) -> OutboxEvent | None:
        return await session.get(self.model, event_id)

    def get_required(self, session: Session, event_id: uuid.UUID) -> OutboxEvent:
        event = self.get(session, event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")
        return event

    async def get_required_async(
        self, session: AsyncSession, event_id: uuid.UUID
    ) -> OutboxEvent:
        event = await self.get_async(session, event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")
        return event

    # ------------------------------------------------------------------
    # Claim (FIFO + SKIP LOCKED)
    # ------------------------------------------------------------------

    def _claim_sql(self) -> str:
        # Table name is validated against [A-Za-z_][A-Za-z0-9_]* before use.
        table = self.table_name
        return f"""
UPDATE {table} AS o
SET status = :processing,
    worker_id = :worker_id,
    processing_started_at = :now,
    updated_at = :now,
    error_code = NULL,
    last_error = NULL
WHERE o.event_id = (
    SELECT e.event_id
    FROM {table} AS e
    WHERE (
            e.status = :created
            OR (
                e.status = :failed
                AND (
                    e.last_retry_timestamp IS NULL
                    OR e.last_retry_timestamp + make_interval(
                        secs => (
                            LEAST(
                                CAST(:max_delay_ms AS double precision),
                                CAST(:initial_delay_ms AS double precision)
                                  * POWER(
                                        CAST(:multiplier AS double precision),
                                        GREATEST(e.retry_count - 1, 0)
                                    )
                            ) / 1000.0
                        )
                    ) <= NOW()
                )
            )
        )
      AND NOT EXISTS (
            SELECT 1
            FROM {table} AS earlier
            WHERE earlier.event_group = e.event_group
              AND earlier.group_sequence < e.group_sequence
              AND earlier.status IN (:created, :processing, :failed, :retry_exhausted)
        )
    ORDER BY e.event_group, e.group_sequence, e.created_at, e.event_id
    FOR UPDATE OF e SKIP LOCKED
    LIMIT 1
)
RETURNING o.event_id
"""

    def claim_next(
        self,
        session: Session,
        *,
        worker_id: str,
        initial_retry_delay_ms: int,
        retry_backoff_multiplier: float,
        max_retry_delay_ms: int,
    ) -> OutboxEvent | None:
        now = _utcnow()
        result = session.execute(
            text(self._claim_sql()),
            {
                "created": EventStatus.CREATED.value,
                "failed": EventStatus.FAILED.value,
                "processing": EventStatus.PROCESSING.value,
                "retry_exhausted": EventStatus.RETRY_EXHAUSTED.value,
                "worker_id": worker_id,
                "now": now,
                "initial_delay_ms": initial_retry_delay_ms,
                "multiplier": retry_backoff_multiplier,
                "max_delay_ms": max_retry_delay_ms,
            },
        )
        row = result.first()
        if row is None:
            return None
        event_id = row[0]
        return self.get(session, event_id)

    async def claim_next_async(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        initial_retry_delay_ms: int,
        retry_backoff_multiplier: float,
        max_retry_delay_ms: int,
    ) -> OutboxEvent | None:
        now = _utcnow()
        result = await session.execute(
            text(self._claim_sql()),
            {
                "created": EventStatus.CREATED.value,
                "failed": EventStatus.FAILED.value,
                "processing": EventStatus.PROCESSING.value,
                "retry_exhausted": EventStatus.RETRY_EXHAUSTED.value,
                "worker_id": worker_id,
                "now": now,
                "initial_delay_ms": initial_retry_delay_ms,
                "multiplier": retry_backoff_multiplier,
                "max_delay_ms": max_retry_delay_ms,
            },
        )
        row = result.first()
        if row is None:
            return None
        event_id = row[0]
        return await self.get_async(session, event_id)

    # ------------------------------------------------------------------
    # Status updates (ownership-checked)
    # ------------------------------------------------------------------

    def mark_synced(
        self,
        session: Session,
        *,
        event_id: uuid.UUID,
        worker_id: str,
        reply_reference_type: str,
        reply_reference: str,
    ) -> bool:
        now = _utcnow()
        result = session.execute(
            update(self.model)
            .where(
                self.model.event_id == event_id,
                self.model.status == EventStatus.PROCESSING.value,
                self.model.worker_id == worker_id,
            )
            .values(
                status=EventStatus.SYNCED.value,
                reply_reference_type=reply_reference_type,
                reply_reference=reply_reference,
                processed_at=now,
                updated_at=now,
                error_code=None,
                last_error=None,
                processing_started_at=None,
            )
        )
        return (result.rowcount or 0) > 0

    async def mark_synced_async(
        self,
        session: AsyncSession,
        *,
        event_id: uuid.UUID,
        worker_id: str,
        reply_reference_type: str,
        reply_reference: str,
    ) -> bool:
        now = _utcnow()
        result = await session.execute(
            update(self.model)
            .where(
                self.model.event_id == event_id,
                self.model.status == EventStatus.PROCESSING.value,
                self.model.worker_id == worker_id,
            )
            .values(
                status=EventStatus.SYNCED.value,
                reply_reference_type=reply_reference_type,
                reply_reference=reply_reference,
                processed_at=now,
                updated_at=now,
                error_code=None,
                last_error=None,
                processing_started_at=None,
            )
        )
        return (result.rowcount or 0) > 0

    def mark_failed(
        self,
        session: Session,
        *,
        event_id: uuid.UUID,
        worker_id: str,
        retry_count: int,
        error_code: str,
        last_error: str,
        exhausted: bool,
    ) -> bool:
        now = _utcnow()
        status = (
            EventStatus.RETRY_EXHAUSTED.value if exhausted else EventStatus.FAILED.value
        )
        result = session.execute(
            update(self.model)
            .where(
                self.model.event_id == event_id,
                self.model.status == EventStatus.PROCESSING.value,
                self.model.worker_id == worker_id,
            )
            .values(
                status=status,
                retry_count=retry_count,
                last_retry_timestamp=now,
                error_code=error_code,
                last_error=last_error,
                updated_at=now,
                processing_started_at=None,
            )
        )
        return (result.rowcount or 0) > 0

    async def mark_failed_async(
        self,
        session: AsyncSession,
        *,
        event_id: uuid.UUID,
        worker_id: str,
        retry_count: int,
        error_code: str,
        last_error: str,
        exhausted: bool,
    ) -> bool:
        now = _utcnow()
        status = (
            EventStatus.RETRY_EXHAUSTED.value if exhausted else EventStatus.FAILED.value
        )
        result = await session.execute(
            update(self.model)
            .where(
                self.model.event_id == event_id,
                self.model.status == EventStatus.PROCESSING.value,
                self.model.worker_id == worker_id,
            )
            .values(
                status=status,
                retry_count=retry_count,
                last_retry_timestamp=now,
                error_code=error_code,
                last_error=last_error,
                updated_at=now,
                processing_started_at=None,
            )
        )
        return (result.rowcount or 0) > 0

    def mark_configuration_exhausted(
        self,
        session: Session,
        *,
        event_id: uuid.UUID,
        worker_id: str,
        error_code: str,
        last_error: str,
    ) -> bool:
        """Terminal failure for permanent configuration errors (no retries)."""
        now = _utcnow()
        result = session.execute(
            update(self.model)
            .where(
                self.model.event_id == event_id,
                self.model.status == EventStatus.PROCESSING.value,
                self.model.worker_id == worker_id,
            )
            .values(
                status=EventStatus.RETRY_EXHAUSTED.value,
                last_retry_timestamp=now,
                error_code=error_code,
                last_error=last_error,
                updated_at=now,
                processing_started_at=None,
            )
        )
        return (result.rowcount or 0) > 0

    async def mark_configuration_exhausted_async(
        self,
        session: AsyncSession,
        *,
        event_id: uuid.UUID,
        worker_id: str,
        error_code: str,
        last_error: str,
    ) -> bool:
        now = _utcnow()
        result = await session.execute(
            update(self.model)
            .where(
                self.model.event_id == event_id,
                self.model.status == EventStatus.PROCESSING.value,
                self.model.worker_id == worker_id,
            )
            .values(
                status=EventStatus.RETRY_EXHAUSTED.value,
                last_retry_timestamp=now,
                error_code=error_code,
                last_error=last_error,
                updated_at=now,
                processing_started_at=None,
            )
        )
        return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover_stale_processing(
        self,
        session: Session,
        *,
        timeout_ms: int,
    ) -> list[uuid.UUID]:
        cutoff = _utcnow() - timedelta(milliseconds=timeout_ms)
        now = _utcnow()
        # Increment retry_count for abandoned processing events.
        stmt = (
            update(self.model)
            .where(
                self.model.status == EventStatus.PROCESSING.value,
                self.model.processing_started_at.is_not(None),
                self.model.processing_started_at < cutoff,
            )
            .values(
                status=EventStatus.FAILED.value,
                retry_count=self.model.retry_count + 1,
                last_retry_timestamp=now,
                error_code=ERROR_PROCESSING_TIMEOUT,
                last_error="Processing timed out; worker likely crashed or hung",
                updated_at=now,
                processing_started_at=None,
                worker_id=None,
            )
            .returning(self.model.event_id)
        )
        result = session.execute(stmt)
        return [row[0] for row in result.all()]

    async def recover_stale_processing_async(
        self,
        session: AsyncSession,
        *,
        timeout_ms: int,
    ) -> list[uuid.UUID]:
        cutoff = _utcnow() - timedelta(milliseconds=timeout_ms)
        now = _utcnow()
        stmt = (
            update(self.model)
            .where(
                self.model.status == EventStatus.PROCESSING.value,
                self.model.processing_started_at.is_not(None),
                self.model.processing_started_at < cutoff,
            )
            .values(
                status=EventStatus.FAILED.value,
                retry_count=self.model.retry_count + 1,
                last_retry_timestamp=now,
                error_code=ERROR_PROCESSING_TIMEOUT,
                last_error="Processing timed out; worker likely crashed or hung",
                updated_at=now,
                processing_started_at=None,
                worker_id=None,
            )
            .returning(self.model.event_id)
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

    def apply_retry_exhaustion_after_recovery(
        self, session: Session, *, max_retry_count: int
    ) -> int:
        """Move recovered FAILED events that exceeded max retries to RETRY_EXHAUSTED."""
        now = _utcnow()
        result = session.execute(
            update(self.model)
            .where(
                self.model.status == EventStatus.FAILED.value,
                self.model.error_code == ERROR_PROCESSING_TIMEOUT,
                self.model.retry_count > max_retry_count,
            )
            .values(
                status=EventStatus.RETRY_EXHAUSTED.value,
                updated_at=now,
            )
        )
        return result.rowcount or 0

    async def apply_retry_exhaustion_after_recovery_async(
        self, session: AsyncSession, *, max_retry_count: int
    ) -> int:
        now = _utcnow()
        result = await session.execute(
            update(self.model)
            .where(
                self.model.status == EventStatus.FAILED.value,
                self.model.error_code == ERROR_PROCESSING_TIMEOUT,
                self.model.retry_count > max_retry_count,
            )
            .values(
                status=EventStatus.RETRY_EXHAUSTED.value,
                updated_at=now,
            )
        )
        return result.rowcount or 0

    # ------------------------------------------------------------------
    # Admin / query
    # ------------------------------------------------------------------

    def _filter_stmt(
        self,
        *,
        event_type: str | None = None,
        event_group: str | None = None,
        reference_type: str | None = None,
        reference: str | None = None,
        retry_count: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        status: str | Sequence[str] | None = None,
    ) -> Select[Any]:
        stmt = select(self.model)
        if event_type:
            stmt = stmt.where(self.model.event_type == event_type)
        if event_group:
            stmt = stmt.where(self.model.event_group == event_group)
        if reference_type:
            stmt = stmt.where(self.model.reference_type == reference_type)
        if reference:
            stmt = stmt.where(self.model.reference == reference)
        if retry_count is not None:
            stmt = stmt.where(self.model.retry_count == retry_count)
        if created_from:
            stmt = stmt.where(self.model.created_at >= created_from)
        if created_to:
            stmt = stmt.where(self.model.created_at <= created_to)
        if status is not None:
            if isinstance(status, str):
                stmt = stmt.where(self.model.status == status)
            else:
                stmt = stmt.where(self.model.status.in_(list(status)))
        return stmt

    def list_events(
        self,
        session: Session,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> tuple[list[OutboxEvent], int]:
        base = self._filter_stmt(**filters)
        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = session.scalars(
            base.order_by(self.model.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return list(rows), int(total)

    async def list_events_async(
        self,
        session: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> tuple[list[OutboxEvent], int]:
        base = self._filter_stmt(**filters)
        total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
        result = await session.scalars(
            base.order_by(self.model.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.all()), int(total)

    def list_failed(
        self,
        session: Session,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> tuple[list[OutboxEvent], int]:
        status = filters.pop("status", None)
        if status is None:
            filters["status"] = [
                EventStatus.FAILED.value,
                EventStatus.RETRY_EXHAUSTED.value,
            ]
        else:
            filters["status"] = status
        return self.list_events(session, limit=limit, offset=offset, **filters)

    async def list_failed_async(
        self,
        session: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> tuple[list[OutboxEvent], int]:
        status = filters.pop("status", None)
        if status is None:
            filters["status"] = [
                EventStatus.FAILED.value,
                EventStatus.RETRY_EXHAUSTED.value,
            ]
        else:
            filters["status"] = status
        return await self.list_events_async(session, limit=limit, offset=offset, **filters)

    def retry_event(self, session: Session, event_id: uuid.UUID) -> OutboxEvent:
        event = self.get_required(session, event_id)
        if event.status == EventStatus.PROCESSING.value:
            raise InvalidEventStateError(
                "Cannot manually retry an event currently in PROCESSING "
                "(use recovery/force if needed)"
            )
        if event.status not in {
            EventStatus.RETRY_EXHAUSTED.value,
            EventStatus.FAILED.value,
        }:
            raise InvalidEventStateError(
                f"Cannot retry event in status {event.status}; "
                "expected RETRY_EXHAUSTED or FAILED"
            )
        now = _utcnow()
        event.status = EventStatus.CREATED.value
        event.retry_count = 0
        event.last_retry_timestamp = None
        event.error_code = None
        event.last_error = None
        event.worker_id = None
        event.processing_started_at = None
        event.updated_at = now
        session.flush()
        return event

    async def retry_event_async(
        self, session: AsyncSession, event_id: uuid.UUID
    ) -> OutboxEvent:
        event = await self.get_required_async(session, event_id)
        if event.status == EventStatus.PROCESSING.value:
            raise InvalidEventStateError(
                "Cannot manually retry an event currently in PROCESSING "
                "(use recovery/force if needed)"
            )
        if event.status not in {
            EventStatus.RETRY_EXHAUSTED.value,
            EventStatus.FAILED.value,
        }:
            raise InvalidEventStateError(
                f"Cannot retry event in status {event.status}; "
                "expected RETRY_EXHAUSTED or FAILED"
            )
        now = _utcnow()
        event.status = EventStatus.CREATED.value
        event.retry_count = 0
        event.last_retry_timestamp = None
        event.error_code = None
        event.last_error = None
        event.worker_id = None
        event.processing_started_at = None
        event.updated_at = now
        await session.flush()
        return event

    def retry_group(self, session: Session, event_group: str) -> OutboxEvent | None:
        """Reset the lowest-sequence RETRY_EXHAUSTED event in the group.

        FAILED events are left for the automatic retry policy.
        """
        stmt = (
            select(self.model)
            .where(
                self.model.event_group == event_group,
                self.model.status == EventStatus.RETRY_EXHAUSTED.value,
            )
            .order_by(self.model.group_sequence.asc(), self.model.event_id.asc())
            .limit(1)
            .with_for_update()
        )
        event = session.scalars(stmt).first()
        if event is None:
            return None
        return self.retry_event(session, event.event_id)

    async def retry_group_async(
        self, session: AsyncSession, event_group: str
    ) -> OutboxEvent | None:
        stmt = (
            select(self.model)
            .where(
                self.model.event_group == event_group,
                self.model.status == EventStatus.RETRY_EXHAUSTED.value,
            )
            .order_by(self.model.group_sequence.asc(), self.model.event_id.asc())
            .limit(1)
            .with_for_update()
        )
        result = await session.scalars(stmt)
        event = result.first()
        if event is None:
            return None
        return await self.retry_event_async(session, event.event_id)

    def statistics(self, session: Session) -> dict[str, Any]:
        counts = dict(
            session.execute(
                select(self.model.status, func.count())
                .group_by(self.model.status)
            ).all()
        )
        oldest_created = session.scalar(
            select(func.min(self.model.created_at)).where(
                self.model.status == EventStatus.CREATED.value
            )
        )
        oldest_failed = session.scalar(
            select(func.min(self.model.created_at)).where(
                self.model.status.in_(
                    [EventStatus.FAILED.value, EventStatus.RETRY_EXHAUSTED.value]
                )
            )
        )
        oldest_processing = session.scalar(
            select(func.min(self.model.processing_started_at)).where(
                self.model.status == EventStatus.PROCESSING.value
            )
        )
        total = sum(int(v) for v in counts.values())
        return {
            "total": total,
            "created": int(counts.get(EventStatus.CREATED.value, 0)),
            "processing": int(counts.get(EventStatus.PROCESSING.value, 0)),
            "failed": int(counts.get(EventStatus.FAILED.value, 0)),
            "retryExhausted": int(counts.get(EventStatus.RETRY_EXHAUSTED.value, 0)),
            "synced": int(counts.get(EventStatus.SYNCED.value, 0)),
            "oldestCreatedAt": oldest_created.isoformat() if oldest_created else None,
            "oldestFailedAt": oldest_failed.isoformat() if oldest_failed else None,
            "oldestProcessingAt": (
                oldest_processing.isoformat() if oldest_processing else None
            ),
        }

    async def statistics_async(self, session: AsyncSession) -> dict[str, Any]:
        result = await session.execute(
            select(self.model.status, func.count()).group_by(self.model.status)
        )
        counts = dict(result.all())
        oldest_created = await session.scalar(
            select(func.min(self.model.created_at)).where(
                self.model.status == EventStatus.CREATED.value
            )
        )
        oldest_failed = await session.scalar(
            select(func.min(self.model.created_at)).where(
                self.model.status.in_(
                    [EventStatus.FAILED.value, EventStatus.RETRY_EXHAUSTED.value]
                )
            )
        )
        oldest_processing = await session.scalar(
            select(func.min(self.model.processing_started_at)).where(
                self.model.status == EventStatus.PROCESSING.value
            )
        )
        total = sum(int(v) for v in counts.values())
        return {
            "total": total,
            "created": int(counts.get(EventStatus.CREATED.value, 0)),
            "processing": int(counts.get(EventStatus.PROCESSING.value, 0)),
            "failed": int(counts.get(EventStatus.FAILED.value, 0)),
            "retryExhausted": int(counts.get(EventStatus.RETRY_EXHAUSTED.value, 0)),
            "synced": int(counts.get(EventStatus.SYNCED.value, 0)),
            "oldestCreatedAt": oldest_created.isoformat() if oldest_created else None,
            "oldestFailedAt": oldest_failed.isoformat() if oldest_failed else None,
            "oldestProcessingAt": (
                oldest_processing.isoformat() if oldest_processing else None
            ),
        }

    def table_exists(self, session: Session) -> bool:
        result = session.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :table_name"
                ")"
            ),
            {"table_name": self.table_name},
        )
        return bool(result.scalar())

    async def table_exists_async(self, session: AsyncSession) -> bool:
        result = await session.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :table_name"
                ")"
            ),
            {"table_name": self.table_name},
        )
        return bool(result.scalar())
