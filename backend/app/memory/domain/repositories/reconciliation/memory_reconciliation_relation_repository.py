"""Persist and query directed memory relations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation import MemoryRelationRecord


class IMemoryReconciliationRelationRepository(ABC):
    """Persist and query directed memory relations."""

    @abstractmethod
    async def upsert_relation(
        self,
        relation: MemoryRelationRecord,
    ) -> MemoryRelationRecord:
        """Create or return one directed memory relation.

        Args:
            relation: Relation.

        Returns:
            MemoryRelationRecord: Operation result.
        """

    @abstractmethod
    async def list_relations(
        self,
        context_id: str,
    ) -> list[MemoryRelationRecord]:
        """List relations where the Context is source or target.

        Args:
            context_id: Context id.

        Returns:
            list[MemoryRelationRecord]: Operation result.
        """
