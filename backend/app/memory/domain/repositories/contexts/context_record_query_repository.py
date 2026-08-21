"""Read persistence port for Context records and audit history."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.memory.domain.entities.context_read_models import (
    ContextAccessEventRecord,
    ContextChunkRecord,
    ContextRecord,
)
from app.memory.domain.event_enum.context_enums import ContextKind, ContextScope


class IContextRecordQueryRepository(ABC):
    """Read Context records, chunks, and recent access events."""

    @abstractmethod
    async def get(self, context_id: str) -> ContextRecord | None:
        """Return one non-deleted context by id.

        Args:
            context_id: Context identifier.

        Returns:
            Stored context read model when found.
        """

    @abstractmethod
    async def list_all(
        self,
        limit: int,
        offset: int,
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
        """List contexts with filters and total count.

        Args:
            limit: Maximum returned entries.
            offset: Pagination offset.
            kind: Optional context kind filter.
            project: Optional project filter.
            scope: Optional context scope filter.
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
            Matching context rows and total count before pagination.
        """

    @abstractmethod
    async def chunks(self, context_id: str) -> list[ContextChunkRecord]:
        """Return chunks for one context.

        Args:
            context_id: Context identifier.

        Returns:
            Stored chunks for the context.
        """

    @abstractmethod
    async def access_events(
        self, context_id: str, limit: int = 5
    ) -> list[ContextAccessEventRecord]:
        """List recent access events for one context.

        Args:
            context_id: Context identifier.
            limit: Maximum events to return.

        Returns:
            Recent access events ordered newest first.
        """
