"""Transition helpers for platform lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.platform.lifecycle.dependency_status_store import DependencyStatusStore
from app.platform.lifecycle.lifecycle_enums import LifecycleStatus


@dataclass(frozen=True, slots=True)
class DrainTransitionResult:
    """Lifecycle drain transition result."""

    status: LifecycleStatus
    drain_started_at: datetime | None
    drain_reason: str | None
    started: bool


def status_when_marked_running(status: LifecycleStatus) -> LifecycleStatus:
    """Return lifecycle status after a running transition request.

    Args:
        status: Current lifecycle status.

    Returns:
        Updated lifecycle status.
    """
    if status in {LifecycleStatus.STARTING, LifecycleStatus.STOPPING}:
        running_status = LifecycleStatus.RUNNING
    else:
        running_status = status
    return running_status


def apply_stopping_transition(dependencies: DependencyStatusStore) -> LifecycleStatus:
    """Apply stopping side effects and return stopping status.

    Args:
        dependencies: Mutable dependency status store.

    Returns:
        Stopping lifecycle status.
    """
    dependencies.mark_all_draining()
    stopping_status = LifecycleStatus.STOPPING
    return stopping_status


def apply_drain_transition(
    status: LifecycleStatus,
    dependencies: DependencyStatusStore,
    reason: str,
    now: datetime | None,
    drain_started_at: datetime | None,
    drain_reason: str | None,
) -> DrainTransitionResult:
    """Apply drain transition when allowed.

    Args:
        status: Current lifecycle status.
        dependencies: Mutable dependency status store.
        reason: Initial drain reason.
        now: Drain timestamp override.
        drain_started_at: Existing drain timestamp.
        drain_reason: Existing drain reason.

    Returns:
        Drain transition result with updated state and start flag.
    """
    if status in {LifecycleStatus.DRAINING, LifecycleStatus.STOPPING}:
        result = DrainTransitionResult(
            status=status,
            drain_started_at=drain_started_at,
            drain_reason=drain_reason,
            started=False,
        )
        return result

    dependencies.mark_all_draining()
    result = DrainTransitionResult(
        status=LifecycleStatus.DRAINING,
        drain_started_at=now or datetime.now(UTC),
        drain_reason=reason,
        started=True,
    )
    return result
