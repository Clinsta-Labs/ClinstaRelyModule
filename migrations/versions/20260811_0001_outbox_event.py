"""Initial outbox_event table, indexes, and constraints."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "outbox_event"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=150), nullable=False),
        sa.Column("event_group", sa.String(length=255), nullable=False),
        sa.Column("group_sequence", sa.BigInteger(), nullable=False),
        sa.Column("reference_type", sa.String(length=100), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_retry_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_reference_type", sa.String(length=100), nullable=True),
        sa.Column("reply_reference", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("retry_count >= 0", name=f"ck_{TABLE}_retry_count"),
        sa.CheckConstraint("group_sequence >= 0", name=f"ck_{TABLE}_group_sequence"),
        sa.CheckConstraint("organization_id > 0", name=f"ck_{TABLE}_organization_id"),
        sa.CheckConstraint(
            "status IN ('CREATED','PROCESSING','FAILED','SYNCED','RETRY_EXHAUSTED')",
            name=f"ck_{TABLE}_status",
        ),
    )

    op.create_index(
        f"ix_{TABLE}_status_group_seq",
        TABLE,
        ["status", "organization_id", "event_group", "group_sequence"],
    )
    op.create_index(
        f"ix_{TABLE}_status_last_retry",
        TABLE,
        ["status", "last_retry_timestamp"],
    )
    op.create_index(
        f"ix_{TABLE}_event_type_status",
        TABLE,
        ["event_type", "status"],
    )
    op.create_index(
        f"ix_{TABLE}_org_group_seq",
        TABLE,
        ["organization_id", "event_group", "group_sequence"],
    )
    op.create_index(
        f"ix_{TABLE}_created_at",
        TABLE,
        ["created_at"],
    )
    op.execute(
        f"""
        CREATE INDEX ix_{TABLE}_claimable
        ON {TABLE} (organization_id, event_group, group_sequence, created_at, event_id)
        WHERE status IN ('CREATED', 'FAILED')
        """
    )
    op.execute(
        f"""
        CREATE INDEX ix_{TABLE}_processing_started
        ON {TABLE} (processing_started_at)
        WHERE status = 'PROCESSING'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS ix_{TABLE}_processing_started")
    op.execute(f"DROP INDEX IF EXISTS ix_{TABLE}_claimable")
    op.drop_index(f"ix_{TABLE}_created_at", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_org_group_seq", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_event_type_status", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_status_last_retry", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_status_group_seq", table_name=TABLE)
    op.drop_table(TABLE)
