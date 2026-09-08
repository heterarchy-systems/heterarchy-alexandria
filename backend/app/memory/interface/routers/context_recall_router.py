"""High-level agent-facing Context recall route."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.memory.application.retrieval.recall_service import RecallService
from app.memory.interface.schemas.context.recall_schema import (
    RecallRequestSchema,
    RecallResponseSchema,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import CONTEXT_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import json_mode_body

router = APIRouter(prefix="/memory", tags=["memory-recall"])


@router.post(
    "/recall",
    response_model=RecallResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Recall memory",
    description=(
        "Resolve scope identity and execute a bounded exact, lexical, semantic, "
        "related-project, and global memory recall cascade."
    ),
)
@router_exception_status(CONTEXT_ROUTE_EXCEPTION_MAPPING)
@inject
async def recall_memory(
    request: Annotated[RecallRequestSchema, json_mode_body(RecallRequestSchema)],
    service: Annotated[
        RecallService,
        Depends(Provide[ApplicationContainer.recall_service]),
    ],
) -> RecallResponseSchema:
    """Return high-level recall matches with bounded provenance and trace."""
    result = await service.recall(request.to_contract())
    return RecallResponseSchema.from_entity(result)
