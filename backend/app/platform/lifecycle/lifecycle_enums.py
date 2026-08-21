"""Feature-owned lifecycle enums."""

from __future__ import annotations

from enum import StrEnum


class LifecycleStatus(StrEnum):
    """Lifecycle status values for the service."""

    STARTING = "starting"
    RUNNING = "running"
    DRAINING = "draining"
    STOPPING = "stopping"
