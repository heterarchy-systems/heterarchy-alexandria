"""Optional cache boundary for operational readiness snapshots."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)


class OperationalReadinessCache(ABC):
    """Fail-open cache contract for short-lived readiness snapshots."""

    @abstractmethod
    async def get(self) -> OperationalReadinessSnapshot | None:
        """Return the cached snapshot.

        Returns:
            Cached snapshot, or None on a miss or cache failure.
        """

    @abstractmethod
    async def set(self, snapshot: OperationalReadinessSnapshot) -> None:
        """Store one snapshot without propagating cache failures.

        Args:
            snapshot: Fresh authoritative readiness snapshot.
        """


class NoopOperationalReadinessCache(OperationalReadinessCache):
    """Disabled cache implementation that preserves uncached behavior."""

    async def get(self) -> None:
        """Always report a cache miss."""
        return None

    async def set(self, snapshot: OperationalReadinessSnapshot) -> None:
        """Discard the snapshot while preserving the cache contract.

        Args:
            snapshot: Snapshot intentionally ignored by the disabled cache.
        """
        del snapshot
