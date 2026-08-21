"""Focused SQL store for first-class memory conflict sets."""

from __future__ import annotations

from app.memory.domain.entities.memory_reconciliation import MemoryConflictSet
from app.memory.domain.event_enum.reconciliation_enums import MemoryConflictStatus
from app.memory.infrastructure.models.reconciliation_models import MemoryConflictSetORM
from app.memory.infrastructure.repositories.reconciliation.reconciliation_mapping import (
    conflict_from_row,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_payload_mapper import (
    conflict_payload,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ReconciliationConflictStore:
    """Persist, resolve, and list memory conflict sets."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, conflict: MemoryConflictSet) -> MemoryConflictSet:
        """Insert or update one conflict by candidate and canonical claim key.

        Args:
            conflict: Conflict.

        Returns:
            MemoryConflictSet: Operation result.
        """
        row = await self._session.scalar(
            select(MemoryConflictSetORM).where(
                MemoryConflictSetORM.candidate_id == conflict.candidate_id,
                MemoryConflictSetORM.claim_key == conflict.claim_key,
            )
        )
        if row is None:
            row = MemoryConflictSetORM(
                id=conflict.conflict_set_id,
                candidate_id=conflict.candidate_id,
                subject_key=conflict.subject_key,
                claim_key=conflict.claim_key,
                scope=conflict.scope.value,
                status=conflict.status.value,
                validity_overlap=conflict.validity_overlap,
                payload=conflict_payload(conflict),
                created_at=conflict.created_at,
                resolved_at=conflict.resolved_at,
            )
            self._session.add(row)
        else:
            row.status = conflict.status.value
            row.validity_overlap = conflict.validity_overlap
            row.payload = conflict_payload(conflict)
            row.resolved_at = conflict.resolved_at
        await self._session.flush()
        return conflict_from_row(row)

    async def get(self, conflict_set_id: str) -> MemoryConflictSet | None:
        """Return one conflict set by identifier.

        Args:
            conflict_set_id: Conflict set id.

        Returns:
            MemoryConflictSet | None: Operation result.
        """
        row = await self._session.get(MemoryConflictSetORM, conflict_set_id)
        return None if row is None else conflict_from_row(row)

    async def list(
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
        statement = select(MemoryConflictSetORM)
        if status is not None:
            statement = statement.where(MemoryConflictSetORM.status == status.value)
        rows = await self._session.scalars(
            statement.order_by(MemoryConflictSetORM.created_at.desc()).limit(limit)
        )
        return [conflict_from_row(row) for row in rows.all()]
