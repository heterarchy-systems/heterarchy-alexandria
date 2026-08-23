"""Routes for recovery run execution."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.container import ApplicationContainer
from app.memory.application.contexts.records.context_service import ContextService
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.operations.application.recovery.execution.recovery_run_errors import (
    RecoveryInProgressError,
)
from app.operations.application.recovery.execution.recovery_run_service import (
    RecoveryRunService,
)
from app.operations.interface.schemas.operations.recovery_run_schema import (
    RecoveryRunRequestSchema,
    RecoveryRunResponse,
    RecoveryRunRetryRequestSchema,
)
from app.platform.middleware.database_session import (
    mark_database_transaction_independent,
)
from app.shared.infrastructure.database import Database

router = APIRouter(prefix="/operations/recovery", tags=["operations"])


@router.post(
    "/runs",
    response_model=RecoveryRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Start operational recovery",
    description="Run manual recovery when the dry-run plan allows execution.",
)
@inject
async def recovery_run(
    request: RecoveryRunRequestSchema,
    http_request: Request,
    database: Annotated[Database, Depends(Provide[ApplicationContainer.database])],
    context_service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
    obsidian_service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
    context_service_factory: Annotated[
        Callable[[], ContextService | Awaitable[ContextService]],
        Depends(Provide[ApplicationContainer.memory.context_service.provider]),
    ],
    obsidian_service_factory: Annotated[
        Callable[[], ObsidianService | Awaitable[ObsidianService]],
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service.provider]),
    ],
) -> RecoveryRunResponse:
    """Start or return an idempotent recovery run.

    Args:
        request: Recovery run request payload.
        database: Shared database coordinator.
        context_service: Context/RAG service.
        obsidian_service: Obsidian vault service.

        http_request: Http request used by this operation.
        context_service_factory: Factory that creates context service.
        obsidian_service_factory: Factory that creates obsidian service.
    Returns:
        Recovery run response.
    """
    mark_database_transaction_independent(http_request)
    service = RecoveryRunService(
        database=database,
        context_service=context_service,
        obsidian_service=obsidian_service,
        context_service_factory=context_service_factory,
        obsidian_service_factory=obsidian_service_factory,
    )
    try:
        run = await service.start(request.to_contract())
    except RecoveryInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RECOVERY_IN_PROGRESS",
                "active_recovery_run_id": exc.run_id,
                "idempotency_key": exc.idempotency_key,
            },
        ) from exc
    return RecoveryRunResponse.from_entity(run)


@router.post(
    "/runs/{run_id}/retry",
    response_model=RecoveryRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry operational recovery run",
    description="Start a new parent-linked retry for a persisted recovery run.",
)
@inject
async def retry_recovery_run(
    run_id: str,
    request: RecoveryRunRetryRequestSchema,
    http_request: Request,
    database: Annotated[Database, Depends(Provide[ApplicationContainer.database])],
    context_service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
    obsidian_service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
    context_service_factory: Annotated[
        Callable[[], ContextService | Awaitable[ContextService]],
        Depends(Provide[ApplicationContainer.memory.context_service.provider]),
    ],
    obsidian_service_factory: Annotated[
        Callable[[], ObsidianService | Awaitable[ObsidianService]],
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service.provider]),
    ],
) -> RecoveryRunResponse:
    """Retry a persisted recovery run.

    Args:
        run_id: Parent recovery run identifier.
        request: Retry recovery run request payload.
        database: Shared database coordinator.
        context_service: Context/RAG service.
        obsidian_service: Obsidian vault service.

        http_request: Http request used by this operation.
        context_service_factory: Factory that creates context service.
        obsidian_service_factory: Factory that creates obsidian service.
    Returns:
        Recovery run response.
    """
    mark_database_transaction_independent(http_request)
    service = RecoveryRunService(
        database=database,
        context_service=context_service,
        obsidian_service=obsidian_service,
        context_service_factory=context_service_factory,
        obsidian_service_factory=obsidian_service_factory,
    )
    try:
        run = await service.retry(run_id, request.to_contract())
    except RecoveryInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RECOVERY_IN_PROGRESS",
                "active_recovery_run_id": exc.run_id,
                "idempotency_key": exc.idempotency_key,
            },
        ) from exc
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RECOVERY_RUN_NOT_FOUND",
                "run_id": run_id,
            },
        )
    return RecoveryRunResponse.from_entity(run)


@router.get(
    "/runs/{run_id}",
    response_model=RecoveryRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operational recovery run",
    description="Return a persisted recovery run manifest by id.",
)
@inject
async def get_recovery_run(
    run_id: str,
    database: Annotated[Database, Depends(Provide[ApplicationContainer.database])],
    context_service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
    obsidian_service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> RecoveryRunResponse:
    """Return persisted recovery run by id.

    Args:
        run_id: Recovery run identifier.
        database: Shared database coordinator.
        context_service: Context/RAG service.
        obsidian_service: Obsidian vault service.

    Returns:
        Recovery run response.
    """
    service = RecoveryRunService(
        database=database,
        context_service=context_service,
        obsidian_service=obsidian_service,
    )
    run = await service.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RECOVERY_RUN_NOT_FOUND",
                "run_id": run_id,
            },
        )
    return RecoveryRunResponse.from_entity(run)
