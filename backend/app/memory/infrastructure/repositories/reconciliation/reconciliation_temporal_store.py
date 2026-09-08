"""Focused SQL store for Context temporal reconciliation overlays."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.entities.memory_reconciliation import MemoryTemporalState
from app.memory.infrastructure.models.reconciliation_models import (
    ContextTemporalStateORM,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_mapping import (
    temporal_from_row,
)
from app.memory.infrastructure.repositories.reconciliation.reconciliation_payload_mapper import (
    temporal_payload,
)
from app.shared.types.types_convert_utils import now_utc


class ReconciliationTemporalStore:
    """Persist and read temporal overlays by Context identifier."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize ReconciliationTemporalStore state and dependencies.

        Args:
            session: Active session used by this operation.
        """
        self._session = session

    async def upsert(self, state: MemoryTemporalState) -> MemoryTemporalState:
        """Insert or replace the temporal overlay for one Context.

        Args:
            state: State.

        Returns:
            MemoryTemporalState: Operation result.
        """
        row = await self._session.get(ContextTemporalStateORM, state.context_id)
        if row is None:
            row = ContextTemporalStateORM(
                context_id=state.context_id,
                recorded_at=state.recorded_at,
                observed_at=state.observed_at,
                valid_from=state.valid_from,
                valid_to=state.valid_to,
                is_current=state.is_current,
                payload=temporal_payload(state),
                updated_at=now_utc(),
            )
            self._session.add(row)
        else:
            row.recorded_at = state.recorded_at
            row.observed_at = state.observed_at
            row.valid_from = state.valid_from
            row.valid_to = state.valid_to
            row.is_current = state.is_current
            row.payload = temporal_payload(state)
            row.updated_at = now_utc()
        await self._session.flush()
        return temporal_from_row(row)

    async def get(self, context_id: str) -> MemoryTemporalState | None:
        """Return the temporal overlay for one Context.

        Args:
            context_id: Context id.

        Returns:
            MemoryTemporalState | None: Operation result.
        """
        row = await self._session.get(ContextTemporalStateORM, context_id)
        return None if row is None else temporal_from_row(row)

    async def get_many(
        self,
        context_ids: tuple[str, ...],
    ) -> dict[str, MemoryTemporalState]:
        """Return bounded overlays with one PostgreSQL ``IN`` query."""
        if not context_ids:
            return {}
        statement = select(ContextTemporalStateORM).where(
            ContextTemporalStateORM.context_id.in_(context_ids)
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        return {row.context_id: temporal_from_row(row) for row in rows}
