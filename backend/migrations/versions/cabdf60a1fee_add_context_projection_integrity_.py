"""add context projection integrity snapshot.

Revision ID: cabdf60a1fee
Revises: 202608070100_credential_text
Create Date: 2026-08-24 23:19:50.418363
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cabdf60a1fee"
down_revision: str | None = "202608070100_credential_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply migration."""
    op.create_table(
        "context_projection_integrity_snapshot",
        sa.Column("singleton_id", sa.Integer(), nullable=False),
        sa.Column("source_revision", sa.String(length=255), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("failure_counts", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "singleton_id = 1",
            name="ck_context_projection_integrity_singleton",
        ),
        sa.CheckConstraint(
            "scanned_count >= 0 AND valid_count >= 0 AND invalid_count >= 0",
            name="ck_context_projection_integrity_non_negative_counts",
        ),
        sa.CheckConstraint(
            "valid_count + invalid_count = scanned_count",
            name="ck_context_projection_integrity_count_balance",
        ),
        sa.PrimaryKeyConstraint("singleton_id"),
    )


def downgrade() -> None:
    """Rollback migration."""
    op.drop_table("context_projection_integrity_snapshot")
