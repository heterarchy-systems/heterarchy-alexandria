"""Feature-owned dependency health enums."""

from __future__ import annotations

from enum import StrEnum


class DependencyHealthStatus(StrEnum):
    """Shared dependency health states."""

    DISABLED = "disabled"
    STARTING = "starting"
    OK = "ok"
    DRAINING = "draining"
    UNAVAILABLE = "unavailable"


class PlatformDependency(StrEnum):
    """Platform dependency identifiers managed by lifecycle state."""

    REDIS = "redis"
    DATABASE = "database"
