"""Context record query routing across canonical Markdown and SQL storage."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.entities.context_read_models import (
    ContextAccessEventRecord,
    ContextChunkRecord,
    ContextRecord,
)
from app.memory.domain.event_enum.context_enums import ContextKind, ContextScope
from app.memory.domain.repositories.contexts.canonical_context_repository import (
    ICanonicalContextRepository,
)
from app.memory.domain.repositories.contexts.context_record_query_repository import (
    IContextRecordQueryRepository,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)
from app.shared.types.types_convert_utils import enum_value


class ContextRecordQueryService:
    """Read Context records while preserving canonical storage ownership."""

    def __init__(
        self,
        repository: IContextRecordQueryRepository,
        canonical_repository: ICanonicalContextRepository | None,
    ) -> None:
        """Create the Context record query service.

        Args:
            repository: SQL-backed Context repository.
            canonical_repository: Optional canonical Markdown Context repository.
        """
        self._repository = repository
        self._canonical_repository = canonical_repository

    async def get(self, context_id: str) -> ContextRecord:
        """Return one Context from its owning storage surface.

        Args:
            context_id: Context identifier.

        Returns:
            Stored Context read model.
        """
        canonical_repository = self._canonical_repository
        if owns_canonical_context(canonical_repository, context_id):
            assert canonical_repository is not None
            context = await canonical_repository.get(context_id)
        else:
            context = await self._repository.get(context_id)
        if context is None:
            raise MemoryContextNotFoundError(f"Context not found: {context_id}")
        return context

    async def list_contexts(
        self,
        limit: int = 50,
        offset: int = 0,
        kind: ContextKind | None = None,
        project: str | None = None,
        scope: ContextScope | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        source_agent: str | None = None,
        tag: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        include_archived: bool = False,
    ) -> tuple[list[ContextRecord], int]:
        """List SQL-backed Context records with filters.

        Args:
            limit: Maximum returned entries.
            offset: Pagination offset.
            kind: Optional Context kind filter.
            project: Optional project filter.
            scope: Optional scope filter.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            source_agent: Optional source-agent filter.
            tag: Optional tag filter.
            created_after: Optional inclusive created-at lower bound.
            created_before: Optional inclusive created-at upper bound.
            updated_after: Optional inclusive updated-at lower bound.
            updated_before: Optional inclusive updated-at upper bound.
            include_archived: Whether archived entries are included.

        Returns:
            Matching Context rows and total count before pagination.
        """
        if kind is not None:
            kind = enum_value(kind, ContextKind, "kind")
        if scope is not None:
            scope = enum_value(scope, ContextScope, "scope")
        return await self._repository.list_all(
            limit=limit,
            offset=offset,
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

    async def chunks(self, context_id: str) -> list[ContextChunkRecord]:
        """Return SQL chunks for one non-canonical Context.

        Args:
            context_id: Context identifier.

        Returns:
            Stored chunks for the Context.
        """
        if owns_canonical_context(self._canonical_repository, context_id):
            raise MemoryContextValidationError(
                "Canonical Markdown contexts do not expose SQL chunk operations"
            )
        await self.get(context_id)
        return await self._repository.chunks(context_id)

    async def access_events(
        self,
        context_id: str,
        limit: int = 5,
    ) -> list[ContextAccessEventRecord]:
        """Return recent SQL access events for one Context.

        Args:
            context_id: Context identifier.
            limit: Maximum events to return.

        Returns:
            Recent access events ordered newest first.
        """
        if owns_canonical_context(self._canonical_repository, context_id):
            raise MemoryContextValidationError(
                "Canonical Markdown context access events are not stored in SQL"
            )
        return await self._repository.access_events(
            context_id=context_id,
            limit=limit,
        )


def owns_canonical_context(
    canonical_repository: ICanonicalContextRepository | None,
    context_id: str,
) -> bool:
    """Return whether the canonical Markdown repository owns one identifier.

    Args:
        canonical_repository: Optional canonical Context repository.
        context_id: Context identifier.

    Returns:
        Whether the identifier belongs to canonical Markdown storage.
    """
    return canonical_repository is not None and canonical_repository.owns(context_id)
