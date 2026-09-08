"""High-level logical verified-upsert and verification routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status

from app.container import ApplicationContainer
from app.obsidian.application.service.notes.obsidian_verified_upsert_service import (
    ObsidianVerifiedUpsertService,
)
from app.obsidian.interface.schemas.obsidian.obsidian_verified_upsert_schema import (
    ObsidianVerifiedUpsertRequestSchema,
    ObsidianVerifiedUpsertResponse,
    ObsidianVerifiedUpsertSelectorSchema,
    ObsidianVerifiedUpsertVerificationResponse,
)
from app.platform.middleware.database_session import (
    mark_database_transaction_independent,
    mark_database_transaction_read_only,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import (
    OBSIDIAN_ROUTE_EXCEPTION_MAPPING,
    OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING,
)
from app.shared.type_validation.strict_json_body import json_mode_body

router = APIRouter()


@router.post(
    "/verified-upsert",
    response_model=ObsidianVerifiedUpsertResponse,
    status_code=status.HTTP_200_OK,
    summary="Verified logical Obsidian upsert",
    description=(
        "Resolve one logical identity, persist one canonical note, commit the "
        "index transaction, and verify source readback."
    ),
)
@router_exception_status(OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING)
@inject
async def verified_upsert_obsidian_note(
    http_request: Request,
    request: Annotated[
        ObsidianVerifiedUpsertRequestSchema,
        json_mode_body(ObsidianVerifiedUpsertRequestSchema),
    ],
    service: Annotated[
        ObsidianVerifiedUpsertService,
        Depends(Provide[ApplicationContainer.obsidian.verified_upsert_service]),
    ],
) -> ObsidianVerifiedUpsertResponse:
    """Execute one durable logical upsert with duplicate-safe replay semantics."""
    mark_database_transaction_independent(http_request)
    result = await service.upsert(request.to_command())
    return ObsidianVerifiedUpsertResponse.from_entity(result)


@router.post(
    "/verified-upsert/verify",
    response_model=ObsidianVerifiedUpsertVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify a logical Obsidian note",
    description="Diagnose source, identity, index, graph, and duplicate evidence.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def verify_obsidian_note(
    http_request: Request,
    request: Annotated[
        ObsidianVerifiedUpsertSelectorSchema,
        json_mode_body(ObsidianVerifiedUpsertSelectorSchema),
    ],
    service: Annotated[
        ObsidianVerifiedUpsertService,
        Depends(Provide[ApplicationContainer.obsidian.verified_upsert_service]),
    ],
) -> ObsidianVerifiedUpsertVerificationResponse:
    """Run the high-level logical-note verification composite."""
    mark_database_transaction_read_only(http_request)
    result = await service.verify(request.to_selector())
    return ObsidianVerifiedUpsertVerificationResponse.from_entity(result)
