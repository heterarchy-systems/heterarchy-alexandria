"""HTTP route for the high-level bounded memory-cycle operation."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status

from app.container import ApplicationContainer
from app.memory.application.reconciliation.cycles.memory_cycle_service import (
    MemoryCycleService,
)
from app.memory.interface.schemas.reconciliation.cycles.memory_cycle_schema import (
    MemoryCycleApplyRequestSchema,
    MemoryCycleDryRunRequestSchema,
    MemoryCycleRequestBody,
    MemoryCycleResponseSchema,
)
from app.platform.middleware.database_session import (
    mark_database_transaction_independent,
    mark_database_transaction_read_only,
)
from app.shared.exceptions.exception_decorators import (
    RouteExceptionStatusMapping,
    router_exception_status,
)
from app.shared.exceptions.memory_cycle_exceptions import (
    MemoryCycleDomainError,
    MemoryCycleRecoveryRequiredError,
    MemoryCycleStalePlanError,
    MemoryCycleValidationError,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
)
from app.shared.type_validation.strict_json_body import json_mode_body

router = APIRouter(prefix="/memory", tags=["memory"])

_MEMORY_CYCLE_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    MemoryCycleValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    MemoryCycleStalePlanError: status.HTTP_409_CONFLICT,
    MemoryCycleRecoveryRequiredError: status.HTTP_409_CONFLICT,
    MemoryCycleDomainError: status.HTTP_409_CONFLICT,
    ObsidianCheckpointRecoveryRequiredError: status.HTTP_409_CONFLICT,
}


@router.post(
    "/cycle",
    response_model=MemoryCycleResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Preview or apply one bounded memory cycle",
    description=(
        "Build a write-free reconciliation and Compact plan, or apply the exact "
        "semantic plan under the exclusive maintenance lease."
    ),
)
@router_exception_status(_MEMORY_CYCLE_ROUTE_EXCEPTION_MAPPING)
@inject
async def execute_memory_cycle(
    http_request: Request,
    request: Annotated[
        MemoryCycleRequestBody,
        json_mode_body(MemoryCycleRequestBody),
    ],
    service: Annotated[
        MemoryCycleService,
        Depends(Provide[ApplicationContainer.memory_cycle_service]),
    ],
) -> MemoryCycleResponseSchema:
    """Execute one discriminated high-level memory-cycle request."""
    typed_request = request.root
    if isinstance(typed_request, MemoryCycleDryRunRequestSchema):
        mark_database_transaction_read_only(http_request)
    else:
        mark_database_transaction_independent(http_request)
    command = (
        typed_request.to_command()
        if isinstance(
            typed_request,
            (MemoryCycleDryRunRequestSchema, MemoryCycleApplyRequestSchema),
        )
        else None
    )
    if command is None:
        raise TypeError("unsupported memory-cycle request operation")
    result = await service.execute(command)
    return MemoryCycleResponseSchema.from_entity(result)
