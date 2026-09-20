"""Redis Streams maintenance job submission and status routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.container import ApplicationContainer
from app.operations.application.maintenance_job_queue import (
    MaintenanceDeadLetterNotFoundError,
    MaintenanceDeadLetterSourceGoneError,
    MaintenanceJobSubmitter,
    MaintenanceQueueUnavailableError,
    MaintenanceSubmissionRateLimitError,
)
from app.operations.domain.entities.maintenance_job import MaintenanceJobRequest
from app.operations.domain.event_enum.maintenance_job_enums import MaintenanceJobKind
from app.operations.interface.schemas.operations.maintenance_job_schema import (
    EmbeddingReindexJobRequest,
    MaintenanceDeadLetterListResponse,
    MaintenanceDeadLetterPurgeResponse,
    MaintenanceDeadLetterResponse,
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
    summary="Purge dead-letter maintenance jobs",
)
@inject
async def purge_maintenance_dead_letters(
    submitter: Annotated[
        MaintenanceJobSubmitter | None,
        Depends(Provide[ApplicationContainer.maintenance_job_submitter]),
    ],
) -> MaintenanceDeadLetterPurgeResponse:
    """Drop every dead-letter entry after operator review.

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
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis maintenance queue is unavailable",
        ) from exc
    return MaintenanceJobResponse.from_entity(snapshot)
