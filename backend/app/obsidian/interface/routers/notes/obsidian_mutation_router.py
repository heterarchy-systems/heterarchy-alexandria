"""High-level agent-facing mutation outcome route."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status

from app.container import ApplicationContainer
from app.obsidian.application.notes.mutations.outcome_service import (
    ObsidianMutationOutcomeService,
)
from app.obsidian.interface.schemas.obsidian.obsidian_mutation_outcome_schema import (
    ObsidianMutationOutcomeRequestSchema,
    ObsidianMutationOutcomeResponseSchema,
)
from app.platform.middleware.database_session import (
    mark_database_transaction_read_only,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/mutations", tags=["obsidian-mutations"])


@router.post(
    "/outcome",
    response_model=ObsidianMutationOutcomeResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Query one mutation outcome",
    description=(
        "Resolve whether a previously attempted fenced mutation committed, from "
        "durable receipt evidence plus one exact canonical readback, before any "
        "retry decision."
    ),
)
@inject
async def mutation_outcome(
    http_request: Request,
    request: Annotated[
        ObsidianMutationOutcomeRequestSchema,
        model_validate_json_body(ObsidianMutationOutcomeRequestSchema),
    ],
    service: Annotated[
        ObsidianMutationOutcomeService,
        Depends(Provide[ApplicationContainer.obsidian.mutation_outcome_service]),
    ],
) -> ObsidianMutationOutcomeResponseSchema:
    """Return the durable retry-safety verdict for one mutation key."""
    mark_database_transaction_read_only(http_request)
    if request.operation == "note_write":
        outcome = await service.note_write_outcome(
            request.idempotency_key,
            mutation_id=request.mutation_id,
        )
    elif request.operation == "relate":
        assert request.idempotency_key is not None
        outcome = await service.relate_outcome(request.idempotency_key)
    else:
        assert request.idempotency_key is not None
        outcome = await service.verified_upsert_outcome(request.idempotency_key)
    return ObsidianMutationOutcomeResponseSchema.from_entity(outcome)
