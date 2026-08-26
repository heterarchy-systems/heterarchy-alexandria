"""Operational readiness status values."""

from __future__ import annotations

from enum import StrEnum


class OperationalReadinessStatus(StrEnum):
    """Operational readiness states for knowledge retrieval safety."""

    UNKNOWN = "UNKNOWN"
    READY = "READY"
    DEGRADED_FTS_ONLY = "DEGRADED_FTS_ONLY"
    DEGRADED_RUNTIME_DRIFT = "DEGRADED_RUNTIME_DRIFT"
    DEGRADED_RETRIEVAL_CANARY = "DEGRADED_RETRIEVAL_CANARY"
    DEGRADED_PROJECTION_INTEGRITY = "DEGRADED_PROJECTION_INTEGRITY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    RECOVERING = "RECOVERING"
    VERIFYING = "VERIFYING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class OperationalOverallStatus(StrEnum):
    """Operator-facing synthesis of service readiness and data integrity."""

    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"
    RECOVERING = "RECOVERING"
