"""Durable staging store for asynchronous maintenance job payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.infrastructure.maintenance_models import MaintenanceJobPayloadORM
from app.shared.types.extra_types import JSONValue


class MaintenanceJobPayloadStore:
    """Save, load, and delete one durable maintenance job payload."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the store.

        Args:
            session: Request-scoped database session.
        """
        self._session = session

    async def save(
        self,
        payload_id: str,
        kind: str,
        body: dict[str, JSONValue],
    ) -> None:
        """Persist one bounded job payload.

        Args:
            payload_id: Stable identifier also carried as the job source_id.
            kind: Maintenance job kind the payload belongs to.
            body: Bounded JSON operation body executed by the worker.
        """
        self._session.add(
            MaintenanceJobPayloadORM(
                payload_id=payload_id,
                kind=kind,
                body=body,
                created_at=datetime.now(UTC),
            )
        )
        await self._session.flush()
        await self._session.commit()

    async def load(self, payload_id: str) -> dict[str, JSONValue] | None:
        """Load one job payload body by identifier.

        Args:
            payload_id: Stable payload identifier.

        Returns:
            The stored JSON body, or None when the payload is unknown.
        """
        row = await self._session.get(MaintenanceJobPayloadORM, payload_id)
        if row is None:
            return None
        return dict(row.body)

    async def save_if_absent(
        self, payload_id: str, kind: str, body: dict[str, JSONValue]
    ) -> bool:
        """Stage a retry-stable immutable payload without replacing another admission.

        Args:
            payload_id: Stable logical batch identity carried by Redis.
            kind: Existing maintenance job kind.
            body: Exact original operation payload.

        Returns:
            True for new admission; False when its payload already exists.
        """
        inserted = await self._session.scalar(
            insert(MaintenanceJobPayloadORM)
            .values(
                payload_id=payload_id,
                kind=kind,
                body=body,
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(
                index_elements=[MaintenanceJobPayloadORM.payload_id]
            )
            .returning(MaintenanceJobPayloadORM.payload_id)
        )
        await self._session.commit()
        return inserted is not None

    async def delete(self, payload_id: str) -> None:
        """Delete one job payload after successful execution.

        Args:
            payload_id: Stable payload identifier.
        """
        await self._session.execute(
            delete(MaintenanceJobPayloadORM).where(
                MaintenanceJobPayloadORM.payload_id == payload_id
            )
        )
        await self._session.commit()
