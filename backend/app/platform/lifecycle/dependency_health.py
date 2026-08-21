"""Dependency health status policy for platform lifecycle state."""

from __future__ import annotations

from app.platform.lifecycle.dependency_health_enums import (
    DependencyHealthStatus,
)


def dependency_is_ready(status: DependencyHealthStatus) -> bool:
    """Check if a dependency status permits readiness.

    Args:
        status: Dependency health status to evaluate.

    Returns:
        Whether the status allows the service to be ready.
    """
    ready = status in {
        DependencyHealthStatus.DISABLED,
        DependencyHealthStatus.OK,
    }
    return ready


def dependency_status_when_lifecycle_drains(
    status: DependencyHealthStatus,
) -> DependencyHealthStatus:
    """Return dependency status after lifecycle drain begins.

    Args:
        status: Current dependency health status.

    Returns:
        Draining status for healthy dependencies, otherwise the original status.
    """
    if status is DependencyHealthStatus.OK:
        drained_status = DependencyHealthStatus.DRAINING
    else:
        drained_status = status
    return drained_status


def dependency_status_when_marked_healthy(
    lifecycle_accepts_traffic: bool,
) -> DependencyHealthStatus:
    """Return dependency status when a dependency reports healthy.

    Args:
        lifecycle_accepts_traffic: Whether lifecycle state may accept traffic.

    Returns:
        ``ok`` during traffic-accepting lifecycle states; ``draining`` otherwise.
    """
    if lifecycle_accepts_traffic:
        healthy_status = DependencyHealthStatus.OK
    else:
        healthy_status = DependencyHealthStatus.DRAINING
    return healthy_status
