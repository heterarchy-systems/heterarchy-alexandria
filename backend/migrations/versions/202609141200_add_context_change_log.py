"""add context change log

Revision ID: 202609141200_change_log
Revises: 202609071940_librarian_drop
Create Date: 2026-09-14 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609141200_change_log"
down_revision: str | None = "202609071940_librarian_drop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply migration."""
    op.create_table(
        "context_change_log",
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("context_id", sa.String(length=36), nullable=False),
        sa.Column("change_kind", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "change_kind IN ('archived','deleted')",
            name="ck_context_change_log_change_kind",
        ),
        sa.PrimaryKeyConstraint("sequence"),
    )
    op.create_index(
        "ix_context_change_log_context_id",
        "context_change_log",
        ["context_id"],
    )
    op.create_table(
        "context_change_log_meta",
        sa.Column("singleton_id", sa.Integer(), nullable=False),
        sa.Column("high_water_seq", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "singleton_id = 1",
            name="ck_context_change_log_meta_singleton",
        ),
        sa.CheckConstraint(
            "high_water_seq >= 0",
            name="ck_context_change_log_meta_non_negative",
        ),
        sa.PrimaryKeyConstraint("singleton_id"),
    )
    op.execute(
        "INSERT INTO context_change_log_meta (singleton_id, high_water_seq) "
        "VALUES (1, 0) ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    """Rollback migration."""
    op.drop_table("context_change_log_meta")
    op.drop_index("ix_context_change_log_context_id", table_name="context_change_log")
    op.drop_table("context_change_log")
