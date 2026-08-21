"""Memory Compact read and pagination service."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_query_repository import (
    IMemoryCompactQueryRepository,
)
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactNotFoundError
from app.shared.types.types_convert_utils import enum_value


class MemoryCompactQueryService:
    """Read and page durable Memory Compact artifacts."""

    def __init__(self, repository: IMemoryCompactQueryRepository) -> None:
        """Create the Memory Compact query service.

        Args:
            repository: Persistence port for Memory Compact artifacts.
        """
        self._repository = repository

    async def get(self, compact_id: str) -> MemoryCompact:
        """Read one Memory Compact by id.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Matching Memory Compact entity.
        """
        compact = await self._repository.get(compact_id)
        if compact is None:
            raise MemoryCompactNotFoundError(f"Memory compact not found: {compact_id}")
        return compact

    async def list_compacts(
        self,
        project: str | None = None,
        status: MemoryCompactStatus | None = None,
        covered_after: datetime | None = None,
        covered_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryCompact], int]:
        """List Memory Compacts with bounded pagination.

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
        if status is not None:
            status = enum_value(status, MemoryCompactStatus, "status")
        return await self._repository.list_compacts(
            project=project,
            status=status,
            covered_after=covered_after,
            covered_before=covered_before,
            limit=min(max(int(limit), 1), 200),
            offset=max(int(offset), 0),
        )

    async def current(self, project: str | None = None) -> MemoryCompact:
        """Read the current compact for a project.

        Args:
            project: Optional project filter; None addresses the default project.

        Returns:
            Current Memory Compact entity.
        """
        compact = await self._repository.current(project=project)
        if compact is None:
            label = "default project" if project is None else project
            raise MemoryCompactNotFoundError(
                f"Current memory compact not found: {label}"
            )
        return compact
