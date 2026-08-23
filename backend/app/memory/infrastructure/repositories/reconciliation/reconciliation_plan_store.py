"""Focused SQL store for immutable reconciliation plans."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationPlan
from app.memory.infrastructure.models.reconciliation_models import (
    MemoryReconciliationPlanORM,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_mapping import (
    plan_from_row,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_payload_mapper import (
    plan_payload,
)


class ReconciliationPlanStore:
    """Persist and query immutable reconciliation plans."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize ReconciliationPlanStore state and dependencies.

        Args:
            session: Active session used by this operation.
        """
        self._session = session

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
        existing = await self.get_plan_by_idempotency_key(plan.idempotency_key)
        if existing is not None:
            return existing
        row = MemoryReconciliationPlanORM(
            id=plan.plan_id,
            candidate_id=plan.candidate.candidate_id,
            idempotency_key=plan.idempotency_key,
            primary_decision=plan.primary_decision.value,
            status=plan.status.value,
            requires_review=plan.requires_review,
            payload=plan_payload(plan),
            created_at=plan.created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return plan_from_row(row)

    async def get_plan(self, plan_id: str) -> MemoryReconciliationPlan | None:
        """Return one plan by identifier.

        Args:
            plan_id: Plan id.

        Returns:
            MemoryReconciliationPlan | None: Operation result.
        """
        row = await self._session.get(MemoryReconciliationPlanORM, plan_id)
        return None if row is None else plan_from_row(row)

    async def get_plan_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> MemoryReconciliationPlan | None:
        """Return one plan by its stable idempotency key.

        Args:
            idempotency_key: Idempotency key.

        Returns:
            MemoryReconciliationPlan | None: Operation result.
        """
        row = await self._session.scalar(
            select(MemoryReconciliationPlanORM).where(
                MemoryReconciliationPlanORM.idempotency_key == idempotency_key
            )
        )
        return None if row is None else plan_from_row(row)

    async def list_review_plans(
        self,
        limit: int = 100,
    ) -> list[MemoryReconciliationPlan]:
        """List review-required plans newest first.

        Args:
            limit: Limit.

        Returns:
            list[MemoryReconciliationPlan]: Operation result.
        """
        rows = await self._session.scalars(
            select(MemoryReconciliationPlanORM)
            .where(MemoryReconciliationPlanORM.requires_review.is_(True))
            .order_by(MemoryReconciliationPlanORM.created_at.desc())
            .limit(limit)
        )
        return [plan_from_row(row) for row in rows.all()]
