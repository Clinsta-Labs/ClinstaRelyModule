"""SQLAlchemy Outbox event model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hms_outbox.constants import DEFAULT_TABLE_NAME, EventStatus, VALID_STATUSES

_MODEL_CACHE: dict[str, type["OutboxEvent"]] = {}


class Base(DeclarativeBase):
    """Declarative base for Outbox models."""


def create_outbox_event_model(table_name: str = DEFAULT_TABLE_NAME) -> type["OutboxEvent"]:
    """Return an OutboxEvent mapped class bound to ``table_name``.

    Models are cached per table name so repeated calls do not register
    duplicate tables/constraints on the metadata.
    """
    if table_name in _MODEL_CACHE:
        return _MODEL_CACHE[table_name]

    class OutboxEvent(Base):
        """Transactional Outbox event row."""

        __tablename__ = table_name
        __table_args__ = (
            CheckConstraint("retry_count >= 0", name=f"ck_{table_name}_retry_count"),
            CheckConstraint("group_sequence >= 0", name=f"ck_{table_name}_group_sequence"),
            CheckConstraint(
                f"status IN ({', '.join(repr(s) for s in sorted(VALID_STATUSES))})",
                name=f"ck_{table_name}_status",
            ),
            {"extend_existing": True},
        )

        event_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
        )
        event_type: Mapped[str] = mapped_column(String(150), nullable=False)
        event_group: Mapped[str] = mapped_column(String(255), nullable=False)
        group_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
        reference_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
        reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
        payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
        status: Mapped[str] = mapped_column(
            String(30), nullable=False, default=EventStatus.CREATED.value
        )
        retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        last_retry_timestamp: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )
        processing_started_at: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )
        processed_at: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )
        reply_reference_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
        reply_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
        error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
        last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
        worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )

        def to_dict(self) -> dict[str, Any]:
            return {
                "eventId": str(self.event_id),
                "eventType": self.event_type,
                "eventGroup": self.event_group,
                "groupSequence": self.group_sequence,
                "referenceType": self.reference_type,
                "reference": self.reference,
                "payload": self.payload,
                "status": self.status,
                "retryCount": self.retry_count,
                "lastRetryTimestamp": (
                    self.last_retry_timestamp.isoformat() if self.last_retry_timestamp else None
                ),
                "processingStartedAt": (
                    self.processing_started_at.isoformat()
                    if self.processing_started_at
                    else None
                ),
                "processedAt": self.processed_at.isoformat() if self.processed_at else None,
                "replyReferenceType": self.reply_reference_type,
                "replyReference": self.reply_reference,
                "errorCode": self.error_code,
                "lastError": self.last_error,
                "workerId": self.worker_id,
                "createdAt": self.created_at.isoformat() if self.created_at else None,
                "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            }

        def dispatch_body(self) -> dict[str, Any]:
            """HTTP request body sent to the target endpoint."""
            return {
                "eventId": str(self.event_id),
                "eventType": self.event_type,
                "group": self.event_group,
                "groupSequence": self.group_sequence,
                "referenceType": self.reference_type,
                "reference": self.reference,
                "payload": self.payload,
                "createdAt": self.created_at.isoformat().replace("+00:00", "Z")
                if self.created_at
                else None,
            }

    OutboxEvent.__name__ = "OutboxEvent"
    OutboxEvent.__qualname__ = "OutboxEvent"
    _MODEL_CACHE[table_name] = OutboxEvent
    return OutboxEvent


# Default mapped class used by the package and migrations.
OutboxEvent = create_outbox_event_model(DEFAULT_TABLE_NAME)

# Re-export for convenience
from hms_outbox.constants import EventStatus as EventStatus  # noqa: E402

__all__ = ["Base", "EventStatus", "OutboxEvent", "create_outbox_event_model"]
