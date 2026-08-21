"""Read-only persistence port for memory reconciliation diagnostics."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationStoreDiagnostics,
)


class IMemoryReconciliationReadinessRepository(ABC):
    """Read aggregate reconciliation health without mutating audit state."""

    @abstractmethod
    async def snapshot(self) -> MemoryReconciliationStoreDiagnostics:
        """Return aggregate reconciliation persistence diagnostics.

        Returns:
            MemoryReconciliationStoreDiagnostics: Operation result.
        """
