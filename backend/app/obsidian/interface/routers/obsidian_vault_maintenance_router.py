"""Generic Obsidian vault inventory and safe-move routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.interface.schemas.obsidian.maintenance.obsidian_vault_inventory_schema import (
    ObsidianVaultInventoryItemResponse,
    ObsidianVaultInventoryRequestSchema,
    ObsidianVaultInventoryResponse,
)
from app.obsidian.interface.schemas.obsidian.maintenance.obsidian_vault_move_schema import (
    ObsidianVaultMoveApplyRequestSchema,
    ObsidianVaultMovePlanRequestSchema,
    ObsidianVaultMovePlanResponse,
    ObsidianVaultMoveReportResponse,
    ObsidianVaultPathSearchRequest,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/vault", tags=["obsidian"])


@router.post(
    "/inventory",
    response_model=ObsidianVaultInventoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Inventory managed Obsidian vault notes",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def inventory_obsidian_vault_notes(
    request: ObsidianVaultInventoryRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultInventoryResponse:
    """Inventory managed Markdown notes under a vault-relative scope."""
    items = await service.inventory_vault(request.to_command())
    responses = [ObsidianVaultInventoryItemResponse.from_entity(item) for item in items]
    return ObsidianVaultInventoryResponse(items=responses, total=len(responses))


@router.post(
    "/path-search",
    response_model=ObsidianVaultInventoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Search managed Obsidian vault paths",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def search_obsidian_vault_paths(
    request: Annotated[
        ObsidianVaultPathSearchRequest,
        Depends(model_validate_json_body(ObsidianVaultPathSearchRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultInventoryResponse:
    """Search managed path and note metadata without relying on FTS."""
    items = await service.search_vault_paths(
        query=request.query,
        scope_path=request.scope_path,
    )
    responses = [ObsidianVaultInventoryItemResponse.from_entity(item) for item in items]
    return ObsidianVaultInventoryResponse(items=responses, total=len(responses))


@router.post(
    "/move-plan",
    response_model=ObsidianVaultMovePlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Plan safe Obsidian vault moves",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def plan_obsidian_vault_moves(
    request: ObsidianVaultMovePlanRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultMovePlanResponse:
    """Build a dry-run safe move plan without mutating the vault."""
    plan = await service.plan_vault_moves(request.to_command())
    return ObsidianVaultMovePlanResponse.from_entity(plan)


@router.post(
    "/apply-moves",
    response_model=ObsidianVaultMoveReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply safe Obsidian vault moves",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def apply_obsidian_vault_moves(
    request: ObsidianVaultMoveApplyRequestSchema,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianVaultMoveReportResponse:
    """Apply a validated move plan, reindex, verify, and write reports."""
    report = await service.apply_vault_moves(request.to_command())
    return ObsidianVaultMoveReportResponse.from_entity(report)


__all__ = ["router"]
