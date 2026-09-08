"""High-level, idempotent Obsidian relation route."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status

from app.container import ApplicationContainer
from app.obsidian.application.service.notes.obsidian_relate_service import (
    ObsidianRelateService,
)
from app.obsidian.interface.schemas.obsidian.obsidian_relation_schema import (
    ObsidianRelateRequestSchema,
    ObsidianRelateResponse,
)
from app.platform.middleware.database_session import (
    mark_database_transaction_independent,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.obsidian_relation_exceptions import (
    ObsidianRelateInvalidRelationError,
    ObsidianRelateSelfEdgeError,
    ObsidianRelateTargetNotFoundError,
)
from app.shared.exceptions.route_exceptions import OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import json_mode_body

router = APIRouter()

_RELATE_ROUTE_EXCEPTION_MAPPING = {
    **OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING,
    ObsidianRelateTargetNotFoundError: status.HTTP_404_NOT_FOUND,
    ObsidianRelateInvalidRelationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ObsidianRelateSelfEdgeError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


@router.post(
    "/notes/relate",
    response_model=ObsidianRelateResponse,
    status_code=status.HTTP_200_OK,
    summary="Relate two existing Obsidian notes",
    description=(
        "Persist one typed source-to-target relation with canonical Markdown CAS, "
        "durable replay fencing, graph projection rebuild, and readback verification."
    ),
)
@router_exception_status(_RELATE_ROUTE_EXCEPTION_MAPPING)
@inject
async def relate_obsidian_notes(
    http_request: Request,
    request: Annotated[
        ObsidianRelateRequestSchema,
        json_mode_body(ObsidianRelateRequestSchema),
    ],
    service: Annotated[
        ObsidianRelateService,
        Depends(Provide[ApplicationContainer.obsidian.relate_service]),
    ],
) -> ObsidianRelateResponse:
    """Execute one high-level typed relation mutation."""
    mark_database_transaction_independent(http_request)
    result = await service.relate(request.to_command())
    return ObsidianRelateResponse.from_entity(result)
