"""Existing-memory reconciliation dry-run and safe backfill routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.memory.application.reconciliation.runtime.memory_existing_reconciliation_service import (
    MemoryExistingReconciliationService,
)
from app.memory.interface.schemas.reconciliation.existing.memory_existing_reconciliation_request_schema import (
    ExistingMemoryReconciliationHttpRequest,
)
from app.memory.interface.schemas.reconciliation.existing.memory_existing_reconciliation_response_schema import (
    ExistingMemoryReconciliationResponse,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import CONTEXT_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(
    prefix="/memory/reconciliation/existing",
    tags=["memory-reconciliation"],
)


@router.post(
    "/preview",
    response_model=ExistingMemoryReconciliationResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview existing-memory reconciliation",
    description=(
        "Analyze existing Contexts without writing temporal overlays or plans."
    ),
)
@router_exception_status(CONTEXT_ROUTE_EXCEPTION_MAPPING)
@inject
async def preview_existing_memory_reconciliation(
    request: Annotated[
        ExistingMemoryReconciliationHttpRequest,
        Depends(model_validate_json_body(ExistingMemoryReconciliationHttpRequest)),
    ],
    service: Annotated[
        MemoryExistingReconciliationService,
        Depends(
            Provide[ApplicationContainer.memory.memory_existing_reconciliation_service]
        ),
    ],
) -> ExistingMemoryReconciliationResponse:
    """Return a write-free existing-memory reconciliation report.

    Args:
        request: Request.
        service: Service.

    Returns:
        ExistingMemoryReconciliationResponse: Operation result.
    """
    return ExistingMemoryReconciliationResponse.from_entity(
        await service.preview(request.to_contract())
    )


@router.post(
    "/apply",
    response_model=ExistingMemoryReconciliationResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply existing-memory reconciliation backfill",
    description=(
        "Backfill missing temporal read models and persist reviewable plans without "
        "mutating canonical Context content."
    ),
)
@router_exception_status(CONTEXT_ROUTE_EXCEPTION_MAPPING)
@inject
async def apply_existing_memory_reconciliation(
    request: Annotated[
        ExistingMemoryReconciliationHttpRequest,
        Depends(model_validate_json_body(ExistingMemoryReconciliationHttpRequest)),
    ],
    service: Annotated[
        MemoryExistingReconciliationService,
        Depends(
            Provide[ApplicationContainer.memory.memory_existing_reconciliation_service]
        ),
    ],
) -> ExistingMemoryReconciliationResponse:
    """Apply safe and idempotent existing-memory read-model backfill.

    Args:
        request: Request.
        service: Service.

    Returns:
        ExistingMemoryReconciliationResponse: Operation result.
    """
    return ExistingMemoryReconciliationResponse.from_entity(
        await service.apply(request.to_contract())
    )
