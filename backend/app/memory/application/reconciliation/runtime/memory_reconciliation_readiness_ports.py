"""Source-owned readiness capability for memory reconciliation diagnostics."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationDiagnostics,
)


class MemoryReconciliationReadinessPort(ABC):
    """Expose read-only reconciliation diagnostics to other bounded contexts."""

    @abstractmethod
    async def snapshot(self) -> MemoryReconciliationDiagnostics:
        """Return reconciliation diagnostics without mutating durable state.

        Returns:
            Current reconciliation diagnostic snapshot.
        """
