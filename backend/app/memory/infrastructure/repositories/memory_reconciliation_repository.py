"""Stable SQLAlchemy facade for memory reconciliation persistence."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.repositories.reconciliation.memory_reconciliation_repository import (
    IMemoryReconciliationRepository,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_conflict_store import (
    ReconciliationConflictStore,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_plan_store import (
    ReconciliationPlanStore,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_relation_store import (
    ReconciliationRelationStore,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_repository_delegates import (
    ReconciliationConflictRepositoryDelegate,
    ReconciliationPlanRepositoryDelegate,
    ReconciliationRelationRepositoryDelegate,
    ReconciliationResultRepositoryDelegate,
    ReconciliationTemporalRepositoryDelegate,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_result_store import (
    ReconciliationResultStore,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_temporal_store import (
    ReconciliationTemporalStore,
)


class SqlAlchemyMemoryReconciliationRepository(
    ReconciliationPlanRepositoryDelegate,
    ReconciliationResultRepositoryDelegate,
    ReconciliationRelationRepositoryDelegate,
    ReconciliationConflictRepositoryDelegate,
    ReconciliationTemporalRepositoryDelegate,
    IMemoryReconciliationRepository,
):
    """Assemble focused stores behind the stable transaction-scoped repository API."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize SqlAlchemyMemoryReconciliationRepository state and dependencies.

        Args:
            session: Active session used by this operation.
        """
        self._plan_store = ReconciliationPlanStore(session)
        self._result_store = ReconciliationResultStore(session)
        self._relation_store = ReconciliationRelationStore(session)
        self._conflict_store = ReconciliationConflictStore(session)
        self._temporal_store = ReconciliationTemporalStore(session)
