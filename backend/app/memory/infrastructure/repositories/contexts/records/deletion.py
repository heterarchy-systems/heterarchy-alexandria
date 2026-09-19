"""Hard-delete helpers for Context Vault persistence."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.event_enum.context_enums import ContextChangeKind
from app.memory.infrastructure.models.context_models import (
    ContextAccessEventORM,
    ContextChunkORM,
    ContextORM,
)
from app.memory.infrastructure.repositories.contexts.records.context_change_log_writer import (
    context_change_content_hash,
    record_context_change,
)


async def delete_context_rows(
    session: AsyncSession, context_id: str, model: ContextORM
) -> None:
    """Delete one context and dependent retrieval/audit rows.

    The hard delete and its ``deleted`` change-log record share one
    transaction: the change entry is written before the row is removed so the
    post-change content hash can be computed from the loaded row, and both
    commit (or roll back) together.

    Args:
        session: Active async session.
        context_id: Identifier of the context row to delete.
        model: Loaded context ORM row.

    Returns:
        None.
    """
    await record_context_change(
        session,
        context_id=context_id,
        change_kind=ContextChangeKind.DELETED,
        content_hash=context_change_content_hash(model.content),
        recorded_at=datetime.now(UTC),
    )
    await session.execute(
        delete(ContextAccessEventORM).where(
            ContextAccessEventORM.context_id == context_id
        )
    )
    await session.execute(
        delete(ContextChunkORM).where(ContextChunkORM.context_id == context_id)
    )
    await session.delete(model)
    await session.flush()
