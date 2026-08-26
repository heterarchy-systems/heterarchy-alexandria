"""Operator-only routes for bounded retrieval flight-recorder diagnostics."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.operations.application.diagnostics.operational_retrieval_diagnostics_service import (
    OperationalRetrievalDiagnosticsService,
)
from app.operations.interface.schemas.operations.operational_retrieval_diagnostics_schema import (
    OperationalRetrievalExplainRequest,
    OperationalRetrievalExplainResponse,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/operations", tags=["operations"])


@router.post(
    "/retrieval/explain",
    response_model=OperationalRetrievalExplainResponse,
    status_code=status.HTTP_200_OK,
    summary="Explain one Context retrieval execution",
    description=(
        "Execute the normal Context retrieval path with bounded operator diagnostics. "
        "The response excludes Context bodies, raw database payloads, and embeddings."
    ),
)
@inject
async def explain_context_retrieval(
    request: Annotated[
        OperationalRetrievalExplainRequest,
        Depends(model_validate_json_body(OperationalRetrievalExplainRequest)),
    ],
    service: Annotated[
        OperationalRetrievalDiagnosticsService,
        Depends(
            Provide[ApplicationContainer.operational_retrieval_diagnostics_service]
        ),
    ],
) -> OperationalRetrievalExplainResponse:
    """Return one score-preserving retrieval flight-recorder snapshot.

    Args:
        request: Strict operator retrieval request.
        service: Request-scoped retrieval diagnostics application service.

    Returns:
        Bounded result metadata and execution diagnostics.
    """
    result = await service.explain(request.to_query())
    return OperationalRetrievalExplainResponse.from_entity(result)
