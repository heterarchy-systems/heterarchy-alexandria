"""SQLAlchemy persistence for the latest Context projection integrity snapshot."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegrityFailure,
    ContextProjectionIntegritySnapshot,
)
from app.memory.domain.repositories.projection_integrity.context_projection_integrity_repository import (
    IContextProjectionIntegrityRepository,
)
from app.memory.infrastructure.models.context_models import (
    ContextProjectionIntegritySnapshotORM,
)

_SINGLETON_ID = 1


class ContextProjectionIntegrityStore(IContextProjectionIntegrityRepository):
    """Persist one rebuildable operational snapshot in PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the projection-integrity store.

        Args:
            session: Active transaction-scoped async session.
        """
        self._session = session

    async def get_latest(self) -> ContextProjectionIntegritySnapshot | None:
        """Return the latest persisted projection-integrity snapshot when present.

        Returns:
            Reconstructed latest snapshot, or None when the singleton row is absent.
        """
        model = await self._session.get(
            ContextProjectionIntegritySnapshotORM, _SINGLETON_ID
        )
        if model is None:
            return None
        failures = tuple(
            ContextProjectionIntegrityFailure(code=code, count=count)
            for code, count in sorted(model.failure_counts.items())
        )
        return ContextProjectionIntegritySnapshot(
            checked=True,
            available=True,
            source_revision=model.source_revision,
            current_source_revision=model.source_revision,
            scanned_count=model.scanned_count,
            valid_count=model.valid_count,
            invalid_count=model.invalid_count,
            failures=failures,
            checked_at=model.checked_at,
            stale=False,
        )

    async def replace_latest(
        self, snapshot: ContextProjectionIntegritySnapshot
    ) -> None:
        """Replace the singleton projection-integrity snapshot atomically.

        Args:
            snapshot: Complete projection-integrity snapshot to store.
        """
        if snapshot.source_revision is None or snapshot.checked_at is None:
            raise ValueError(
                "PROJECTION_INTEGRITY_SNAPSHOT_INVALID: source revision and checked_at required"
            )
        failure_counts = {failure.code: failure.count for failure in snapshot.failures}
        model = await self._session.get(
            ContextProjectionIntegritySnapshotORM, _SINGLETON_ID
        )
        if model is None:
            model = ContextProjectionIntegritySnapshotORM(singleton_id=_SINGLETON_ID)
            self._session.add(model)
        model.source_revision = snapshot.source_revision
        model.scanned_count = snapshot.scanned_count
        model.valid_count = snapshot.valid_count
        model.invalid_count = snapshot.invalid_count
        model.failure_counts = failure_counts
        model.checked_at = snapshot.checked_at
        await self._session.flush()
