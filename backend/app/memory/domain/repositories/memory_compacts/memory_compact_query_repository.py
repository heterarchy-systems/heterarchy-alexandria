"""Read persistence port for Memory Compact artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus


class IMemoryCompactQueryRepository(ABC):
    """Read and page durable Memory Compact artifacts."""

    @abstractmethod
    async def get(self, compact_id: str) -> MemoryCompact | None:
        """Read one compact by id.

        Args:
            compact_id: Memory Compact identifier.

        Returns:
            Matching compact, or None when absent.
        """

    @abstractmethod
    async def list_compacts(
        self,
        project: str | None = None,
        status: MemoryCompactStatus | None = None,
        covered_after: datetime | None = None,
        covered_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryCompact], int]:
        """List compacts and total count.

        Args:
            project: Project filter.
            status: Lifecycle status filter.
            covered_after: Coverage-overlap lower bound.
            covered_before: Coverage-overlap upper bound.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip.

        Returns:
            Page of compacts and total matching count.
        """

    @abstractmethod
    async def current(self, project: str | None = None) -> MemoryCompact | None:
        """Read the current compact for a project.

        Args:
            project: Optional project filter; None addresses the default project.

        Returns:
            Current compact, or None when absent.
        """
