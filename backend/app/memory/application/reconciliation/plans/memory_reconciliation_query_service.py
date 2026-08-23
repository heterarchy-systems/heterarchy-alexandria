"""Read-only application queries for reconciliation plans and results."""

from __future__ import annotations

from app.memory.domain.entities.memory_reconciliation import (
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_use_case_repositories import (
    IMemoryReconciliationQueryRepository,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)


class MemoryReconciliationQueryService:
    """Read persisted reconciliation audit entities through explicit use cases."""

    def __init__(self, repository: IMemoryReconciliationQueryRepository) -> None:
        """Initialize MemoryReconciliationQueryService state and dependencies.

        Args:
            repository: Repository used by this operation.
        """
        self._repository = repository

    async def get_plan(self, plan_id: str) -> MemoryReconciliationPlan:
        """Return one reconciliation plan or fail explicitly.

        Args:
            plan_id: Plan id.

        Returns:
            MemoryReconciliationPlan: Operation result.
        """
        plan = await self._repository.get_plan(plan_id)
        if plan is None:
            raise MemoryContextNotFoundError(
                f"Memory reconciliation plan not found: {plan_id}"
            )
        return plan

    async def list_review_plans(
        self,
        limit: int = 100,
    ) -> list[MemoryReconciliationPlan]:
        """List durable UNKNOWN or otherwise review-required plans.

        Args:
            limit: Limit.

        Returns:
            list[MemoryReconciliationPlan]: Operation result.
        """
        if limit < 1 or limit > 1000:
            raise MemoryContextValidationError(
                "memory review queue limit must be between 1 and 1000"
            )
        return await self._repository.list_review_plans(limit=limit)

    async def get_result(
        self,
        reconciliation_id: str,
    ) -> MemoryReconciliationResult:
        """Return one reconciliation result or fail explicitly.

        Args:
            reconciliation_id: Reconciliation id.

        Returns:
            MemoryReconciliationResult: Operation result.
        """
        result = await self._repository.get_result(reconciliation_id)
        if result is None:
            raise MemoryContextNotFoundError(
                f"Memory reconciliation result not found: {reconciliation_id}"
            )
        return result
