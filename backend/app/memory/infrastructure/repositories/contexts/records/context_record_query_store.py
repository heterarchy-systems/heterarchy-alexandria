"""SQL-backed Context record query store."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.entities.context_read_models import (
    ContextAccessEventRecord,
    ContextChunkRecord,
    ContextRecord,
)
from app.memory.domain.event_enum.context_enums import ContextKind, ContextScope
from app.memory.infrastructure.models.context_models import ContextChunkORM, ContextORM
from app.memory.infrastructure.repositories.contexts.records.access_events import (
    list_context_access_events,
)
from app.memory.infrastructure.repositories.contexts.records.filters import (
    filtered_context_statement,
)
from app.memory.infrastructure.repositories.contexts.records.mapping import (
    map_chunk_row,
    map_context_row,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextNotFoundError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class ContextRecordQueryStore:
    """Read Context records, chunks, and access events from SQL storage."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the query store.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def get(self, context_id: str) -> ContextRecord | None:
        """Read one Context by identifier.

        Args:
            context_id: Context identifier.

        Returns:
            Context record when present.
        """
        model = await self._session.get(ContextORM, context_id)
        return None if model is None else map_context_row(model)

    async def list_all(
        self,
        limit: int,
        offset: int,
        kind: ContextKind | None,
        project: str | None,
        scope: ContextScope | None,
        workspace_id: str | None,
        agent_id: str | None,
        user_id: str | None,
        session_id: str | None,
        source_agent: str | None,
        tag: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
        updated_after: datetime | None,
        updated_before: datetime | None,
        include_archived: bool,
    ) -> tuple[list[ContextRecord], int]:
        """List Contexts with repository filters and pagination.

        Args:
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            kind: Optional Context kind filter.
            project: Optional project filter.
            scope: Optional scope filter.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            source_agent: Optional source-agent filter.
            tag: Optional tag filter.
            created_after: Optional created-at lower bound.
            created_before: Optional created-at upper bound.
            updated_after: Optional updated-at lower bound.
            updated_before: Optional updated-at upper bound.
            include_archived: Whether archived records are included.

        Returns:
            Matching records and total count before pagination.
        """
        statement = filtered_context_statement(
            kind=kind,
            project=project,
            scope=scope,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            source_agent=source_agent,
            tag=tag,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
            include_archived=include_archived,
        )
        count = await self._session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(ContextORM.updated_at.desc()).limit(limit).offset(offset)
        )
        rows = await self._session.execute(page)
        return [map_context_row(row) for row in rows.scalars().all()], int(count or 0)

    async def chunks(self, context_id: str) -> list[ContextChunkRecord]:
        """Read ordered chunks for one Context.

        Args:
            context_id: Context identifier.

        Returns:
            Ordered Context chunks.
        """
        rows = await self._session.execute(
            select(ContextChunkORM)
            .where(ContextChunkORM.context_id == context_id)
            .order_by(ContextChunkORM.chunk_index)
        )
        return [map_chunk_row(row) for row in rows.scalars().all()]

    async def access_events(
        self,
        context_id: str,
        limit: int,
    ) -> list[ContextAccessEventRecord]:
        """Read recent access events for one Context.

        Args:
            context_id: Context identifier.
            limit: Maximum events to return.

        Returns:
            Recent access events ordered newest first.
        """
        await require_context(self._session, context_id)
        return await list_context_access_events(
            session=self._session,
            context_id=context_id,
            limit=limit,
        )


async def require_context(
    session: AsyncSession,
    context_id: str,
) -> ContextORM:
    """Return one Context ORM model or raise not-found.

    Args:
        session: Active async database session.
        context_id: Context identifier.

    Returns:
        Matching ORM Context model.
    """
    model = await session.get(ContextORM, context_id)
    if model is None:
        raise MemoryContextNotFoundError(f"Context not found: {context_id}")
    return model
