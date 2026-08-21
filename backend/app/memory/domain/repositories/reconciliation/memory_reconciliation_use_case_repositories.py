"""Use-case repository compositions for memory reconciliation application services."""

from __future__ import annotations

from app.memory.domain.repositories.reconciliation.memory_reconciliation_conflict_repository import (
    IMemoryReconciliationConflictRepository,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_plan_repository import (
    IMemoryReconciliationPlanRepository,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_relation_repository import (
    IMemoryReconciliationRelationRepository,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_result_repository import (
    IMemoryReconciliationResultRepository,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_temporal_repository import (
    IMemoryReconciliationTemporalRepository,
)


class IMemoryReconciliationStateRepository(
    IMemoryReconciliationRelationRepository,
    IMemoryReconciliationConflictRepository,
    IMemoryReconciliationTemporalRepository,
):
    """Persist relation, conflict, and temporal state produced during apply."""


class IMemoryReconciliationApplyRepository(
    IMemoryReconciliationPlanRepository,
    IMemoryReconciliationResultRepository,
    IMemoryReconciliationStateRepository,
):
    """Provide plan, result, and state persistence required by apply execution."""


class IMemoryReconciliationQueryRepository(
    IMemoryReconciliationPlanRepository,
    IMemoryReconciliationResultRepository,
):
    """Provide only plan and result reads required by audit queries."""


class IMemoryExistingReconciliationRepository(
    IMemoryReconciliationPlanRepository,
    IMemoryReconciliationTemporalRepository,
):
    """Provide plan and temporal persistence required by existing-memory analysis."""
