"""maintenance job payload staging.

Revision ID: 202609211100_maint_payload
Revises: 202609141500_error_source_hash
Create Date: 2026-09-21 02:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609211100_maint_payload"
down_revision: str | None = "202609141500_error_source_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable payload staging for asynchronous maintenance jobs."""
    op.create_table(
        "maintenance_job_payloads",
        sa.Column("payload_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("payload_id"),
    )
    op.create_index(
        "ix_maintenance_job_payloads_kind",
        "maintenance_job_payloads",
        ["kind"],
    )


def downgrade() -> None:
    """Drop maintenance job payload staging."""
    op.drop_index("ix_maintenance_job_payloads_kind", "maintenance_job_payloads")
    op.drop_table("maintenance_job_payloads")
