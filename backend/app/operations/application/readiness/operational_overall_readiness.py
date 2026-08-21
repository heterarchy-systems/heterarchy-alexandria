"""Overall readiness synthesis across service and canonical data integrity."""

from __future__ import annotations

from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.operations.domain.event_enum.operational_data_integrity_enums import (
    OperationalDataIntegrityStatus,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalOverallStatus,
    OperationalReadinessStatus,
)


def overall_readiness_status(
    snapshot: OperationalReadinessSnapshot,
) -> OperationalOverallStatus:
    """Return one unambiguous status without replacing existing readiness fields.

    Args:
        snapshot: Value supplied to overall_readiness_status.

    Returns:
        Result produced by overall_readiness_status.
    """
    if snapshot.status is OperationalReadinessStatus.RECOVERING:
        return OperationalOverallStatus.RECOVERING
    if snapshot.ready:
        if (
            snapshot.warnings
            or snapshot.data_integrity.status
            is not OperationalDataIntegrityStatus.HEALTHY
        ):
            return OperationalOverallStatus.READY_WITH_WARNINGS
        return OperationalOverallStatus.READY
    if snapshot.status in {
        OperationalReadinessStatus.DEGRADED_FTS_ONLY,
        OperationalReadinessStatus.UNKNOWN,
        OperationalReadinessStatus.VERIFYING,
    }:
        return OperationalOverallStatus.DEGRADED
    return OperationalOverallStatus.NOT_READY
