"""Routes for Context Vault retrieval and embedding operations."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.container import ApplicationContainer
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.interface.schemas.context.context_mapping import (
    health_payload,
    pack_payload,
    soft_rebuild_payload,
)
from app.memory.interface.schemas.context.context_retrieval_schema import (
    ContextPackResponse,
    ContextSearchRequest,
    ContextSoftRebuildResponse,
    RagStatusResponse,
)
from app.platform.config.app_config import AppConfig
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import CONTEXT_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter(prefix="/memory/contexts", tags=["library-contexts"])


@router.post(
    "/retrieval/search",
    response_model=ContextPackResponse,
    status_code=status.HTTP_200_OK,
    description="Search Context Vault and return a Context Pack.",
    summary="Search contexts",
)
@router_exception_status(CONTEXT_ROUTE_EXCEPTION_MAPPING)
@inject
async def search_contexts(
    request: Annotated[
        ContextSearchRequest, Depends(model_validate_json_body(ContextSearchRequest))
    ],
    service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
) -> ContextPackResponse:
    """Search contexts for RAG.

    Args:
        request: Context search request.
        service: Context application service.

    Returns:
        Context Pack response.
    """
    pack = await service.search(
        query=request.query,
        strategy=request.strategy,
        limit=request.limit,
        project=request.project,
        kind=request.kind,
        include_scopes=request.include_scopes,
        workspace_id=request.workspace_id,
        agent_id=request.agent_id,
        user_id=request.user_id,
        session_id=request.session_id,
        include_lifecycle_statuses=request.include_lifecycle_statuses,
        prefer_memory_functions=request.prefer_memory_functions,
    )
    response = ContextPackResponse.model_validate(pack_payload(pack))
    return response


@router.get(
    "/rag/status",
    response_model=RagStatusResponse,
    status_code=status.HTTP_200_OK,
    description="Return Context RAG dependency health.",
    summary="Get context RAG status",
)
@router_exception_status(CONTEXT_ROUTE_EXCEPTION_MAPPING)
@inject
async def rag_status(
    http_response: Response,
    service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
) -> RagStatusResponse:
    """Return RAG dependency status.

    Args:
        http_response: Mutable HTTP response used for runtime provenance metadata.
        service: Context application service.

    Returns:
        RAG health response.
    """
    health = await service.rag_health_with_index_status()
    http_response.headers["X-Alexandria-Retrieval-Kernel-Authority"] = (
        service.retrieval_kernel_authority
    )
    response = RagStatusResponse.model_validate(health_payload(health))
    return response


@router.post(
    "/retrieval/reindex",
    status_code=status.HTTP_409_CONFLICT,
    description=(
        "Reject direct CPU-heavy embedding reindex execution. Submit the "
        "operation through the bounded Redis Streams maintenance queue instead."
    ),
    summary="Reject direct embedding reindex execution",
)
@inject
async def reindex_context_embeddings(
    app_config: Annotated[AppConfig, Depends(Provide[ApplicationContainer.app_config])],
    limit: int = Query(default=100, ge=1, le=1000),
    force: bool = Query(default=False),
) -> None:
    """Reject direct embedding execution so the API cannot bypass the queue.

    Args:
        limit: Maximum chunks to reindex in this batch.
        force: Whether to rebuild existing embeddings even if model metadata matches.
        app_config: Common service settings used for the diagnostic response header.

    Raises:
        HTTPException: Always, with the queue submission endpoint.
    """
    del limit, force
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "EMBEDDING_REINDEX_REQUIRES_QUEUE",
            "message": (
                "Embedding reindex must be submitted to the bounded Redis "
                "Streams maintenance queue."
            ),
            "submission_endpoint": "/operations/maintenance/embedding-reindex/jobs",
        },
        headers={"X-Alexandria-Service": app_config.app_name},
    )


@router.post(
    "/retrieval/soft-rebuild",
    response_model=ContextSoftRebuildResponse,
    status_code=status.HTTP_200_OK,
    description="Soft rebuild embeddings/vectors without deleting source rows.",
    summary="Soft rebuild context embeddings",
)
@router_exception_status(CONTEXT_ROUTE_EXCEPTION_MAPPING)
@inject
async def soft_rebuild_context_embeddings(
    service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
    limit: int = Query(default=100, ge=1, le=1000),
    verification_query: str | None = Query(default=None),
    project: str | None = Query(default=None),
) -> ContextSoftRebuildResponse:
    """Soft rebuild embedding/vector fields and return operator evidence.

    Args:
        limit: Maximum chunks to rebuild in this batch.
        verification_query: Optional verification query to run after rebuild.
        project: Optional project filter for verification.
        service: Context application service.

    Returns:
        Soft rebuild evidence response.
    """
    result = await service.soft_rebuild_embeddings(
        limit=limit,
        verification_query=verification_query,
        project=project,
    )
    response = ContextSoftRebuildResponse.model_validate(soft_rebuild_payload(result))
    return response
