"""Redis Streams maintenance job submission and status routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.container import ApplicationContainer
from app.operations.application.maintenance_batch_note_write_service import (
    MaintenanceBatchNoteWriteService,
    MaintenanceBatchWritePayloadTooLargeError,
)
from app.operations.application.maintenance_job_queue import (
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import MaintenanceJobRequest
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobKind
from app.operations.interface.routers.maintenance.dependencies import (
    _required_submitter,
)
from app.operations.interface.schemas.operations.maintenance.job_schema import (
    BatchNoteWriteJobRequest,
    EmbeddingReindexJobRequest,
    MaintenanceJobResponse,
    MaintenanceJobsRequest,
    MaintenanceJobsResponse,
    MaintenanceQueueStatusResponse,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/operations/maintenance", tags=["operations"])


@router.post("/jobs/batch-status", response_model=MaintenanceJobsResponse)
@inject
async def get_maintenance_jobs(
    request: Annotated[
        MaintenanceJobsRequest,
        Depends(model_validate_json_body(MaintenanceJobsRequest)),
    ],
    submitter: Annotated[
        MaintenanceJobSubmitter | None,
        Depends(Provide[ApplicationContainer.maintenance_job_submitter]),
    ],
) -> MaintenanceJobsResponse:
    """Read bounded batch progress through the existing queue authority.

    Args:
        request: Existing job identifiers to inspect.
        submitter: Injected maintenance status reader.

    Returns:
        Known snapshots and explicit absent identities.
    """
    queue = _required_submitter(submitter)
    try:
        snapshots = await queue.get_many(tuple(request.job_ids))
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(503, "Redis maintenance queue is unavailable") from exc
    return MaintenanceJobsResponse(
        jobs=[
            MaintenanceJobResponse.from_entity(item)
            for item in snapshots
            if item is not None
        ],
        missing_job_ids=[
            job_id
            for job_id, item in zip(request.job_ids, snapshots, strict=True)
            if item is None
        ],
    )


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


@router.post(
    "/batch-note-write/jobs",
    response_model=MaintenanceJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an asynchronous batch note write",
    description=(
        "Stage bounded note write operations durably and enqueue one job. "
        "The worker executes per-item CAS writes; poll the returned job id "
        "for per-item outcomes."
    ),
)
@inject
async def submit_batch_note_write_job(
    request: Annotated[
        BatchNoteWriteJobRequest,
        Depends(model_validate_json_body(BatchNoteWriteJobRequest)),
    ],
    service: Annotated[
        MaintenanceBatchNoteWriteService,
        Depends(Provide[ApplicationContainer.maintenance_batch_note_write_service]),
    ],
) -> MaintenanceJobResponse:
    """Queue one bounded asynchronous batch note write.

    Args:
        request: Validated HTTP batch write job request.
        service: Async batch note write submission service.

    Returns:
        Operator-visible queued maintenance job response.
    """
    try:
        snapshot = await service.submit(
            operations=request.operations,
            requested_by=request.requested_by,
        )
    except MaintenanceBatchWritePayloadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
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
