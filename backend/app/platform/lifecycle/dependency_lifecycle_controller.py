"""Lifecycle-aware dependency transition controller."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock

from app.platform.lifecycle.dependency_health_enums import PlatformDependency
from app.platform.lifecycle.dependency_status_store import DependencyStatusStore


class DependencyLifecycleController:
    """Apply dependency transitions under the owning lifecycle lock."""

    def __init__(
        self,
        store: DependencyStatusStore,
        lock: Lock,
        lifecycle_accepts_traffic: Callable[[], bool],
    ) -> None:
        """Create the dependency transition controller.

        Args:
            store: Mutable dependency status store.
            lock: Owning lifecycle synchronization lock.
            lifecycle_accepts_traffic: Current lifecycle traffic policy callback.
        """
        self._store = store
        self._lock = lock
        self._lifecycle_accepts_traffic = lifecycle_accepts_traffic

    def mark_starting(self, dependency: PlatformDependency) -> None:
        """Set one dependency to starting.

        Args:
            dependency: Dependency to update.
        """
        with self._lock:
            self._store.mark_starting(dependency)

    def mark_healthy(self, dependency: PlatformDependency) -> None:
        """Set one dependency from a healthy report.

        Args:
            dependency: Dependency to update.
        """
        with self._lock:
            self._store.mark_healthy(
                dependency,
                lifecycle_accepts_traffic=self._lifecycle_accepts_traffic(),
            )

    def mark_unavailable(self, dependency: PlatformDependency) -> None:
        """Set one dependency to unavailable.

        Args:
            dependency: Dependency to update.
        """
        with self._lock:
            self._store.mark_unavailable(dependency)

    def mark_draining(self, dependency: PlatformDependency) -> None:
        """Move one healthy dependency to draining.

        Args:
            dependency: Dependency to update.
        """
        with self._lock:
            self._store.mark_draining(dependency)

    def mark_disabled(self, dependency: PlatformDependency) -> None:
        """Set one dependency to disabled.

        Args:
            dependency: Dependency to update.
        """
        with self._lock:
            self._store.mark_disabled(dependency)
