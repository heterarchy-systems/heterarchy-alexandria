"""Focused SQL store for directed memory relations."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.entities.memory_reconciliation import MemoryRelationRecord
from app.memory.infrastructure.models.reconciliation_models import MemoryRelationORM
from app.memory.infrastructure.repositories.reconciliation.reconciliation_mapping import (
    relation_from_row,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_payload_mapper import (
    relation_payload,
)


class ReconciliationRelationStore:
    """Persist and query idempotent directed memory relations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize ReconciliationRelationStore state and dependencies.

        Args:
            session: Active session used by this operation.
        """
        self._session = session

    async def upsert(
        self,
        relation: MemoryRelationRecord,
    ) -> MemoryRelationRecord:
        """Create or return a relation by source, target, and relation type.

        Args:
            relation: Relation.

        Returns:
            MemoryRelationRecord: Operation result.
        """
        row = await self._session.scalar(
            select(MemoryRelationORM).where(
                MemoryRelationORM.source_context_id == relation.source_context_id,
                MemoryRelationORM.target_context_id == relation.target_context_id,
                MemoryRelationORM.relation == relation.relation.value,
            )
        )
        if row is None:
            row = MemoryRelationORM(
                id=relation.relation_id,
                source_context_id=relation.source_context_id,
                target_context_id=relation.target_context_id,
                candidate_id=relation.candidate_id,
                relation=relation.relation.value,
                confidence=relation.confidence,
                reason=relation.reason,
                decision_source=relation.decision_source.value,
                policy_version=relation.policy_version,
                payload=relation_payload(relation),
                created_at=relation.created_at,
            )
            self._session.add(row)
        await self._session.flush()
        return relation_from_row(row)

    async def list_for_context(
        self,
        context_id: str,
    ) -> list[MemoryRelationRecord]:
        """List directed relations where a Context is source or target.

        Args:
            context_id: Context id.

        Returns:
            list[MemoryRelationRecord]: Operation result.
        """
        rows = await self._session.scalars(
            select(MemoryRelationORM)
            .where(
                or_(
                    MemoryRelationORM.source_context_id == context_id,
                    MemoryRelationORM.target_context_id == context_id,
                )
            )
            .order_by(MemoryRelationORM.created_at.desc())
        )
        return [relation_from_row(row) for row in rows.all()]
