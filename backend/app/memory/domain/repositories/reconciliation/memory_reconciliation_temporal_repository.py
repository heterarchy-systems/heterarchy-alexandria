"""Persist and query temporal Context overlays."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation import MemoryTemporalState


class IMemoryReconciliationTemporalRepository(ABC):
    """Persist and query temporal Context overlays."""

    @abstractmethod
    async def upsert_temporal_state(
        self,
        state: MemoryTemporalState,
    ) -> MemoryTemporalState:
        """Create or replace the temporal overlay for one Context.

        Args:
            state: State.

        Returns:
            MemoryTemporalState: Operation result.
        """

    @abstractmethod
    async def get_temporal_state(
        self,
        context_id: str,
    ) -> MemoryTemporalState | None:
        """Return the temporal overlay for one Context.

        Args:
            context_id: Context id.

        Returns:
            MemoryTemporalState | None: Operation result.
        """
