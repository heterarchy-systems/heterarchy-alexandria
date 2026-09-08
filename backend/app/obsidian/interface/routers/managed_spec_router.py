"""HTTP route for the high-level managed-spec execution boundary."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status

from app.container import ApplicationContainer
from app.obsidian.application.service.managed_spec.managed_spec_execution_service import (
    ManagedSpecExecutionService,
)
from app.obsidian.domain.managed_spec_exceptions import ManagedSpecError
from app.obsidian.interface.schemas.managed_spec.managed_spec_schema import (
    ManagedSpecCompleteRequestSchema,
    ManagedSpecCompleteResponse,
    ManagedSpecPrepareRequestSchema,
    ManagedSpecPrepareResponse,
    ManagedSpecRequestBody,
    ManagedSpecResponseSchema,
)
from app.platform.middleware.database_session import (
    mark_database_transaction_independent,
    mark_database_transaction_read_only,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
)
from app.shared.exceptions.route_exceptions import (
    OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING,
    RouteExceptionStatusMapping,
)

router = APIRouter(prefix="/obsidian/managed-specs", tags=["managed-spec"])

_MANAGED_SPEC_ROUTE_EXCEPTION_MAPPING: RouteExceptionStatusMapping = {
    ObsidianCheckpointRecoveryRequiredError: status.HTTP_409_CONFLICT,
    ManagedSpecError: status.HTTP_409_CONFLICT,
    **OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING,
}


@router.post(
    "/execute",
    response_model=ManagedSpecResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Prepare or complete one managed specification execution",
    description=(
        "Resolve exact canonical policy/spec notes into an inert pinned envelope, "
        "or complete that envelope through the verified logical upsert boundary."
    ),
)
@router_exception_status(_MANAGED_SPEC_ROUTE_EXCEPTION_MAPPING)
@inject
async def execute_managed_spec(
    http_request: Request,
    request: ManagedSpecRequestBody,
    service: Annotated[
        ManagedSpecExecutionService,
        Depends(Provide[ApplicationContainer.obsidian.managed_spec_service]),
    ],
) -> ManagedSpecPrepareResponse | ManagedSpecCompleteResponse:
    """Execute one discriminated prepare/complete managed-spec request."""
    typed_request = request.root
    if isinstance(typed_request, ManagedSpecPrepareRequestSchema):
        mark_database_transaction_read_only(http_request)
        result = await service.prepare(typed_request.to_command())
        return ManagedSpecPrepareResponse.from_entity(result)
    if isinstance(typed_request, ManagedSpecCompleteRequestSchema):
        mark_database_transaction_independent(http_request)
        result = await service.complete(typed_request.to_command())
        return ManagedSpecCompleteResponse.from_entity(result)
    raise TypeError("unsupported managed-spec request operation")
