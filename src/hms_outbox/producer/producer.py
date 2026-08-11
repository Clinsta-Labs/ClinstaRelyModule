"""Transactional Outbox producer (sync and async)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from hms_outbox.constants import DEFAULT_TABLE_NAME, EventStatus
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.models.event import OutboxEvent, create_outbox_event_model


class OutboxProducer:
    """Lightweight producer API for inserting Outbox events.

    The producer **does not** commit the caller's transaction. Callers must
    insert business rows and Outbox events in the same transaction:

    .. code-block:: python

        with session.begin():
            create_invoice(...)
            event_id = outbox.publish(session, ...)
    """

    def __init__(
        self,
        *,
        table_name: str = DEFAULT_TABLE_NAME,
        repository: OutboxRepository | None = None,
        model: type[OutboxEvent] | None = None,
    ) -> None:
        if model is not None:
            self.model = model
        elif table_name == DEFAULT_TABLE_NAME:
            self.model = OutboxEvent
        else:
            self.model = create_outbox_event_model(table_name)
        self.repository = repository or OutboxRepository(self.model)

    def publish(
        self,
        session: Session,
        *,
        event_type: str,
        event_group: str,
        group_sequence: int,
        payload: dict[str, Any],
        reference_type: str | None = None,
        reference: str | None = None,
        event_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Insert an Outbox event using a sync SQLAlchemy session.

        Returns the EventId. Does not commit.
        """
        if group_sequence < 0:
            raise ValueError("group_sequence must be >= 0")
        if not event_type:
            raise ValueError("event_type is required")
        if not event_group:
            raise ValueError("event_group is required")
        if payload is None:
            raise ValueError("payload is required")

        event = self.model(
            event_id=event_id or uuid.uuid4(),
            event_type=event_type,
            event_group=event_group,
            group_sequence=group_sequence,
            reference_type=reference_type,
            reference=reference,
            payload=payload,
            status=EventStatus.CREATED.value,
            retry_count=0,
        )
        self.repository.add(session, event)
        return event.event_id

    async def publish_async(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        event_group: str,
        group_sequence: int,
        payload: dict[str, Any],
        reference_type: str | None = None,
        reference: str | None = None,
        event_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Insert an Outbox event using an async SQLAlchemy session.

        Returns the EventId. Does not commit.
        """
        if group_sequence < 0:
            raise ValueError("group_sequence must be >= 0")
        if not event_type:
            raise ValueError("event_type is required")
        if not event_group:
            raise ValueError("event_group is required")
        if payload is None:
            raise ValueError("payload is required")

        event = self.model(
            event_id=event_id or uuid.uuid4(),
            event_type=event_type,
            event_group=event_group,
            group_sequence=group_sequence,
            reference_type=reference_type,
            reference=reference,
            payload=payload,
            status=EventStatus.CREATED.value,
            retry_count=0,
        )
        await self.repository.add_async(session, event)
        return event.event_id
