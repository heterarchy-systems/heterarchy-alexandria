"""Redis Streams maintenance job submission and status routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.container import ApplicationContainer
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
)
from app.operations.interface.routers.maintenance.dependencies import (
    _required_submitter,
)
from app.operations.interface.schemas.operations.maintenance.dead_letter_inspection_schema import (
    MaintenanceDeadLetterListResponse,
    MaintenanceDeadLetterPurgeResponse,
    MaintenanceDeadLetterResponse,
)

router = APIRouter(prefix="/operations/maintenance", tags=["operations"])


@router.get(
    "/dead-letters",
    response_model=MaintenanceDeadLetterListResponse,
    status_code=status.HTTP_200_OK,
    summary="List dead-letter maintenance jobs",
    description=(
        "Read the newest terminal job failures recorded by the bounded "
        "maintenance worker without mutating the dead-letter stream."
    ),
)
@inject
async def list_maintenance_dead_letters(
    submitter: Annotated[
        MaintenanceJobSubmitter | None,
        Depends(Provide[ApplicationContainer.maintenance_job_submitter]),
    ],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MaintenanceDeadLetterListResponse:
    """Return the newest dead-letter entries.

    Args:
        submitter: Injected maintenance queue query port.
        limit: Maximum number of entries to return.

    Returns:
        Operator-visible bounded dead-letter listing response.
    """
    queue = _required_submitter(submitter)
    try:
        entries = await queue.list_dead_letters(limit)
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis maintenance queue is unavailable",
        ) from exc
    return MaintenanceDeadLetterListResponse(
        entries=tuple(
            MaintenanceDeadLetterResponse.from_entity(entry) for entry in entries
        )
    )


@router.delete(
    "/dead-letters",
    response_model=MaintenanceDeadLetterPurgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Administrative bulk retention purge of dead-letter jobs",
    description="Explicitly delete all live DLQ entries; normal cleanup uses inspect/retry/reconcile/retire.",
)
@inject
async def purge_maintenance_dead_letters(
    submitter: Annotated[
        MaintenanceJobSubmitter | None,
        Depends(Provide[ApplicationContainer.maintenance_job_submitter]),
    ],
) -> MaintenanceDeadLetterPurgeResponse:
    """Perform an explicit administrative bulk retention purge.

    Args:
        submitter: Injected maintenance queue query port.

    Returns:
        Count of dead-letter entries removed by the purge.
    """
    queue = _required_submitter(submitter)
    try:
        purged = await queue.purge_dead_letters()
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis maintenance queue is unavailable",
        ) from exc
    return MaintenanceDeadLetterPurgeResponse(purged=purged)
