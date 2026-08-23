"""Source-owned capability ports exposed by the Context application facade."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.memory.domain.entities.context_read_models import (
    ContextPack,
    ContextRecord,
    ContextReindexResult,
    RagDependencyHealth,
)
from app.memory.domain.event_enum.context_enums import (
    ContextKind,
    ContextRecallLifecycleStatus,
    ContextScope,
    RagStrategy,
)


class ContextReadinessPort(ABC):
    """Expose Context retrieval readiness without leaking facade internals."""

    @abstractmethod
    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        """Return retrieval health including persisted index status.

        Returns:
            Current Context retrieval dependency health.
        """


class ContextEmbeddingReindexPort(ABC):
    """Expose bounded Context embedding reindex capability."""

    @abstractmethod
    async def reindex_embeddings(
        self,
        limit: int = 100,
        force: bool = False,
    ) -> ContextReindexResult:
        """Reindex one bounded batch of Context embeddings.

        Args:
            limit: Maximum chunks scanned in one batch.
            force: Whether current embeddings should also be rebuilt.

        Returns:
            Bounded Context embedding reindex result.
        """


class ContextRecoveryPort(ContextReadinessPort, ContextEmbeddingReindexPort, ABC):
    """Expose the Context capabilities required by operational recovery."""


class ContextListPort(ABC):
    """Expose canonical Context listing to application collaborators."""

    @abstractmethod
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
        """Return a filtered canonical Context page and its total count.

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


class ContextTemporalSearchPort(ABC):
    """Expose ranked Context search to temporal reconciliation."""

    @abstractmethod
    async def search(
        self,
        query: str,
        strategy: RagStrategy = RagStrategy.HYBRID,
        limit: int = 5,
        project: str | None = None,
        kind: ContextKind | None = None,
        include_scopes: list[ContextScope] | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        include_lifecycle_statuses: list[ContextRecallLifecycleStatus] | None = None,
    ) -> ContextPack:
        """Return ranked Context matches for one query.

        Args:
            query: Search query text.
            strategy: Requested retrieval strategy.
            limit: Maximum matches.
            project: Optional project filter.
            kind: Optional Context kind filter.
            include_scopes: Optional recall scope filters.
            workspace_id: Optional workspace filter.
            agent_id: Optional agent filter.
            user_id: Optional user filter.
            session_id: Optional session filter.
            include_lifecycle_statuses: Optional administrative lifecycle filter.

        Returns:
            Ranked Context pack with retrieval warnings and evidence.
        """
