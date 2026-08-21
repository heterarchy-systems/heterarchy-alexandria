"""Persist and query first-class memory conflict sets."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation import MemoryConflictSet
from app.memory.domain.event_enum.reconciliation_enums import MemoryConflictStatus


class IMemoryReconciliationConflictRepository(ABC):
    """Persist and query first-class memory conflict sets."""

    @abstractmethod
    async def upsert_conflict(
        self,
        conflict: MemoryConflictSet,
    ) -> MemoryConflictSet:
        """Create or update one durable conflict set.

        Args:
            conflict: Conflict.

        Returns:
            MemoryConflictSet: Operation result.
        """

    @abstractmethod
    async def get_conflict(self, conflict_set_id: str) -> MemoryConflictSet | None:
        """Return one conflict set by identifier.

        Args:
            conflict_set_id: Conflict set id.

        Returns:
            MemoryConflictSet | None: Operation result.
        """

    @abstractmethod
    async def list_conflicts(
        self,
        status: MemoryConflictStatus | None = None,
        limit: int = 100,
    ) -> list[MemoryConflictSet]:
        """List conflict sets newest first with an optional status filter.

        Args:
            status: Status.
            limit: Limit.

        Returns:
            list[MemoryConflictSet]: Operation result.
        """
