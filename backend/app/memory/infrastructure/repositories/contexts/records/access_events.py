"""Persistence helpers for Context Vault access-event history."""

from __future__ import annotations

from app.memory.domain.contracts.context_contracts import ContextAccessCreate
from app.memory.domain.entities.context_read_models import (
    ContextAccessEventRecord,
    ContextRecord,
)
from app.memory.infrastructure.models.context_models import (
    ContextAccessEventORM,
    ContextORM,
)
from app.memory.infrastructure.repositories.contexts.records.mapping import (
    map_access_event_row,
    map_context_row,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def record_context_access(
    session: AsyncSession,
    model: ContextORM,
    payload: ContextAccessCreate,
) -> ContextRecord:
    """Record one context access event and update aggregate counters.

    Args:
        session: Active async session.
        model: Existing context ORM row.
        payload: Context access event fields.

    Returns:
        Updated context read model.
    """
    event = ContextAccessEventORM(
        context_id=payload.context_id,
        accessed_at=payload.accessed_at,
        actor_name=payload.actor_name,
        actor_type=payload.actor_type.value,
        access_method=payload.access_method.value,
        source_surface=payload.source_surface,
    )
    session.add(event)
    await session.execute(
        update(ContextORM)
        .where(ContextORM.id == payload.context_id)
        .values(
            last_accessed_at=payload.accessed_at,
            access_count=ContextORM.access_count + 1,
        )
    )
    await session.flush()
    await session.refresh(model)
    context = map_context_row(model)
    return context


async def list_context_access_events(
    session: AsyncSession,
    context_id: str,
    limit: int,
) -> list[ContextAccessEventRecord]:
    """Return newest access events for one context.

    Args:
        session: Active async session.
        context_id: Context identifier.
        limit: Maximum event rows to return.

    Returns:
        Recent context access events, newest first.
    """
    rows = await session.execute(
        select(ContextAccessEventORM)
        .where(ContextAccessEventORM.context_id == context_id)
        .order_by(ContextAccessEventORM.accessed_at.desc())
        .limit(limit)
    )
    events = [map_access_event_row(row) for row in rows.scalars().all()]
    return events
