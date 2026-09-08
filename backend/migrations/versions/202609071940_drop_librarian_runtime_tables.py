"""Drop retired Librarian runtime tables.

Revision ID: 202609071940_librarian_drop
Revises: cabdf60a1fee
Create Date: 2026-09-07 19:40:00+09:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "202609071940_librarian_drop"
down_revision: str | None = "cabdf60a1fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove retired Librarian runtime persistence."""
    op.drop_table("librarian_provider_secrets")
    op.drop_table("skill_acquisition_jobs")
    op.drop_table("obsidian_librarian_workflows")
    op.drop_table("agent_profiles")
    op.drop_table("librarian_providers")


def downgrade() -> None:
    """Leave the destructive Librarian cutover in place."""
