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
    MemoryStewardReadinessWarningCode,
)
from app.memory.interface.schemas.memory_compact.memory_compact_review_schema import (
    MemoryCompactDraftEditRequest,
    MemoryCompactMarkCurrentRequest,
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
        compact,
        warnings=_CurrentCompactRagGuard.current_compact_warnings(
            compact, max_compact_age_days
        ),
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
        rag_gate = await _CurrentCompactRagGuard.ensure_rag_healthy_for_current(
            context_service
        )
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
    request: Annotated[
        MemoryCompactMarkCurrentRequest | None,
        Depends(model_validate_optional_json_body(MemoryCompactMarkCurrentRequest)),
    ],
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
        request: Optional reviewed-receipt fence for the promotion.
        service: Memory Compact application service.
        context_service: Context/RAG service for the CURRENT healthy gate.

    Returns:
        Updated current Memory Compact response.
    """
    rag_gate = await _CurrentCompactRagGuard.ensure_rag_healthy_for_current(
        context_service
    )
    compact = await service.mark_current(
        compact_id,
        expected_review_hash=None if request is None else request.expected_review_hash,
    )
    return MemoryCompactResponse.from_entity(compact, rag_gate=rag_gate)


@router.post(
    "/{compact_id}/review",
    response_model=MemoryCompactReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Review Memory Compact quality",
    description=(
        "Run the quality rubric and return item scores, verdict, "
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
    """Review one Memory Compact against the quality rubric.

    Args:
        compact_id: Memory Compact identifier.
        request: Validated compatibility input; current sources are read server-side.
        service: Memory Compact application service.

    Returns:
        Structured quality review result.
    """
    del request
    result = await service.review(compact_id)
    return MemoryCompactReviewResponse.from_result(result)


@router.delete(
    "/{compact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Memory Compact",
    description=(
        "Hard delete a Memory Compact and its durable source references. "
        "Requires the explicit confirm=true query parameter."
    ),
)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def delete_memory_compact(
    compact_id: str,
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
    confirm: bool = Query(
        default=False,
        description="Explicit hard-delete confirmation; deletion is refused without it.",
    ),
) -> Response:
    """Hard delete one Memory Compact.

    Args:
        compact_id: Memory Compact identifier.
        service: Memory Compact application service.
        confirm: Explicit hard-delete confirmation flag.

    Returns:
        Empty HTTP 204 response.
    """
    await service.delete(compact_id, confirm=confirm)
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


class _CurrentCompactRagGuard:
    """Enforce RAG health gates and freshness warnings for CURRENT compacts."""

    @staticmethod
    def current_compact_warnings(
        compact: MemoryCompact, max_compact_age_days: int
    ) -> list[str]:
        """Derive freshness warnings for the current Memory Compact response.

        Args:
            compact: Current Memory Compact entity.
            max_compact_age_days: Maximum accepted age in days before flagging staleness.

        Returns:
            List of freshness warning codes for the current compact.
        """
        freshness_reference = compact.reviewed_at or compact.updated_at
        if datetime.now(UTC) - freshness_reference > timedelta(
            days=max_compact_age_days
        ):
            return [
                MemoryStewardReadinessWarningCode.CURRENT_MEMORY_COMPACT_STALE.value
            ]
        return []

    @classmethod
    async def ensure_rag_healthy_for_current(
        cls,
        context_service: ContextService,
    ) -> MemoryCompactRagGateResponse:
        """Verify RAG subsystem health before creating or promoting a CURRENT compact.

        Args:
            context_service: Context and RAG application service dependency.

        Returns:
            Passed RAG health gate summary attached to the compact response.

        Raises:
            HTTPException: If RAG status cannot be inspected or any component is unhealthy.
        """
        try:
            health = await context_service.rag_health_with_index_status()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=cls._rag_health_block_detail(
                    blockers=[
                        MemoryStewardReadinessWarningCode.RAG_STATUS_UNAVAILABLE.value
                    ],
                    warnings=[],
                ),
            ) from exc
        blockers = cls._rag_health_blockers(health)
        if blockers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=cls._rag_health_block_detail(
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

    @staticmethod
    def _rag_health_blockers(health: RagDependencyHealth) -> list[str]:
        """Collect blocking RAG health warning codes from dependency health status.

        Args:
            health: RAG dependency health snapshot.

        Returns:
            Ordered list of blocking RAG health warning codes.
        """
        blockers: list[str] = []
        if health.fts is not RagHealthState.HEALTHY:
            blockers.append(MemoryStewardReadinessWarningCode.RAG_FTS_NOT_HEALTHY.value)
        if health.vector is not RagHealthState.HEALTHY:
            blockers.append(
                MemoryStewardReadinessWarningCode.RAG_VECTOR_NOT_HEALTHY.value
            )
        if health.embedding is RagHealthState.REINDEX_REQUIRED:
            blockers.append(
                MemoryStewardReadinessWarningCode.RAG_EMBEDDING_REINDEX_REQUIRED.value
            )
        elif health.embedding is not RagHealthState.HEALTHY:
            blockers.append(
                MemoryStewardReadinessWarningCode.RAG_EMBEDDING_NOT_HEALTHY.value
            )
        if health.warnings:
            blockers.append(
                MemoryStewardReadinessWarningCode.RAG_STATUS_WARNINGS_PRESENT.value
            )
        return blockers

    @classmethod
    def _rag_health_block_detail(
        cls,
        blockers: list[str],
        warnings: list[str],
    ) -> RagHealthGateBlockDetail:
        """Build the structured HTTP error detail payload for a blocked RAG gate.

        Args:
            blockers: Blocking RAG component warning codes.
            warnings: Additional diagnostic warnings from RAG status.

        Returns:
            Structured RAG health gate block detail dictionary.
        """
        return RagHealthGateBlockDetail(
            error="blocked_by_rag_health",
            gate_status="blocked",
            components=blockers,
            warnings=warnings,
            recommended_recovery_tools=cls._rag_health_recovery_tools(blockers),
            retryable=True,
        )

    @staticmethod
    def _rag_health_recovery_tools(blockers: list[str]) -> list[str]:
        """Recommend MCP recovery tools for a set of RAG health gate blockers.

        Args:
            blockers: Blocking RAG component warning codes.

        Returns:
            Ordered list of recommended MCP tool names.
        """
        reindex_code = (
            MemoryStewardReadinessWarningCode.RAG_EMBEDDING_REINDEX_REQUIRED.value
        )
        tools: list[str] = []
        if reindex_code in blockers:
            tools.append("alexandria_reindex_context_embeddings")
        if any(blocker != reindex_code for blocker in blockers):
            tools.append("alexandria_check_context_rag_status")
        if not tools:
            tools.append("alexandria_check_context_rag_status")
        return tools


@router.post("/{compact_id}/draft", response_model=MemoryCompactResponse)
@router_exception_status(MEMORY_COMPACT_ROUTE_EXCEPTION_MAPPING)
@inject
async def edit_memory_compact_draft(
    compact_id: str,
    request: Annotated[
        MemoryCompactDraftEditRequest,
        Depends(model_validate_json_body(MemoryCompactDraftEditRequest)),
    ],
    service: Annotated[
        MemoryCompactService,
        Depends(Provide[ApplicationContainer.memory.memory_compact_service]),
    ],
) -> MemoryCompactResponse:
    """Replace only an unchanged DRAFT; prior CURRENT remains untouched.

    Args:
        compact_id: Canonical draft identity.
        request: Final semantic body and prior read fence.
        service: Existing Compact lifecycle owner.

    Returns:
        Edited draft with invalidated review evidence.
    """
    compact = await service.edit_draft(
        compact_id, request.markdown_body, request.expected_draft_hash
    )
    return MemoryCompactResponse.from_entity(compact)
