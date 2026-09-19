"""extend context change kinds

Revision ID: 202609141300_change_kinds
Revises: 202609141200_change_log
Create Date: 2026-09-14 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "202609141300_change_kinds"
down_revision: str | None = "202609141200_change_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_context_change_log_change_kind"
_EXTENDED_PREDICATE = (
    "change_kind IN ('created', 'updated', 'superseded', 'archived', 'deleted')"
)
_LEGACY_PREDICATE = "change_kind IN ('archived', 'deleted')"


def upgrade() -> None:
    """Apply migration."""
    op.execute(f"ALTER TABLE context_change_log DROP CONSTRAINT {_CONSTRAINT_NAME}")
    op.execute(
        f"ALTER TABLE context_change_log ADD CONSTRAINT {_CONSTRAINT_NAME} "
        f"CHECK ({_EXTENDED_PREDICATE})"
    )


def downgrade() -> None:
    """Rollback migration."""
    op.execute(
        "DELETE FROM context_change_log WHERE change_kind IN "
        "('created', 'updated', 'superseded')"
    )
    op.execute(f"ALTER TABLE context_change_log DROP CONSTRAINT {_CONSTRAINT_NAME}")
    op.execute(
        f"ALTER TABLE context_change_log ADD CONSTRAINT {_CONSTRAINT_NAME} "
        f"CHECK ({_LEGACY_PREDICATE})"
    )
