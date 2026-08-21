"""Stable Memory Compact application facade."""

from __future__ import annotations

from datetime import datetime

from app.memory.application.memory_compacts.lifecycle.memory_compact_creation_service import (
    MemoryCompactCreationService,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_lifecycle_service import (
    MemoryCompactLifecycleService,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_query_service import (
    MemoryCompactQueryService,
)
from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactReviewResult,
    MemoryCompactSourceObservation,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_repository import (
    IMemoryCompactRepository,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)


class MemoryCompactService:
    """Expose the stable Memory Compact API over focused use-case services.

    Creation policy, duplicate signatures, read pagination, lifecycle mutation,
    and rubric review are delegated to focused collaborators. The facade keeps the
    eight public methods because HTTP, MCP, CLI, and operations consume this single
    application contract.
    """

    def __init__(self, repository: IMemoryCompactRepository) -> None:
        """Initialize service dependencies.

        Args:
            repository: Persistence port for Memory Compact artifacts.
        """
        self._query_service = MemoryCompactQueryService(repository)
        self._creation_service = MemoryCompactCreationService(repository)
        self._lifecycle_service = MemoryCompactLifecycleService(
            repository=repository,
            query_service=self._query_service,
        )

    async def create(self, payload: MemoryCompactCreate) -> MemoryCompact:
        """Create a compact and enforce lifecycle invariants.

        Args:
            payload: Validated Memory Compact creation contract.

        Returns:
            Created Memory Compact entity.
        """
        return await self._creation_service.create(payload)

    async def get(self, compact_id: str) -> MemoryCompact:
        """Read one Memory Compact by id.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Matching Memory Compact entity.
        """
        return await self._query_service.get(compact_id)

    async def list_compacts(
        self,
        project: str | None = None,
        status: MemoryCompactStatus | None = None,
        covered_after: datetime | None = None,
        covered_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryCompact], int]:
        """List Memory Compacts.

        Args:
            project: Project filter.
            status: Lifecycle status filter.
            covered_after: Coverage-overlap lower bound.
            covered_before: Coverage-overlap upper bound.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip.

        Returns:
            Page of Memory Compacts and the total matching count.
        """
        return await self._query_service.list_compacts(
            project=project,
            status=status,
            covered_after=covered_after,
            covered_before=covered_before,
            limit=limit,
            offset=offset,
        )

    async def current(self, project: str | None = None) -> MemoryCompact:
        """Read the current compact for a project.

        Args:
            project: Optional project filter; None addresses the default project.

        Returns:
            Current Memory Compact entity.
        """
        return await self._query_service.current(project=project)

    async def mark_current(self, compact_id: str) -> MemoryCompact:
        """Mark one compact as current.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Updated current Memory Compact entity.
        """
        return await self._lifecycle_service.mark_current(compact_id)

    async def archive(self, compact_id: str) -> MemoryCompact:
        """Archive one Memory Compact.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Archived Memory Compact entity.
        """
        return await self._lifecycle_service.archive(compact_id)

    async def delete(self, compact_id: str) -> None:
        """Hard delete one Memory Compact.

        Args:
            compact_id: Memory Compact identifier.
        """
        await self._lifecycle_service.delete(compact_id)

    async def review(
        self,
        compact_id: str,
        source_observations: tuple[MemoryCompactSourceObservation, ...] = (),
    ) -> MemoryCompactReviewResult:
        """Review one Memory Compact against the librarian rubric.

        Args:
            compact_id: Memory Compact identifier.
            source_observations: Optional current source evidence observations.

        Returns:
            Structured review result.
        """
        return await self._lifecycle_service.review(
            compact_id,
            source_observations=source_observations,
        )
