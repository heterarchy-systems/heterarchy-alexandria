"""Feature-owned operational capability enums."""

from __future__ import annotations

from enum import StrEnum


class OperationalCapabilityState(StrEnum):
    """One capability's independent serving state."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    OPTIONAL = "OPTIONAL"
