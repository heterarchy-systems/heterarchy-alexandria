"""Focused SQL store for reconciliation execution results."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationResult
from app.memory.infrastructure.models.reconciliation_models import (
    MemoryReconciliationResultORM,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_mapping import (
    result_from_row,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_payload_mapper import (
    result_payload,
)


class ReconciliationResultStore:
    """Persist and query the latest execution result for each plan."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize ReconciliationResultStore state and dependencies.

        Args:
            session: Active session used by this operation.
        """
        self._session = session

    async def save_result(
        self,
        result: MemoryReconciliationResult,
    ) -> MemoryReconciliationResult:
        """Insert or replace the single result for one plan.

        Args:
            result: Result.

        Returns:
            MemoryReconciliationResult: Operation result.
        """
        row = await self._session.scalar(
            select(MemoryReconciliationResultORM).where(
                MemoryReconciliationResultORM.plan_id == result.plan_id
            )
        )
        if row is None:
            row = MemoryReconciliationResultORM(
                id=result.reconciliation_id,
                plan_id=result.plan_id,
                status=result.status.value,
                failure_code=(
                    None if result.failure_code is None else result.failure_code.value
                ),
                hard_delete_performed=result.hard_delete_performed,
                payload=result_payload(result),
                completed_at=result.completed_at,
            )
            self._session.add(row)
        else:
            row.status = result.status.value
            row.failure_code = (
                None if result.failure_code is None else result.failure_code.value
            )
            row.hard_delete_performed = result.hard_delete_performed
            row.payload = result_payload(result)
            row.completed_at = result.completed_at
        await self._session.flush()
        return result_from_row(row)

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
        row = await self._session.get(
            MemoryReconciliationResultORM,
            reconciliation_id,
        )
        return None if row is None else result_from_row(row)

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
        row = await self._session.scalar(
            select(MemoryReconciliationResultORM).where(
                MemoryReconciliationResultORM.plan_id == plan_id
            )
        )
        return None if row is None else result_from_row(row)
