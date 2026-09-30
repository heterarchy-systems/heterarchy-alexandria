"""Deterministic temporal coverage route."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status

from app.container import ApplicationContainer
from app.obsidian.application.service.vault.obsidian_temporal_coverage_service import (
    ObsidianTemporalCoverageService,
)
from app.obsidian.interface.schemas.obsidian.obsidian_temporal_coverage_schema import (
    ObsidianTemporalCoverageRequest,
    ObsidianTemporalCoverageResponse,
)
from app.platform.middleware.database_session import (
    mark_database_transaction_read_only,
)
from app.shared.type_validation.strict_json_body import json_mode_body

router = APIRouter(prefix="/vault", tags=["obsidian-coverage"])


@router.post(
    "/temporal-coverage",
    response_model=ObsidianTemporalCoverageResponse,
    status_code=status.HTTP_200_OK,
    summary="Temporal coverage matrix",
    description=(
        "Classify per-date report-family coverage (COMPLETE, BACKFILL, MISSING, "
        "NOT_EXPECTED, OPEN) deterministically from durable vault packets."
    ),
)
@inject
async def temporal_coverage(
    http_request: Request,
    request: Annotated[
        ObsidianTemporalCoverageRequest,
        json_mode_body(ObsidianTemporalCoverageRequest),
    ],
    service: Annotated[
        ObsidianTemporalCoverageService,
        Depends(Provide[ApplicationContainer.obsidian.temporal_coverage_service]),
    ],
) -> ObsidianTemporalCoverageResponse:
    """Return one deterministic temporal coverage matrix."""
    mark_database_transaction_read_only(http_request)
    payload = await service.coverage(
        project=request.project,
        start_date=request.start_date,
        end_date=request.end_date,
        families=tuple(request.families),
        not_expected=tuple(
            (entry.family, entry.date) for entry in request.not_expected
        ),
        timezone=request.timezone,
    )
    return ObsidianTemporalCoverageResponse.from_payload(payload)
