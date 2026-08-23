"""SQL-backed Context lifecycle and access-audit mutation store."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.contracts.context_contracts import ContextAccessCreate
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.infrastructure.repositories.contexts.records.access_events import (
    record_context_access,
)
from app.memory.infrastructure.repositories.contexts.records.context_record_query_store import (
    require_context,
)
from app.memory.infrastructure.repositories.contexts.records.deletion import (
    delete_context_rows,
)
from app.memory.infrastructure.repositories.contexts.records.mapping import (
    map_context_row,
)


class ContextRecordMutationStore:
    """Archive, delete, and record access for SQL-backed Context records."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the mutation store.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def archive(self, context_id: str) -> ContextRecord:
        """Archive one Context record.

        Args:
            context_id: Context identifier.

        Returns:
            Archived Context record.
        """
        model = await require_context(self._session, context_id)
        archived_at = datetime.now(UTC)
        model.is_archived = True
        model.archived_at = archived_at
        model.updated_at = archived_at
        await self._session.flush()
        return map_context_row(model)

    async def delete(self, context_id: str) -> None:
        """Hard delete one Context record and dependent rows.

        Args:
            context_id: Context identifier.
        """
        model = await require_context(self._session, context_id)
        await delete_context_rows(
            session=self._session,
            context_id=context_id,
            model=model,
        )

    async def record_access(self, payload: ContextAccessCreate) -> ContextRecord:
        """Persist one access event and update last-access metadata.

        Args:
            payload: Context access event contract.

        Returns:
            Updated Context record.
        """
        model = await require_context(self._session, payload.context_id)
        return await record_context_access(
            session=self._session,
            model=model,
            payload=payload,
        )
