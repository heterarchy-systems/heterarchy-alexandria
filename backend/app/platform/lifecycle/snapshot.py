"""Lifecycle snapshot contract and readiness helper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.platform.lifecycle.dependency_health import dependency_is_ready
from app.platform.lifecycle.dependency_health_enums import DependencyHealthStatus
from app.platform.lifecycle.dependency_status_store import DependencyStatusStore
from app.platform.lifecycle.lifecycle_enums import LifecycleStatus


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    """Read-only snapshot of lifecycle state."""

    status: LifecycleStatus
    redis_status: DependencyHealthStatus
    database_status: DependencyHealthStatus
    started_at: datetime
    drain_started_at: datetime | None
    drain_reason: str | None

    @property
    def draining(self) -> bool:
        """Whether the lifecycle state is currently ``draining``.

        Args:
            None.

        Returns:
            Return value.
        """
        draining = self.status is LifecycleStatus.DRAINING
        return draining

    @property
    def ready(self) -> bool:
        """Whether the service is ready to accept new traffic.

        Args:
            None.

        Returns:
            Return value.
        """
        ready = lifecycle_is_ready(
            status=self.status,
            dependencies=DependencyStatusStore(
                redis_status=self.redis_status,
                database_status=self.database_status,
            ),
        )
        return ready


def lifecycle_accepts_traffic(status: LifecycleStatus) -> bool:
    """Return whether lifecycle status allows healthy dependency traffic.

    Args:
        status: Current lifecycle status.

    Returns:
        Whether dependency health reports should remain traffic-ready.
    """
    accepts_traffic = status not in {
        LifecycleStatus.DRAINING,
        LifecycleStatus.STOPPING,
    }
    return accepts_traffic


def lifecycle_is_ready(
    status: LifecycleStatus,
    dependencies: DependencyStatusStore,
) -> bool:
    """Return whether lifecycle and dependency state are ready for traffic.

    Args:
        status: Current lifecycle status.
        dependencies: Current dependency status store.

    Returns:
        Whether new traffic can be accepted.
    """
    ready = (
        status is LifecycleStatus.RUNNING
        and dependency_is_ready(dependencies.redis_status)
        and dependency_is_ready(dependencies.database_status)
    )
    return ready
