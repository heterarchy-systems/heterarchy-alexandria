"""Report-bundle write route for Obsidian-backed Alexandria storage."""

from typing import Annotated

from app.container import ApplicationContainer
from app.obsidian.application.service.notes.obsidian_report_bundle_service import (
    ObsidianReportBundleService,
)
from app.obsidian.interface.schemas.obsidian.obsidian_report_bundle_schema import (
    ObsidianReportBundleRequestSchema,
    ObsidianReportBundleResponse,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

router = APIRouter()


@router.post(
    "/report-bundles/upsert",
    response_model=ObsidianReportBundleResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert an idempotent report bundle",
    description=(
        "Preflight owners, upsert one canonical Source, update owner links, "
        "reindex PostgreSQL and graph projection, then verify incoming edges."
    ),
)
@router_exception_status(OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING)
@inject
async def upsert_obsidian_report_bundle(
    request: ObsidianReportBundleRequestSchema,
    service: Annotated[
        ObsidianReportBundleService,
        Depends(Provide[ApplicationContainer.obsidian.report_bundle_service]),
    ],
) -> ObsidianReportBundleResponse:
    """Execute one durable report bundle operation.

    Args:
        request: Value supplied to upsert_obsidian_report_bundle.
        service: Value supplied to upsert_obsidian_report_bundle.

    Returns:
        Result produced by upsert_obsidian_report_bundle.
    """
    result = await service.upsert(request.to_command())
    return ObsidianReportBundleResponse.from_entity(result)
