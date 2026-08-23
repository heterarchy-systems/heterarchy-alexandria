"""Application service for explicit memory conflict review and resolution."""

from __future__ import annotations

from dataclasses import replace

from app.memory.domain.entities.memory_reconciliation import MemoryConflictSet
from app.memory.domain.event_enum.reconciliation_enums import MemoryConflictStatus
from app.memory.domain.repositories.reconciliation.memory_reconciliation_conflict_repository import (
    IMemoryReconciliationConflictRepository,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)
from app.shared.types.types_convert_utils import now_utc

_RESOLVED_STATUSES = {
    MemoryConflictStatus.RESOLVED_KEEP_BOTH,
    MemoryConflictStatus.RESOLVED_SUPERSEDED,
    MemoryConflictStatus.RESOLVED_MERGED,
    MemoryConflictStatus.RESOLVED_INVALID_SOURCE,
}


class MemoryConflictService:
    """List, inspect, review, and explicitly resolve durable conflict sets."""

    def __init__(self, repository: IMemoryReconciliationConflictRepository) -> None:
        """Initialize MemoryConflictService state and dependencies.

        Args:
            repository: Repository used by this operation.
        """
        self._repository = repository

    async def list(
        self,
        status: MemoryConflictStatus | None = None,
        limit: int = 100,
    ) -> list[MemoryConflictSet]:
        """List conflict sets newest first.

        Args:
            status: Status.
            limit: Limit.

        Returns:
            list[MemoryConflictSet]: Operation result.
        """
        if limit < 1 or limit > 1000:
            raise MemoryContextValidationError(
                "memory conflict limit must be between 1 and 1000"
            )
        return await self._repository.list_conflicts(status=status, limit=limit)

    async def get(self, conflict_set_id: str) -> MemoryConflictSet:
        """Return one durable conflict set or fail explicitly.

        Args:
            conflict_set_id: Conflict set id.

        Returns:
            MemoryConflictSet: Operation result.
        """
        conflict = await self._repository.get_conflict(conflict_set_id)
        if conflict is None:
            raise MemoryContextNotFoundError(
                f"Memory conflict not found: {conflict_set_id}"
            )
        return conflict

    async def mark_reviewing(self, conflict_set_id: str) -> MemoryConflictSet:
        """Mark one open conflict as actively under review.

        Args:
            conflict_set_id: Conflict set id.

        Returns:
            MemoryConflictSet: Operation result.
        """
        conflict = await self.get(conflict_set_id)
        if conflict.status not in {
            MemoryConflictStatus.OPEN,
            MemoryConflictStatus.REVIEWING,
        }:
            raise MemoryContextValidationError(
                "resolved memory conflicts cannot return to REVIEWING"
            )
        return await self._repository.upsert_conflict(
            replace(conflict, status=MemoryConflictStatus.REVIEWING)
        )

    async def resolve(
        self,
        conflict_set_id: str,
        status: MemoryConflictStatus,
        resolution: str,
    ) -> MemoryConflictSet:
        """Record an explicit final conflict resolution without deleting either memory.

        Args:
            conflict_set_id: Conflict set id.
            status: Status.
            resolution: Resolution.

        Returns:
            MemoryConflictSet: Operation result.
        """
        if status not in _RESOLVED_STATUSES:
            raise MemoryContextValidationError(
                "memory conflict resolution requires a RESOLVED_* status"
            )
        normalized_resolution = resolution.strip()
        if not normalized_resolution:
            raise MemoryContextValidationError(
                "memory conflict resolution explanation is required"
            )
        conflict = await self.get(conflict_set_id)
        return await self._repository.upsert_conflict(
            replace(
                conflict,
                status=status,
                resolution=normalized_resolution,
                resolved_at=now_utc(),
            )
        )
