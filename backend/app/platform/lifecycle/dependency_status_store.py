"""Dependency status store for platform lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass

from app.platform.lifecycle.dependency_health import (
    dependency_status_when_lifecycle_drains,
    dependency_status_when_marked_healthy,
)
from app.platform.lifecycle.dependency_health_enums import (
    DependencyHealthStatus,
    PlatformDependency,
)


@dataclass(slots=True)
class DependencyStatusStore:
    """Mutable lifecycle-owned dependency health status store."""

    redis_status: DependencyHealthStatus = DependencyHealthStatus.DISABLED
    database_status: DependencyHealthStatus = DependencyHealthStatus.DISABLED

    def mark_all_draining(self) -> None:
        """Move all healthy dependencies to draining state."""
        self.redis_status = dependency_status_when_lifecycle_drains(self.redis_status)
        self.database_status = dependency_status_when_lifecycle_drains(
            self.database_status
        )

    def mark_starting(self, dependency: PlatformDependency) -> None:
        """Set one dependency status to starting.

        Args:
            dependency: Dependency to update.
        """
        _set_status(self, dependency, DependencyHealthStatus.STARTING)

    def mark_healthy(
        self,
        dependency: PlatformDependency,
        lifecycle_accepts_traffic: bool,
    ) -> None:
        """Set one dependency status from a healthy report.

        Args:
            dependency: Dependency to update.
            lifecycle_accepts_traffic: Whether lifecycle may accept traffic.
        """
        _set_status(
            self,
            dependency,
            dependency_status_when_marked_healthy(
                lifecycle_accepts_traffic=lifecycle_accepts_traffic
            ),
        )

    def mark_unavailable(self, dependency: PlatformDependency) -> None:
        """Set one dependency status to unavailable.

        Args:
            dependency: Dependency to update.
        """
        _set_status(self, dependency, DependencyHealthStatus.UNAVAILABLE)

    def mark_draining(self, dependency: PlatformDependency) -> None:
        """Move one healthy dependency to draining state.

        Args:
            dependency: Dependency to update.
        """
        _set_status(
            self,
            dependency,
            dependency_status_when_lifecycle_drains(_status_for(self, dependency)),
        )

    def mark_disabled(self, dependency: PlatformDependency) -> None:
        """Set one dependency status to disabled.

        Args:
            dependency: Dependency to update.
        """
        _set_status(self, dependency, DependencyHealthStatus.DISABLED)


def _status_for(
    store: DependencyStatusStore,
    dependency: PlatformDependency,
) -> DependencyHealthStatus:
    """Execute status for.

    Args:
        store: Store used by this operation.
        dependency: Dependency used by this operation.

    Returns:
        DependencyHealthStatus result produced by status for.
    """
    if dependency is PlatformDependency.REDIS:
        return store.redis_status
    return store.database_status


def _set_status(
    store: DependencyStatusStore,
    dependency: PlatformDependency,
    status: DependencyHealthStatus,
) -> None:
    """Execute set status.

    Args:
        store: Store used by this operation.
        dependency: Dependency used by this operation.
        status: Status value used by this operation.
    """
    if dependency is PlatformDependency.REDIS:
        store.redis_status = status
        return
    store.database_status = status
