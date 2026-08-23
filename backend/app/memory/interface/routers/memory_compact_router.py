"""Routes for Memory Compact artifacts."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from typing_extensions import TypedDict

from app.container import ApplicationContainer
from app.memory.application.contexts.records.context_service import ContextService
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.context_enums import RagHealthState
from app.memory.domain.event_enum.memory_compact_enums import (
    MemoryCompactStatus,
)
from app.memory.interface.schemas.memory_compact.memory_compact_review_schema import (
    MemoryCompactReviewRequest,
    MemoryCompactReviewResponse,
)
from app.memory.interface.schemas.memory_compact.memory_compact_schema import (
    MemoryCompactCreateRequest,
    MemoryCompactListResponse,
    MemoryCompactRagGateResponse,
    MemoryCompactResponse,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import (
    MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING,
)
from app.shared.schemas.datetime_schemas import AwareTimestamp
from app.shared.type_validation.strict_json_body import (
    model_validate_json_body,
    model_validate_optional_json_body,
)

router = APIRouter(prefix="/memory/compacts", tags=["memory-compacts"])


class RagHealthGateBlockDetail(TypedDict, closed=True):
    """Structured RAG healthy-gate block payload."""

    error: str
    gate_status: str
    components: list[str]
    warnings: list[str]
    recommended_recovery_tools: list[str]
    retryable: bool


@router.get(
    "",
    response_model=MemoryCompactListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Memory Compacts",
    description="List durable Memory Compact artifacts with optional project and status filters.",
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def list_memory_compacts(
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
    project: str | None = Query(default=None),
    compact_status: MemoryCompactStatus | None = Query(default=None, alias="status"),
    covered_after: AwareTimestamp | None = Query(default=None),
    covered_before: AwareTimestamp | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MemoryCompactListResponse:
    """List Memory Compact artifacts.

    Args:
        project: Project filter.
        compact_status: Lifecycle status filter.
        covered_after: Coverage-overlap lower bound.
        covered_before: Coverage-overlap upper bound.
        limit: Maximum number of rows to return.
        offset: Number of rows to skip.
        service: Memory Compact application service.

    Returns:
        Paginated Memory Compact response.
    """
    items, total = await service.list_compacts(
        project=project,
        status=compact_status,
        covered_after=covered_after,
        covered_before=covered_before,
        limit=limit,
        offset=offset,
    )
    return MemoryCompactListResponse(
        items=[MemoryCompactResponse.from_entity(item) for item in items],
        total=total,
    )


@router.get(
    "/current",
    response_model=MemoryCompactResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current Memory Compact",
    description="Read the CURRENT Memory Compact for a project or the default project.",
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_current_memory_compact(
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
    project: str | None = Query(default=None),
    max_compact_age_days: int = Query(default=30, ge=1, le=365_000),
) -> MemoryCompactResponse:
    """Read current Memory Compact for a project.

    Args:
        project: Optional project filter; None addresses the default project.
        max_compact_age_days: Maximum accepted age for freshness warnings.
        service: Memory Compact application service.

    Returns:
        Current Memory Compact response.
    """
    compact = await service.current(project=project)
    return MemoryCompactResponse.from_entity(
        compact, warnings=_current_compact_warnings(compact, max_compact_age_days)
    )


@router.get(
    "/{compact_id}",
    response_model=MemoryCompactResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Memory Compact",
    description="Read one selected Memory Compact artifact by identifier.",
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_memory_compact(
    compact_id: str,
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
) -> MemoryCompactResponse:
    """Read one Memory Compact.

    Args:
        compact_id: Memory Compact identifier.
        service: Memory Compact application service.

    Returns:
        Selected Memory Compact response.
    """
    compact = await service.get(compact_id)
    return MemoryCompactResponse.from_entity(compact)


@router.post(
    "",
    response_model=MemoryCompactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Memory Compact",
    description="Create a durable Memory Compact artifact and optional source references.",
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def create_memory_compact(
    request: Annotated[
        MemoryCompactCreateRequest,
        Depends(model_validate_json_body(MemoryCompactCreateRequest)),
    ],
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
    context_service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
) -> MemoryCompactResponse:
    """Create a Memory Compact artifact.

    Args:
        request: Public Memory Compact creation payload.
        service: Memory Compact application service.
        context_service: Context/RAG service for the CURRENT healthy gate.

    Returns:
        Created Memory Compact response.
    """
    rag_gate = None
    if request.status == MemoryCompactStatus.CURRENT:
        rag_gate = await _ensure_rag_healthy_for_current(context_service)
    compact = await service.create(request.to_create())
    return MemoryCompactResponse.from_entity(compact, rag_gate=rag_gate)


@router.post(
    "/{compact_id}/mark-current",
    response_model=MemoryCompactResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark Memory Compact current",
    description="Promote one compact to CURRENT and supersede the prior current compact for that project.",
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def mark_memory_compact_current(
    compact_id: str,
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
    context_service: Annotated[
        ContextService, Depends(Provide[ApplicationContainer.memory.context_service])
    ],
) -> MemoryCompactResponse:
    """Mark one compact as current.

    Args:
        compact_id: Memory Compact identifier.
        service: Memory Compact application service.
        context_service: Context/RAG service for the CURRENT healthy gate.

    Returns:
        Updated current Memory Compact response.
    """
    rag_gate = await _ensure_rag_healthy_for_current(context_service)
    compact = await service.mark_current(compact_id)
    return MemoryCompactResponse.from_entity(compact, rag_gate=rag_gate)


@router.post(
    "/{compact_id}/review",
    response_model=MemoryCompactReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Review Memory Compact quality",
    description=(
        "Run the librarian quality rubric and return item scores, verdict, "
        "missing refs, contradictions, stale reasons, and recommended actions."
    ),
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def review_memory_compact(
    compact_id: str,
    request: Annotated[
        MemoryCompactReviewRequest | None,
        Depends(model_validate_optional_json_body(MemoryCompactReviewRequest)),
    ],
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
) -> MemoryCompactReviewResponse:
    """Review one Memory Compact against the librarian rubric.

    Args:
        compact_id: Memory Compact identifier.
        request: Optional current source observations.
        service: Memory Compact application service.

    Returns:
        Structured librarian review result.
    """
    observations = () if request is None else request.to_observations()
    result = await service.review(compact_id, source_observations=observations)
    return MemoryCompactReviewResponse.from_result(result)


@router.delete(
    "/{compact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Memory Compact",
    description="Hard delete a Memory Compact and its durable source references.",
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def delete_memory_compact(
    compact_id: str,
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
) -> Response:
    """Hard delete one Memory Compact.

    Args:
        compact_id: Memory Compact identifier.
        service: Memory Compact application service.

    Returns:
        Empty HTTP 204 response.
    """
    await service.delete(compact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{compact_id}/archive",
    response_model=MemoryCompactResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive Memory Compact",
    description="Archive a Memory Compact without deleting its durable source references.",
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def archive_memory_compact(
    compact_id: str,
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
) -> MemoryCompactResponse:
    """Archive one Memory Compact.

    Args:
        compact_id: Memory Compact identifier.
        service: Memory Compact application service.

    Returns:
        Archived Memory Compact response.
    """
    compact = await service.archive(compact_id)
    return MemoryCompactResponse.from_entity(compact)


def _current_compact_warnings(
    compact: MemoryCompact, max_compact_age_days: int
) -> list[str]:
    """Execute current compact warnings.

    Args:
        compact: Compact used by this operation.
        max_compact_age_days: Max compact age days used by this operation.

    Returns:
        list[str] result produced by current compact warnings.
    """
    freshness_reference = compact.reviewed_at or compact.updated_at
    if datetime.now(UTC) - freshness_reference > timedelta(days=max_compact_age_days):
        return ["current_memory_compact_stale"]
    return []


async def _ensure_rag_healthy_for_current(
    context_service: ContextService,
) -> MemoryCompactRagGateResponse:
    """Ensure rag healthy for current.

    Args:
        context_service: Context service dependency.

    Returns:
        MemoryCompactRagGateResponse result produced by ensure rag healthy for current.
    """
    try:
        health = await context_service.rag_health_with_index_status()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_rag_health_block_detail(
                blockers=["rag_status_unavailable"],
                warnings=[],
            ),
        ) from exc
    blockers = _rag_health_blockers(health)
    if blockers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_rag_health_block_detail(
                blockers=blockers,
                warnings=list(health.warnings),
            ),
        )
    return MemoryCompactRagGateResponse(
        gate_status="passed",
        checked_at=datetime.now(UTC),
        fingerprint=health.fingerprint,
        warnings=list(health.warnings),
    )


def _rag_health_blockers(health: RagDependencyHealth) -> list[str]:
    """Execute rag health blockers.

    Args:
        health: Health used by this operation.

    Returns:
        list[str] result produced by rag health blockers.
    """
    blockers: list[str] = []
    if health.fts is not RagHealthState.HEALTHY:
        blockers.append("rag_fts_not_healthy")
    if health.vector is not RagHealthState.HEALTHY:
        blockers.append("rag_vector_not_healthy")
    if health.embedding is RagHealthState.REINDEX_REQUIRED:
        blockers.append("rag_embedding_reindex_required")
    elif health.embedding is not RagHealthState.HEALTHY:
        blockers.append("rag_embedding_not_healthy")
    if health.warnings:
        blockers.append("rag_status_warnings_present")
    return blockers


def _rag_health_block_detail(
    blockers: list[str],
    warnings: list[str],
) -> RagHealthGateBlockDetail:
    """Execute rag health block detail.

    Args:
        blockers: Blockers used by this operation.
        warnings: Warnings used by this operation.

    Returns:
        RagHealthGateBlockDetail result produced by rag health block detail.
    """
    return RagHealthGateBlockDetail(
        error="blocked_by_rag_health",
        gate_status="blocked",
        components=blockers,
        warnings=warnings,
        recommended_recovery_tools=_rag_health_recovery_tools(blockers),
        retryable=True,
    )


def _rag_health_recovery_tools(blockers: list[str]) -> list[str]:
    """Execute rag health recovery tools.

    Args:
        blockers: Blockers used by this operation.

    Returns:
        list[str] result produced by rag health recovery tools.
    """
    tools: list[str] = []
    if "rag_embedding_reindex_required" in blockers:
        tools.append("alexandria_reindex_context_embeddings")
    if any(blocker != "rag_embedding_reindex_required" for blocker in blockers):
        tools.append("alexandria_check_context_rag_status")
    if not tools:
        tools.append("alexandria_check_context_rag_status")
    return tools
