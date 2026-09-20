"""Memory Steward composed verification status values."""

from __future__ import annotations

from enum import StrEnum


class MemoryStewardStatus(StrEnum):
    """Overall status emitted by Memory Steward diagnose and seal workflows."""

    READY = "READY"
    READY_WITH_RESIDUALS = "READY_WITH_RESIDUALS"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"
    FAILED = "FAILED"
