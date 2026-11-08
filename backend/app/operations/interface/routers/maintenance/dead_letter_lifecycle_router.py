"""Redis Streams maintenance job submission and status routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.container import ApplicationContainer
from app.operations.application.maintenance_dlq_service import (
    MaintenanceDeadLetterLifecycleService,
)
from app.operations.application.maintenance_job_queue import (
    MaintenanceDeadLetterLifecycleConflictError,
    MaintenanceDeadLetterNotFoundError,
    MaintenanceDeadLetterNotRetryableError,
    MaintenanceDeadLetterSourceGoneError,
    MaintenanceQueueUnavailableError,
)
from app.operations.interface.routers.maintenance.dependencies import (
    _required_dlq_service,
)
from app.operations.interface.schemas.operations.maintenance.dead_letter_inspection_schema import (
    MaintenanceDeadLetterInspectionResponse,
)
from app.operations.interface.schemas.operations.maintenance.dead_letter_lifecycle_schema import (
    MaintenanceDeadLetterReconcileResponse,
    MaintenanceDeadLetterRetireRequest,
    MaintenanceDeadLetterRetireResponse,
    MaintenanceDeadLetterRetryRequest,
    MaintenanceDeadLetterRetryResponse,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/operations/maintenance", tags=["operations"])


@router.get(
    "/dead-letters/{entry_id}",
    response_model=MaintenanceDeadLetterInspectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect one maintenance dead-letter entry",
)
@router.get(
    "/dead-letters/{entry_id}/inspect",
    response_model=MaintenanceDeadLetterInspectionResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
@inject
async def inspect_maintenance_dead_letter(
    entry_id: str,
    service: Annotated[
        MaintenanceDeadLetterLifecycleService | None,
        Depends(Provide[ApplicationContainer.maintenance_dlq_service]),
    ],
) -> MaintenanceDeadLetterInspectionResponse:
    """Inspect exact live or archived dead-letter evidence."""
    lifecycle = _required_dlq_service(service)
    try:
        result = await lifecycle.inspect(entry_id)
    except MaintenanceDeadLetterNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Dead-letter entry was not found"
        ) from exc
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Redis maintenance queue is unavailable",
        ) from exc
    return MaintenanceDeadLetterInspectionResponse.from_entity(result)


@router.post(
    "/dead-letters/{entry_id}/retry",
    response_model=MaintenanceDeadLetterRetryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry one maintenance dead-letter entry",
)
@inject
async def retry_maintenance_dead_letter(
    entry_id: str,
    request: Annotated[
        MaintenanceDeadLetterRetryRequest,
        Depends(model_validate_json_body(MaintenanceDeadLetterRetryRequest)),
    ],
    service: Annotated[
        MaintenanceDeadLetterLifecycleService | None,
        Depends(Provide[ApplicationContainer.maintenance_dlq_service]),
    ],
) -> MaintenanceDeadLetterRetryResponse:
    """Preview or same-ID retry one evidence-approved terminal job."""
    lifecycle = _required_dlq_service(service)
    try:
        result = await lifecycle.retry(
            entry_id,
            dry_run=request.dry_run,
            reason=request.reason,
        )
    except MaintenanceDeadLetterNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Dead-letter entry was not found"
        ) from exc
    except MaintenanceDeadLetterNotRetryableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MaintenanceDeadLetterSourceGoneError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MaintenanceDeadLetterLifecycleConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Redis maintenance queue is unavailable",
        ) from exc
    return MaintenanceDeadLetterRetryResponse.from_entity(result)


@router.post(
    "/dead-letters/{entry_id}/reconcile",
    response_model=MaintenanceDeadLetterReconcileResponse,
    status_code=status.HTTP_200_OK,
    summary="Reconcile one maintenance dead-letter entry",
)
@inject
async def reconcile_maintenance_dead_letter(
    entry_id: str,
    service: Annotated[
        MaintenanceDeadLetterLifecycleService | None,
        Depends(Provide[ApplicationContainer.maintenance_dlq_service]),
    ],
) -> MaintenanceDeadLetterReconcileResponse:
    """Read batch note receipts without requeueing unknown effects."""
    lifecycle = _required_dlq_service(service)
    try:
        result = await lifecycle.reconcile(entry_id)
    except MaintenanceDeadLetterNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Dead-letter entry was not found"
        ) from exc
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Redis maintenance queue is unavailable",
        ) from exc
    return MaintenanceDeadLetterReconcileResponse.from_entity(result)


@router.post(
    "/dead-letters/{entry_id}/retire",
    response_model=MaintenanceDeadLetterRetireResponse,
    status_code=status.HTTP_200_OK,
    summary="Retire one maintenance dead-letter entry",
)
@inject
async def retire_maintenance_dead_letter(
    entry_id: str,
    request: Annotated[
        MaintenanceDeadLetterRetireRequest,
        Depends(model_validate_json_body(MaintenanceDeadLetterRetireRequest)),
    ],
    service: Annotated[
        MaintenanceDeadLetterLifecycleService | None,
        Depends(Provide[ApplicationContainer.maintenance_dlq_service]),
    ],
) -> MaintenanceDeadLetterRetireResponse:
    """Archive provenance before exact Redis cleanup of one entry."""
    lifecycle = _required_dlq_service(service)
    try:
        result = await lifecycle.retire(
            entry_id,
            reason=request.reason,
            classification=request.classification,
            retired_by=request.retired_by,
        )
    except MaintenanceDeadLetterNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Dead-letter entry was not found"
        ) from exc
    except MaintenanceDeadLetterLifecycleConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MaintenanceQueueUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Maintenance DLQ archive or Redis cleanup is unavailable",
        ) from exc
    return MaintenanceDeadLetterRetireResponse.from_entity(result)
