"""Vault and index lifecycle routes for Obsidian-backed Alexandria storage."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.application.service.vault.obsidian_vault_reindex_service import (
    ObsidianVaultReindexService,
)
from app.obsidian.interface.schemas.obsidian.maintenance.obsidian_index_error_repair_schema import (
    ObsidianIndexErrorRepairApplyRequest,
    ObsidianIndexErrorRepairPlanResponse,
    ObsidianIndexErrorRepairReportResponse,
)
from app.obsidian.interface.schemas.obsidian.maintenance.obsidian_legacy_metadata_repair_schema import (
    ObsidianLegacyMetadataRepairApplyRequest,
    ObsidianLegacyMetadataRepairPlanResponse,
    ObsidianLegacyMetadataRepairReportResponse,
)
from app.obsidian.interface.schemas.obsidian.obsidian_schema import (
    ObsidianNoteResponse,
    ObsidianReindexResponse,
    ObsidianStatusResponse,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import (
    OBSIDIAN_ROUTE_EXCEPTION_MAPPING,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter()


@router.get(
    "/status",
    response_model=ObsidianStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Obsidian index status",
    description="Return Obsidian vault and Alexandria index status.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def obsidian_status(
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianStatusResponse:
    """Return Obsidian vault/index status.

    Args:
        service: Obsidian application service.

    Returns:
        Current vault/index status response.
    """
    result = await service.status()
    return ObsidianStatusResponse.from_entity(result)


@router.post(
    "/init",
    response_model=ObsidianNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize Obsidian vault",
    description="Create Alexandria folders and START_HERE note in the Obsidian vault.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def initialize_obsidian_vault(
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianNoteResponse:
    """Initialize the managed Obsidian vault layout.

    Args:
        service: Obsidian application service.

    Returns:
        START_HERE note response.
    """
    note = await service.initialize_vault()
    return ObsidianNoteResponse.from_entity(note)


@router.post(
    "/index/rebuild",
    response_model=ObsidianReindexResponse,
    status_code=status.HTTP_200_OK,
    summary="Reindex Obsidian vault",
    description=(
        "Scan Alexandria Markdown notes, rebuild the relational search cache, "
        "then refresh the optional graph projection."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def reindex_obsidian_vault(
    service: Annotated[
        ObsidianVaultReindexService,
        Depends(Provide[ApplicationContainer.obsidian.vault_reindex_service]),
    ],
) -> ObsidianReindexResponse:
    """Rebuild the Obsidian index cache.

    Args:
        service: Obsidian application service.

    Returns:
        Reindex summary response.
    """
    result = await service.rebuild()
    return ObsidianReindexResponse.from_reindex_report(result)


@router.post(
    "/index/errors/repair-plan",
    response_model=ObsidianIndexErrorRepairPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Plan known legacy index-error repairs",
    description=(
        "Inspect current source hashes and return a non-mutating repair plan. "
        "Unknown errors are skipped for manual review."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def plan_obsidian_index_error_repairs(
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianIndexErrorRepairPlanResponse:
    """Return a dry-run plan bound to the current Markdown bytes.

    Args:
        service: Obsidian application facade.

    Returns:
        HTTP repair-plan response.
    """
    plan = await service.plan_index_error_repairs()
    return ObsidianIndexErrorRepairPlanResponse.from_entity(plan)


@router.post(
    "/index/errors/repair",
    response_model=ObsidianIndexErrorRepairReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply known legacy index-error repairs",
    description=(
        "Verify the plan hash, back up every source, patch only known scalar "
        "frontmatter fields, then reindex and persist an audit report."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def apply_obsidian_index_error_repairs(
    request: Annotated[
        ObsidianIndexErrorRepairApplyRequest,
        Depends(model_validate_json_body(ObsidianIndexErrorRepairApplyRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianIndexErrorRepairReportResponse:
    """Apply an unchanged repair plan after writing verified backups.

    Args:
        request: Accepted plan hash.
        service: Obsidian application facade.

    Returns:
        HTTP repair evidence response.
    """
    report = await service.apply_index_error_repairs(
        expected_plan_hash=request.expected_plan_hash
    )
    return ObsidianIndexErrorRepairReportResponse.from_entity(report)


@router.post(
    "/metadata/legacy-repair-plan",
    response_model=ObsidianLegacyMetadataRepairPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Plan legacy metadata repairs",
    description=(
        "Dry-run managed Markdown for tuple-repr collections, string Booleans, "
        "and unrecoverable redacted URLs without changing source files."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def plan_obsidian_legacy_metadata_repairs(
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianLegacyMetadataRepairPlanResponse:
    """Return a non-mutating, source-hash-bound metadata repair plan.

    Args:
        service: Obsidian application facade.

    Returns:
        HTTP repair-plan response.
    """
    plan = await service.plan_legacy_metadata_repairs()
    return ObsidianLegacyMetadataRepairPlanResponse.from_entity(plan)


@router.post(
    "/metadata/legacy-repair",
    response_model=ObsidianLegacyMetadataRepairReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply legacy metadata repairs",
    description=(
        "Apply only an explicitly accepted plan after verified backups, then "
        "reindex changed documents and report before/after content hashes."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def apply_obsidian_legacy_metadata_repairs(
    request: Annotated[
        ObsidianLegacyMetadataRepairApplyRequest,
        Depends(model_validate_json_body(ObsidianLegacyMetadataRepairApplyRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianLegacyMetadataRepairReportResponse:
    """Apply the accepted repair plan and return per-document evidence.

    Args:
        request: Explicitly accepted repair plan hash.
        service: Obsidian application facade.

    Returns:
        HTTP repair report.
    """
    report = await service.apply_legacy_metadata_repairs(
        expected_plan_hash=request.expected_plan_hash
    )
    return ObsidianLegacyMetadataRepairReportResponse.from_entity(report)
