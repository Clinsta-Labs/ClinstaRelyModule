"""Add organization_id for org-scoped FIFO.

Revision ID: 20260813_0002
Revises: 20260811_0001
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0002"
down_revision: Union[str, None] = "20260811_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "outbox_event"


def _has_column(conn: sa.Connection, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
            """
        ),
        {"table": table, "column": column},
    ).first()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, TABLE, "organization_id"):
        # Greenfield installs already created organization_id in 0001.
        return

    count = conn.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar() or 0
    if int(count) > 0:
        raise RuntimeError(
            "Cannot add NOT NULL organization_id: outbox_event already has rows. "
            "Truncate or backfill organization_id before upgrading to 0.2.0."
        )

    op.add_column(TABLE, sa.Column("organization_id", sa.Integer(), nullable=False))
    op.create_check_constraint(
        f"ck_{TABLE}_organization_id",
        TABLE,
        "organization_id > 0",
    )

    op.drop_index(f"ix_{TABLE}_status_group_seq", table_name=TABLE)
    op.create_index(
        f"ix_{TABLE}_status_group_seq",
        TABLE,
        ["status", "organization_id", "event_group", "group_sequence"],
    )

    op.drop_index(f"ix_{TABLE}_group_seq", table_name=TABLE)
    op.create_index(
        f"ix_{TABLE}_org_group_seq",
        TABLE,
        ["organization_id", "event_group", "group_sequence"],
    )

    op.execute(f"DROP INDEX IF EXISTS ix_{TABLE}_claimable")
    op.execute(
        f"""
        CREATE INDEX ix_{TABLE}_claimable
        ON {TABLE} (organization_id, event_group, group_sequence, created_at, event_id)
        WHERE status IN ('CREATED', 'FAILED')
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, TABLE, "organization_id"):
        return

    op.execute(f"DROP INDEX IF EXISTS ix_{TABLE}_claimable")
    op.execute(
        f"""
        CREATE INDEX ix_{TABLE}_claimable
        ON {TABLE} (event_group, group_sequence, created_at, event_id)
        WHERE status IN ('CREATED', 'FAILED')
        """
    )

    op.drop_index(f"ix_{TABLE}_org_group_seq", table_name=TABLE)
    op.create_index(
        f"ix_{TABLE}_group_seq",
        TABLE,
        ["event_group", "group_sequence"],
    )

    op.drop_index(f"ix_{TABLE}_status_group_seq", table_name=TABLE)
    op.create_index(
        f"ix_{TABLE}_status_group_seq",
        TABLE,
        ["status", "event_group", "group_sequence"],
    )

    op.drop_constraint(f"ck_{TABLE}_organization_id", TABLE, type_="check")
    op.drop_column(TABLE, "organization_id")
