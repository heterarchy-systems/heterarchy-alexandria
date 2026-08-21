"""SQLAlchemy diagnostics store for memory reconciliation readiness."""

from __future__ import annotations

from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationStoreDiagnostics,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryConflictStatus,
    MemoryReconciliationStatus,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_readiness_repository import (
    IMemoryReconciliationReadinessRepository,
)
from app.memory.infrastructure.models.reconciliation_models import (
    ContextTemporalStateORM,
    MemoryConflictSetORM,
    MemoryReconciliationPlanORM,
    MemoryReconciliationResultORM,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyMemoryReconciliationReadinessRepository(
    IMemoryReconciliationReadinessRepository
):
    """Read aggregate reconciliation metrics from indexed SQL read models.

    The read-only probes remain together because they produce one operational
    readiness snapshot and never mutate reconciliation state.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(self) -> MemoryReconciliationStoreDiagnostics:
        """Return one read-only aggregate persistence snapshot.

        Returns:
            MemoryReconciliationStoreDiagnostics: Operation result.
        """
        total_plans = await self._count_plans()
        pending_review_plans = await self._count_review_plans()
        total_results = await self._count_results()
        partial_apply_results = await self._count_results_by_status(
            MemoryReconciliationStatus.PARTIAL_APPLY
        )
        failed_results = await self._count_results_by_status(
            MemoryReconciliationStatus.FAILED
        )
        open_conflicts = await self._count_conflicts(MemoryConflictStatus.OPEN)
        reviewing_conflicts = await self._count_conflicts(
            MemoryConflictStatus.REVIEWING
        )
        temporal_state_count = await self._count_temporal_states()
        hard_delete_results = await self._count_hard_delete_results()
        latest_failure = await self._latest_failure()
        return MemoryReconciliationStoreDiagnostics(
            reachable=True,
            total_plans=total_plans,
            pending_review_plans=pending_review_plans,
            total_results=total_results,
            partial_apply_results=partial_apply_results,
            failed_results=failed_results,
            open_conflicts=open_conflicts,
            reviewing_conflicts=reviewing_conflicts,
            temporal_state_count=temporal_state_count,
            hard_delete_results=hard_delete_results,
            latest_failure_code=(
                None if latest_failure is None else latest_failure.failure_code
            ),
            latest_failure_at=(
                None if latest_failure is None else latest_failure.completed_at
            ),
        )

    async def _count_plans(self) -> int:
        value = await self._session.scalar(
            select(func.count()).select_from(MemoryReconciliationPlanORM)
        )
        return int(value or 0)

    async def _count_review_plans(self) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(MemoryReconciliationPlanORM)
            .where(MemoryReconciliationPlanORM.requires_review.is_(True))
        )
        return int(value or 0)

    async def _count_results(self) -> int:
        value = await self._session.scalar(
            select(func.count()).select_from(MemoryReconciliationResultORM)
        )
        return int(value or 0)

    async def _count_results_by_status(
        self,
        status: MemoryReconciliationStatus,
    ) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(MemoryReconciliationResultORM)
            .where(MemoryReconciliationResultORM.status == status.value)
        )
        return int(value or 0)

    async def _count_conflicts(self, status: MemoryConflictStatus) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(MemoryConflictSetORM)
            .where(MemoryConflictSetORM.status == status.value)
        )
        return int(value or 0)

    async def _count_temporal_states(self) -> int:
        value = await self._session.scalar(
            select(func.count()).select_from(ContextTemporalStateORM)
        )
        return int(value or 0)

    async def _count_hard_delete_results(self) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(MemoryReconciliationResultORM)
            .where(MemoryReconciliationResultORM.hard_delete_performed.is_(True))
        )
        return int(value or 0)

    async def _latest_failure(self) -> MemoryReconciliationResultORM | None:
        return await self._session.scalar(
            select(MemoryReconciliationResultORM)
            .where(
                MemoryReconciliationResultORM.status.in_(
                    (
                        MemoryReconciliationStatus.PARTIAL_APPLY.value,
                        MemoryReconciliationStatus.FAILED.value,
                    )
                )
            )
            .order_by(MemoryReconciliationResultORM.completed_at.desc())
            .limit(1)
        )
