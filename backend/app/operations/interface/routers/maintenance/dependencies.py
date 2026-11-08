"""Redis Streams maintenance job submission and status routes."""

from fastapi import HTTPException, status

from app.operations.application.maintenance_dlq_service import (
    MaintenanceDeadLetterLifecycleService,
)
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobSubmitter,
)


def _required_submitter(
    submitter: MaintenanceJobSubmitter | None,
) -> MaintenanceJobSubmitter:
    """Execute required submitter.

    Args:
        submitter: Submitter used by this operation.

    Returns:
        MaintenanceJobSubmitter result produced by required submitter.
    """
    if submitter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis maintenance queue is disabled",
        )
    return submitter


def _required_dlq_service(
    service: MaintenanceDeadLetterLifecycleService | None,
) -> MaintenanceDeadLetterLifecycleService:
    """Require the composed DLQ lifecycle application service."""
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Maintenance DLQ lifecycle is disabled",
        )
    return service
