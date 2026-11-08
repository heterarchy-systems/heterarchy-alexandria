"""Use-case repository composition for idempotent Memory Compact creation."""

from __future__ import annotations

from abc import abstractmethod
from contextlib import AbstractAsyncContextManager

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_create_repository import (
    IMemoryCompactCreateRepository,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_query_repository import (
    IMemoryCompactQueryRepository,
)


class IMemoryCompactCreationRepository(
    IMemoryCompactCreateRepository,
    IMemoryCompactQueryRepository,
):
    """Create compacts and read scoped snapshots for idempotency."""

    @abstractmethod
    async def creation_snapshot(
        self,
        project: str | None,
        status: MemoryCompactStatus,
    ) -> list[MemoryCompact]:
        """Read compacts in the exact project/status scope, newest coverage first.

        Args:
            project: Exact project scope, including the default ``None`` project.
            status: Exact lifecycle status to inspect.

        Returns:
            Matching canonical Memory Compact entities in newest-first order.
        """
        raise NotImplementedError

    @abstractmethod
    def creation_guard(self) -> AbstractAsyncContextManager[None]:
        """Coordinate one complete duplicate-check and create operation.

        Returns:
            Async context manager serializing creation for the canonical store.
        """
        raise NotImplementedError
