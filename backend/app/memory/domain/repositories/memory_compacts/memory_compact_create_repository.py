"""Creation persistence port for Memory Compact artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)


class IMemoryCompactCreateRepository(ABC):
    """Create normalized Memory Compact artifacts."""

    @abstractmethod
    async def create(self, payload: MemoryCompactCreate) -> MemoryCompact:
        """Create a compact and its source refs.

        Args:
            payload: Memory Compact creation contract.

        Returns:
            Created Memory Compact entity.
        """
