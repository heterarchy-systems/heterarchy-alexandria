"""Persist and query immutable reconciliation plans."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationPlan


class IMemoryReconciliationPlanRepository(ABC):
    """Persist and query immutable reconciliation plans."""

    @abstractmethod
    async def save_plan(
        self,
        plan: MemoryReconciliationPlan,
    ) -> MemoryReconciliationPlan:
        """Persist one plan idempotently by idempotency key.

        Args:
            plan: Plan.

        Returns:
            MemoryReconciliationPlan: Operation result.
        """

    @abstractmethod
    async def get_plan(self, plan_id: str) -> MemoryReconciliationPlan | None:
        """Return one plan by identifier.

        Args:
            plan_id: Plan id.

        Returns:
            MemoryReconciliationPlan | None: Operation result.
        """

    @abstractmethod
    async def get_plan_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> MemoryReconciliationPlan | None:
        """Return one plan by stable idempotency key.

        Args:
            idempotency_key: Idempotency key.

        Returns:
            MemoryReconciliationPlan | None: Operation result.
        """

    @abstractmethod
    async def list_review_plans(
        self,
        limit: int = 100,
    ) -> list[MemoryReconciliationPlan]:
        """List durable plans that require explicit human review.

        Args:
            limit: Limit.

        Returns:
            list[MemoryReconciliationPlan]: Operation result.
        """
