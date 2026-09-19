"""persist raw source hash for incremental knowledge compile

Revision ID: 202609141400_compile_source_hash
Revises: 202609141300_change_kinds
Create Date: 2026-09-14 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609141400_compile_source_hash"
down_revision: str | None = "202609141300_change_kinds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the raw source fingerprint used by CompilePlan diffing."""
    op.add_column(
        "obsidian_files",
        sa.Column("source_hash", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE obsidian_files SET source_hash = content_hash")
    op.alter_column("obsidian_files", "source_hash", nullable=False)


def downgrade() -> None:
    """Remove persisted raw source fingerprints."""
    op.drop_column("obsidian_files", "source_hash")
