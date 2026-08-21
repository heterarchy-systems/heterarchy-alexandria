"""Focused delegation mixins for the SQLAlchemy reconciliation repository facade."""

from __future__ import annotations

from app.memory.domain.entities.memory_reconciliation import (
    MemoryConflictSet,
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
    MemoryRelationRecord,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryConflictStatus
from app.memory.infrastructure.repositories.reconciliation.reconciliation_conflict_store import (
    ReconciliationConflictStore,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_plan_store import (
    ReconciliationPlanStore,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_relation_store import (
    ReconciliationRelationStore,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_result_store import (
    ReconciliationResultStore,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_temporal_store import (
    ReconciliationTemporalStore,
)


class ReconciliationPlanRepositoryDelegate:
    """Delegate one focused reconciliation persistence responsibility."""

    _plan_store: ReconciliationPlanStore

    async def save_plan(
        self,
        plan: MemoryReconciliationPlan,
    ) -> MemoryReconciliationPlan:
        """Persist one plan idempotently by stable idempotency key.

        Args:
            plan: Plan.

        Returns:
            MemoryReconciliationPlan: Operation result.
        """
        return await self._plan_store.save_plan(plan)

    async def get_plan(self, plan_id: str) -> MemoryReconciliationPlan | None:
        """Return one plan by identifier.

        Args:
            plan_id: Plan id.

        Returns:
            MemoryReconciliationPlan | None: Operation result.
        """
        return await self._plan_store.get_plan(plan_id)

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
        return await self._plan_store.get_plan_by_idempotency_key(idempotency_key)

    async def list_review_plans(
        self,
        limit: int = 100,
    ) -> list[MemoryReconciliationPlan]:
        """List persisted plans that require explicit review.

        Args:
            limit: Limit.

        Returns:
            list[MemoryReconciliationPlan]: Operation result.
        """
        return await self._plan_store.list_review_plans(limit=limit)


class ReconciliationResultRepositoryDelegate:
    """Delegate one focused reconciliation persistence responsibility."""

    _result_store: ReconciliationResultStore

    async def save_result(
        self,
        result: MemoryReconciliationResult,
    ) -> MemoryReconciliationResult:
        """Persist the latest result for one plan.

        Args:
            result: Result.

        Returns:
            MemoryReconciliationResult: Operation result.
        """
        return await self._result_store.save_result(result)

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
        return await self._result_store.get_result(reconciliation_id)

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
        return await self._result_store.get_result_by_plan_id(plan_id)


class ReconciliationRelationRepositoryDelegate:
    """Delegate one focused reconciliation persistence responsibility."""

    _relation_store: ReconciliationRelationStore

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
        return await self._relation_store.upsert(relation)

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
        return await self._relation_store.list_for_context(context_id)


class ReconciliationConflictRepositoryDelegate:
    """Delegate one focused reconciliation persistence responsibility."""

    _conflict_store: ReconciliationConflictStore

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
        return await self._conflict_store.upsert(conflict)

    async def get_conflict(self, conflict_set_id: str) -> MemoryConflictSet | None:
        """Return one conflict set by identifier.

        Args:
            conflict_set_id: Conflict set id.

        Returns:
            MemoryConflictSet | None: Operation result.
        """
        return await self._conflict_store.get(conflict_set_id)

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
        return await self._conflict_store.list(status=status, limit=limit)


class ReconciliationTemporalRepositoryDelegate:
    """Delegate one focused reconciliation persistence responsibility."""

    _temporal_store: ReconciliationTemporalStore

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
        return await self._temporal_store.upsert(state)

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
        return await self._temporal_store.get(context_id)
