"""In-memory process-local lifecycle state management.

This state is shared only within a single Python process. In uvicorn/gunicorn
multi-worker mode, each worker has its own lifecycle state.

This is currently a bootstrap implementation; when shared DB/Redis infrastructure
is introduced, drain coordination, short-lived failure counters, and lifecycle
event history should be revisited on external shared storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from app.platform.lifecycle.dependency_health_enums import (
    DependencyHealthStatus as DependencyHealthStatus,
)
from app.platform.lifecycle.dependency_lifecycle_controller import (
    DependencyLifecycleController,
)
from app.platform.lifecycle.dependency_status_store import DependencyStatusStore
from app.platform.lifecycle.lifecycle_enums import LifecycleStatus
from app.platform.lifecycle.snapshot import (
    LifecycleSnapshot,
    lifecycle_accepts_traffic,
    lifecycle_is_ready,
)
from app.platform.lifecycle.transitions import (
    apply_drain_transition,
    apply_stopping_transition,
    status_when_marked_running,
)


class LifecycleState:
    """Track process lifecycle and expose focused dependency transitions."""

    def __init__(self, started_at: datetime | None = None) -> None:
        """Initialize lifecycle state.

        Args:
            started_at: Process start timestamp, defaults to current UTC time.
        """
        self._lock = Lock()
        self._started_at = started_at or datetime.now(UTC)
        self._status = LifecycleStatus.STARTING
        self._dependencies = DependencyStatusStore()
        self._dependency_controller = DependencyLifecycleController(
            store=self._dependencies,
            lock=self._lock,
            lifecycle_accepts_traffic=self._lifecycle_accepts_traffic,
        )
        self._drain_started_at: datetime | None = None
        self._drain_reason: str | None = None

    @property
    def dependencies(self) -> DependencyLifecycleController:
        """Return lifecycle-aware dependency transitions.

        Returns:
            Dependency transition controller bound to this state and lock.
        """
        return self._dependency_controller

    def mark_running(self) -> None:
        """Transition state to ``running``.

        This transition is only allowed from ``starting`` or ``stopping``.
        Draining state does not auto-recover.
        """
        with self._lock:
            self._status = status_when_marked_running(self._status)

    def mark_stopping(self) -> None:
        """Transition state to ``stopping``."""
        with self._lock:
            self._status = apply_stopping_transition(self._dependencies)

    def start_draining(self, reason: str, now: datetime | None = None) -> bool:
        """Start draining state.

        Args:
            reason: Initial draining reason.
            now: Draining start timestamp, defaults to current UTC.

        Returns:
            ``True`` if this call initiated draining.
        """
        with self._lock:
            result = apply_drain_transition(
                status=self._status,
                dependencies=self._dependencies,
                reason=reason,
                now=now,
                drain_started_at=self._drain_started_at,
                drain_reason=self._drain_reason,
            )
            self._status = result.status
            self._drain_started_at = result.drain_started_at
            self._drain_reason = result.drain_reason
            return result.started

    def is_ready(self) -> bool:
        """Return whether traffic can be accepted in the current state.

        Returns:
            Whether lifecycle and dependencies are ready.
        """
        with self._lock:
            return lifecycle_is_ready(
                status=self._status,
                dependencies=self._dependencies,
            )

    def snapshot(self) -> LifecycleSnapshot:
        """Return a read-only snapshot of current lifecycle state.

        Returns:
            Current lifecycle snapshot.
        """
        with self._lock:
            return LifecycleSnapshot(
                status=self._status,
                redis_status=self._dependencies.redis_status,
                database_status=self._dependencies.database_status,
                started_at=self._started_at,
                drain_started_at=self._drain_started_at,
                drain_reason=self._drain_reason,
            )

    def _lifecycle_accepts_traffic(self) -> bool:
        return lifecycle_accepts_traffic(self._status)
