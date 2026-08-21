"""Composite port for transaction-scoped memory reconciliation persistence."""

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


class IMemoryReconciliationRepository(
    IMemoryReconciliationPlanRepository,
    IMemoryReconciliationResultRepository,
    IMemoryReconciliationRelationRepository,
    IMemoryReconciliationConflictRepository,
    IMemoryReconciliationTemporalRepository,
):
    """Combine focused reconciliation ports for transaction-scoped use cases."""
