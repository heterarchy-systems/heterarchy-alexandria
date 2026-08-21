"""Redis Streams maintenance job submission and status routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.container import ApplicationContainer
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import MaintenanceJobRequest
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobKind
from app.operations.interface.schemas.operations.maintenance_job_schema import (
    EmbeddingReindexJobRequest,
    MaintenanceJobResponse,
    MaintenanceQueueStatusResponse,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/operations/maintenance", tags=["operations"])


@router.post(
    "/embedding-reindex/jobs",
    response_model=MaintenanceJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an embedding reindex job",
    description=(
        "Submit a deduplicated Redis Streams job. The separate bounded worker "
        "performs CPU-heavy embedding inference; PostgreSQL advisory locks remain "
        "the final maintenance correctness boundary."
    ),
)
@inject
async def enqueue_embedding_reindex_job(
    request: Annotated[
        EmbeddingReindexJobRequest,
        Depends(model_validate_json_body(EmbeddingReindexJobRequest)),
    ],
    response: Response,
    submitter: Annotated[
        MaintenanceJobSubmitter | None,
        Depends(Provide[ApplicationContainer.maintenance_job_submitter]),
    ],
) -> MaintenanceJobResponse:
    """Queue one bounded embedding reindex operation.

    Args:
        request: Validated HTTP maintenance job request.
        response: FastAPI response used to publish queue metadata headers.
        submitter: Injected maintenance queue submission port.

    Returns:
        Operator-visible queued or deduplicated maintenance job response.
    """
    queue = _required_submitter(submitter)
    try:
        snapshot = await queue.enqueue(
            MaintenanceJobRequest(
                kind=MaintenanceJobKind.EMBEDDING_REINDEX,
                requested_by=request.requested_by,
                source_id=request.source_id,
                limit=request.limit,
                force=request.force,
            )
        )
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
    if snapshot.deduplicated:
        response.headers["X-Alexandria-Deduplicated"] = "true"
    return MaintenanceJobResponse.from_entity(snapshot)


@router.get(
    "/jobs/{job_id}",
    response_model=MaintenanceJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a maintenance job",
)
@inject
async def get_maintenance_job(
    job_id: str,
    submitter: Annotated[
        MaintenanceJobSubmitter | None,
        Depends(Provide[ApplicationContainer.maintenance_job_submitter]),
    ],
) -> MaintenanceJobResponse:
    """Return one maintenance job snapshot.

    Args:
        job_id: Maintenance job identifier from queue submission.
        submitter: Injected maintenance queue query port.

    Returns:
        Operator-visible maintenance job lifecycle response.
    """
    queue = _required_submitter(submitter)
    try:
        snapshot = await queue.get(job_id)
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis maintenance queue is unavailable",
        ) from exc
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance job was not found",
        )
    return MaintenanceJobResponse.from_entity(snapshot)


@router.get(
    "/queue/status",
    response_model=MaintenanceQueueStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get maintenance queue status",
)
@inject
async def get_maintenance_queue_status(
    submitter: Annotated[
        MaintenanceJobSubmitter | None,
        Depends(Provide[ApplicationContainer.maintenance_job_submitter]),
    ],
) -> MaintenanceQueueStatusResponse:
    """Return aggregate Redis Streams backlog and worker evidence.

    Args:
        submitter: Injected maintenance queue query port.

    Returns:
        Operator-visible aggregate queue status response.
    """
    queue = _required_submitter(submitter)
    try:
        snapshot = await queue.queue_status()
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis maintenance queue is unavailable",
        ) from exc
    return MaintenanceQueueStatusResponse.from_entity(snapshot)


def _required_submitter(
    submitter: MaintenanceJobSubmitter | None,
) -> MaintenanceJobSubmitter:
    if submitter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis maintenance queue is disabled",
        )
    return submitter
