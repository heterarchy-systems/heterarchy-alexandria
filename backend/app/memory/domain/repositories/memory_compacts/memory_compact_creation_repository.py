"""Use-case repository composition for idempotent Memory Compact creation."""

from __future__ import annotations

from abc import abstractmethod
from contextlib import AbstractAsyncContextManager

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
    """Create compacts and query prior signatures for idempotency."""

    @abstractmethod
    def creation_guard(self) -> AbstractAsyncContextManager[None]:
        """Coordinate one complete duplicate-check and create operation.

        Returns:
            Async context manager serializing creation for the canonical store.
        """
        raise NotImplementedError
