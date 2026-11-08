"""Widen the Context change-log ID to match canonical Obsidian note IDs.

Revision ID: 202610221200_context_id_255
Revises: 202609211100_maint_payload
Create Date: 2026-10-22 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202610221200_context_id_255"
down_revision: str | None = "202609211100_maint_payload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow all identifiers supported by the Obsidian note index."""
    op.alter_column(
        "context_change_log",
        "context_id",
        existing_type=sa.String(length=36),
        type_=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Restore UUID width when all logged identifiers fit 36 characters.

    PostgreSQL rejects this narrowing if longer identifiers exist; it does not
    truncate them.
    """
    op.alter_column(
        "context_change_log",
        "context_id",
        existing_type=sa.String(length=255),
        type_=sa.String(length=36),
        existing_nullable=False,
    )
