"""Read-only application service for memory reconciliation diagnostics."""

from __future__ import annotations

from app.memory.application.contexts.records.context_service_ports import (
    ContextListPort,
)
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_ports import (
    MemoryReconciliationReadinessPort,
)
from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationDiagnostics,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_readiness_repository import (
    IMemoryReconciliationReadinessRepository,
)


class MemoryReconciliationReadinessService(MemoryReconciliationReadinessPort):
    """Combine reconciliation SQL metrics with canonical Context coverage."""

    def __init__(
        self,
        repository: IMemoryReconciliationReadinessRepository,
        context_service: ContextListPort,
    ) -> None:
        """Initialize MemoryReconciliationReadinessService state and dependencies.

        Args:
            repository: Repository used by this operation.
            context_service: Context service dependency.
        """
        self._repository = repository
        self._context_service = context_service

    async def snapshot(self) -> MemoryReconciliationDiagnostics:
        """Return read-only reconciliation diagnostics without changing state.

        Returns:
            MemoryReconciliationDiagnostics: Operation result.
        """
        store = await self._repository.snapshot()
        _, total_contexts = await self._context_service.list_contexts(
            limit=1,
            offset=0,
            project=None,
            scope=None,
            include_archived=True,
        )
        missing_temporal_states = max(total_contexts - store.temporal_state_count, 0)
        return MemoryReconciliationDiagnostics(
            reachable=store.reachable,
            total_contexts=total_contexts,
            temporal_state_count=store.temporal_state_count,
            missing_temporal_states=missing_temporal_states,
            total_plans=store.total_plans,
            pending_review_plans=store.pending_review_plans,
            total_results=store.total_results,
            partial_apply_results=store.partial_apply_results,
            failed_results=store.failed_results,
            open_conflicts=store.open_conflicts,
            reviewing_conflicts=store.reviewing_conflicts,
            hard_delete_results=store.hard_delete_results,
            latest_failure_code=store.latest_failure_code,
            latest_failure_at=store.latest_failure_at,
        )
