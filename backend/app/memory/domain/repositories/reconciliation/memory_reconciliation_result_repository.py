"""Persist and query reconciliation execution results."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationResult


class IMemoryReconciliationResultRepository(ABC):
    """Persist and query reconciliation execution results."""

    @abstractmethod
    async def save_result(
        self,
        result: MemoryReconciliationResult,
    ) -> MemoryReconciliationResult:
        """Persist one reconciliation execution result idempotently.

        Args:
            result: Result.

        Returns:
            MemoryReconciliationResult: Operation result.
        """

    @abstractmethod
    async def get_result(
        self,
        reconciliation_id: str,
    ) -> MemoryReconciliationResult | None:
        """Return one reconciliation result by identifier.

        Args:
            reconciliation_id: Reconciliation id.

        Returns:
            MemoryReconciliationResult | None: Operation result.
        """

    @abstractmethod
    async def get_result_by_plan_id(
        self,
        plan_id: str,
    ) -> MemoryReconciliationResult | None:
        """Return the single execution result for one plan.

        Args:
            plan_id: Plan id.

        Returns:
            MemoryReconciliationResult | None: Operation result.
        """
