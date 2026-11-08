"""Redis Streams maintenance job submission and status routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.container import ApplicationContainer
from app.operations.application.maintenance_job_queue import (
    MaintenanceDeadLetterNotFoundError,
    MaintenanceDeadLetterSourceGoneError,
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.interface.routers.maintenance.dependencies import (
    _required_submitter,
)
from app.operations.interface.schemas.operations.maintenance.job_schema import (
    MaintenanceJobResponse,
)

router = APIRouter(prefix="/operations/maintenance", tags=["operations"])


@router.post(
    "/dead-letters/{entry_id}/replay",
    response_model=MaintenanceJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Replay one dead-letter maintenance job",
    description=(
        "Re-enqueue the original request behind one dead-letter entry as a "
        "fresh job with a new identity and deduplication window."
    ),
)
@inject
async def replay_maintenance_dead_letter(
    entry_id: str,
    submitter: Annotated[
        MaintenanceJobSubmitter | None,
        Depends(Provide[ApplicationContainer.maintenance_job_submitter]),
    ],
) -> MaintenanceJobResponse:
    """Replay one dead-letter entry as a fresh maintenance job.

    Args:
        entry_id: Dead-letter stream entry identifier to replay.
        submitter: Injected maintenance queue submission port.

    Returns:
        Freshly queued replacement maintenance job response.
    """
    queue = _required_submitter(submitter)
    try:
        snapshot = await queue.replay_dead_letter(entry_id)
    except MaintenanceDeadLetterNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead-letter entry was not found",
        ) from exc
    except MaintenanceDeadLetterSourceGoneError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dead-letter source entry is no longer available for replay",
        ) from exc
    except MaintenanceSubmissionRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maintenance submission rate limit exceeded",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis maintenance queue is unavailable",
        ) from exc
    return MaintenanceJobResponse.from_entity(snapshot)
