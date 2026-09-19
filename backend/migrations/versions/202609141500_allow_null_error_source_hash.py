"""allow source hash absence for non-compiled index-error rows

Revision ID: 202609141500_error_source_hash
Revises: 202609141400_compile_source_hash
Create Date: 2026-09-14 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609141500_error_source_hash"
down_revision: str | None = "202609141400_compile_source_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Permit diagnostic rows that have no compiled-source fingerprint."""
    op.alter_column(
        "obsidian_files",
        "source_hash",
        existing_type=sa.String(length=64),
        nullable=True,
    )


def downgrade() -> None:
    """Restore the previous non-null storage contract."""
    op.execute(
        "UPDATE obsidian_files SET source_hash = content_hash WHERE source_hash IS NULL"
    )
    op.alter_column(
        "obsidian_files",
        "source_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )
