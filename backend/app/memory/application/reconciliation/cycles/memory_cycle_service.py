"""Bounded aggregate orchestration for Memory reconciliation and Compacts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.memory.application.contexts.records.context_service_ports import (
    ContextTemporalSearchPort,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.application.reconciliation.cycles import (
    memory_cycle_checkpoints,
    memory_cycle_readback,
)
from app.memory.application.reconciliation.cycles.memory_cycle_apply import (
    MemoryCycleApplyCoordinator,
)
from app.memory.application.reconciliation.cycles.memory_cycle_checkpoints import (
    MemoryCycleCheckpointStore,
)
from app.memory.application.reconciliation.cycles.memory_cycle_compact_publication import (
    MemoryCycleCompactPublication,
)
from app.memory.application.reconciliation.cycles.memory_cycle_preview import (
    MemoryCyclePreviewPlanner,
    validate_request,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    MemoryCycleSourceFence,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_apply_service import (
    MemoryReconciliationApplyService,
)
from app.memory.application.reconciliation.runtime.memory_existing_reconciliation_service import (
    MemoryExistingReconciliationService,
)
from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.entities.memory_cycle import MemoryCycleResult
from app.memory.domain.event_enum.memory_cycle_enums import MemoryCycleOperation
from app.memory.domain.repositories.reconciliation.memory_reconciliation_use_case_repositories import (
    IMemoryReconciliationApplyRepository,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)


class MemoryCycleService:
    """Validate and dispatch bounded aggregate memory-cycle requests."""

    def __init__(
        self,
        existing_reconciliation_service: MemoryExistingReconciliationService,
        context_service: ContextTemporalSearchPort,
        source_fence: MemoryCycleSourceFence,
        reconciliation_repository: IMemoryReconciliationApplyRepository,
        reconciliation_apply_service: MemoryReconciliationApplyService,
        compact_service: MemoryCompactService,
        compact_policy: MemoryCompactReconciliationPolicy,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        checkpoint_store: MemoryCycleCheckpointStore,
        commit_projection: Callable[[], Awaitable[None]],
        rollback_projection: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize one request-scoped aggregate memory-cycle facade.

        Args:
            existing_reconciliation_service: Existing reconciliation detection service.
            context_service: Context temporal search port.
            source_fence: Canonical source revision fence reader.
            reconciliation_repository: Reconciliation apply repository port.
            reconciliation_apply_service: Reconciliation plan apply service.
            compact_service: Memory Compact application service.
            compact_policy: Memory Compact reconciliation planning policy.
            index_maintenance_coordinator: Exclusive maintenance lease coordinator.
            checkpoint_store: Durable cycle checkpoint store.
            commit_projection: Async callback committing the database transaction.
            rollback_projection: Async callback rolling back the database transaction.
        """
        preview_planner = MemoryCyclePreviewPlanner(
            existing_reconciliation_service=existing_reconciliation_service,
            source_fence=source_fence,
            compact_service=compact_service,
            compact_policy=compact_policy,
        )
        self._preview_planner = preview_planner
        checkpoint_adapter = memory_cycle_checkpoints.MemoryCycleCheckpointAdapter(
            checkpoint_store=checkpoint_store,
        )
        readback = memory_cycle_readback.MemoryCycleReadback(
            context_service=context_service,
            source_fence=source_fence,
            reconciliation_repository=reconciliation_repository,
            compact_service=compact_service,
        )
        compact_publication = MemoryCycleCompactPublication(
            compact_service=compact_service,
        )
        self._apply_coordinator = MemoryCycleApplyCoordinator(
            preview_planner=preview_planner,
            checkpoint_adapter=checkpoint_adapter,
            readback=readback,
            compact_publication=compact_publication,
            source_fence=source_fence,
            reconciliation_repository=reconciliation_repository,
            reconciliation_apply_service=reconciliation_apply_service,
            compact_service=compact_service,
            coordinator=index_maintenance_coordinator,
            commit_projection=commit_projection,
            rollback_projection=rollback_projection,
        )

    async def execute(self, request: MemoryCycleRequest) -> MemoryCycleResult:
        """Run one write-free preview or fenced aggregate apply.

        Args:
            request: Memory cycle dry-run or apply request.

        Returns:
            Memory cycle preview or apply result.
        """
        validate_request(request)
        if request.operation is MemoryCycleOperation.DRY_RUN:
            return (await self._preview_planner.preview(request)).result
        return await self._apply_coordinator.apply(request)
