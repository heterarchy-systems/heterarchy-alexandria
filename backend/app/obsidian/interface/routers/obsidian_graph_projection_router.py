"""Routes for the optional Obsidian graph projection read model."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.container import ApplicationContainer
from app.obsidian.application.graph.diagnostics.obsidian_graph_issue_list_service import (
    ObsidianGraphIssueListService,
)
from app.obsidian.application.graph.diagnostics.obsidian_graph_note_diagnostics_service import (
    ObsidianGraphNoteDiagnosticsService,
)
from app.obsidian.application.graph.diagnostics.obsidian_graph_orphan_census_service import (
    ObsidianGraphOrphanCensusService,
)
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
)
from app.obsidian.domain.repositories.obsidian_index_repository import (
    IObsidianIndexRepository,
)
from app.obsidian.interface.schemas.obsidian.graph.obsidian_graph_projection_schema import (
    ObsidianGraphBuildStatusResponse,
    ObsidianGraphProjectionRebuildResponse,
    ObsidianGraphProjectionStatusResponse,
)
from app.obsidian.interface.schemas.obsidian.graph.obsidian_graph_query_schema import (
    ObsidianGraphIssueListResponse,
    ObsidianGraphNoteLinkValidationResponse,
    ObsidianGraphNoteRebuildResponse,
)
from app.obsidian.interface.schemas.obsidian.obsidian_orphan_census_schema import (
    ObsidianGraphOrphanAcknowledgeRequest,
    ObsidianGraphOrphanCensusResponse,
    ObsidianGraphOrphanEntryResponse,
    ObsidianGraphOrphanListRequest,
    ObsidianGraphOrphanStatusRequest,
    ObsidianGraphRelationSuggestionResponse,
    ObsidianGraphRelationSuggestionsResponse,
    ObsidianGraphSuggestRelationsRequest,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import json_mode_body

router = APIRouter()


@router.get(
    "/graph/projection/status",
    response_model=ObsidianGraphProjectionStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get graph projection status",
    description="Return status for the PostgreSQL/Rust graph projection.",
)
@inject
async def graph_projection_status(
    service: Annotated[
        ObsidianGraphProjectionRebuildService,
        Depends(
            Provide[ApplicationContainer.obsidian.graph_projection_rebuild_service]
        ),
    ],
) -> ObsidianGraphProjectionStatusResponse:
    """Return graph projection status without mutating Markdown.

    Args:
        service: Graph projection rebuild/status service.

    Returns:
        Current graph projection status response.
    """
    report = await service.status()
    return ObsidianGraphProjectionStatusResponse.from_entity(report)


@router.get(
    "/graph/build/status",
    response_model=ObsidianGraphBuildStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get graph build status",
    description=(
        "Return graph build status and clarify that per-note graph diagnostics "
        "are validation-only for the current snapshot projection model."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def graph_build_status(
    service: Annotated[
        ObsidianGraphNoteDiagnosticsService,
        Depends(Provide[ApplicationContainer.obsidian.graph_note_diagnostics_service]),
    ],
) -> ObsidianGraphBuildStatusResponse:
    """Return graph build status without mutating canonical Markdown.

    Args:
        service: Per-note graph diagnostics service.

    Returns:
        Graph build/status diagnostic response.
    """
    report = await service.build_status()
    return ObsidianGraphBuildStatusResponse.from_status_report(report)


@router.get(
    "/graph/notes/validate-links",
    response_model=ObsidianGraphNoteLinkValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate outgoing graph links for one Obsidian note",
    description=(
        "Report note index existence, outgoing cached edge resolution, explicit "
        "unresolved targets, and current graph projection status. This endpoint "
        "does not mutate Markdown or PostgreSQL."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def validate_note_graph_links(
    service: Annotated[
        ObsidianGraphNoteDiagnosticsService,
        Depends(Provide[ApplicationContainer.obsidian.graph_note_diagnostics_service]),
    ],
    note_id: str | None = Query(default=None, min_length=1),
    path: str | None = Query(default=None, min_length=1),
    include_resolved_targets: bool = Query(default=False),
) -> ObsidianGraphNoteLinkValidationResponse:
    """Validate cached outgoing graph links for one exact note selector.

    Args:
        note_id: Optional stable note id selector.
        path: Optional vault-relative exact path selector.
        include_resolved_targets: Include resolved edge details when true.
        service: Per-note graph diagnostics service.

    Returns:
        Per-note graph link validation response.
    """
    report = await service.validate_note_links(
        note_id=note_id,
        path=path,
        include_resolved_targets=include_resolved_targets,
    )
    return ObsidianGraphNoteLinkValidationResponse.from_entity(report)


@router.get(
    "/graph/issues",
    response_model=ObsidianGraphIssueListResponse,
    status_code=status.HTTP_200_OK,
    summary="List graph projection issues with exact source detail",
    description=(
        "Recompute the projection from the current index state and list every "
        "non-fatal issue with its exact source note, target path, and relation. "
        "Read-only: this endpoint never creates notes, repairs links, or "
        "mutates Markdown, PostgreSQL, or the active projection."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def list_graph_issues(
    service: Annotated[
        ObsidianGraphIssueListService,
        Depends(Provide[ApplicationContainer.obsidian.graph_issue_list_service]),
    ],
    code: str | None = Query(default=None, min_length=1),
    source_note_id: str | None = Query(default=None, min_length=1),
    source_path: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1),
) -> ObsidianGraphIssueListResponse:
    """List graph projection issues with bounded keyset pagination.

    Args:
        service: Graph issue list service.
        code: Optional issue code filter.
        source_note_id: Optional source note id filter.
        source_path: Optional source path filter.
        limit: Page size bound.
        cursor: Keyset cursor from the previous page.

    Returns:
        One bounded page of graph issue detail.
    """
    from app.obsidian.domain.contracts.obsidian_graph_issue_contracts import (
        ObsidianGraphIssueListQuery,
        ObsidianGraphIssueListValidationError,
    )

    try:
        query = ObsidianGraphIssueListQuery(
            code=code,
            source_note_id=source_note_id,
            source_path=source_path,
            limit=limit,
            cursor=cursor,
        )
    except ObsidianGraphIssueListValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    result = await service.list_issues(query)
    return ObsidianGraphIssueListResponse.from_entity(result)


@router.post(
    "/graph/notes/rebuild",
    response_model=ObsidianGraphNoteRebuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Rebuild graph edges for one Obsidian note",
    description=(
        "Reparse one canonical note, replace its cached outgoing indexed edges, "
        "resolve targets, and activate a fresh full graph projection snapshot."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def rebuild_note_graph(
    service: Annotated[
        ObsidianGraphNoteDiagnosticsService,
        Depends(Provide[ApplicationContainer.obsidian.graph_note_diagnostics_service]),
    ],
    note_id: str | None = Query(default=None, min_length=1),
    path: str | None = Query(default=None, min_length=1),
    replace_existing_edges: bool = Query(default=True),
) -> ObsidianGraphNoteRebuildResponse:
    """Refresh one note's cached edges and the snapshot graph projection.

    Args:
        note_id: Value supplied to rebuild_note_graph.
        path: Value supplied to rebuild_note_graph.
        replace_existing_edges: Value supplied to rebuild_note_graph.
        service: Value supplied to rebuild_note_graph.

    Returns:
        Result produced by rebuild_note_graph.
    """
    report = await service.rebuild_note_graph(
        note_id=note_id,
        path=path,
        replace_existing_edges=replace_existing_edges,
    )
    return ObsidianGraphNoteRebuildResponse.from_entity(report)


@router.post(
    "/graph/projection/rebuild",
    response_model=ObsidianGraphProjectionRebuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Rebuild graph projection",
    description=(
        "Explicitly rebuild the PostgreSQL/Rust graph projection from the "
        "existing read-only Obsidian relational-index state."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def rebuild_graph_projection(
    service: Annotated[
        ObsidianGraphProjectionRebuildService,
        Depends(
            Provide[ApplicationContainer.obsidian.graph_projection_rebuild_service]
        ),
    ],
    include_issue_details: bool = Query(default=False),
    issue_limit: int = Query(default=100, ge=1, le=500),
) -> ObsidianGraphProjectionRebuildResponse:
    """Rebuild graph projection without mutating canonical Markdown.

    Args:
        service: Graph projection rebuild/status service.

        include_issue_details: Whether to include issue details.
        issue_limit: Issue limit used by this operation.
    Returns:
        Rebuild operation response.
    """
    report = await service.rebuild(
        include_issue_details=include_issue_details,
        issue_limit=issue_limit,
    )
    return ObsidianGraphProjectionRebuildResponse.from_entity(report)


@router.post(
    "/graph/orphans",
    response_model=ObsidianGraphOrphanCensusResponse,
    status_code=status.HTTP_200_OK,
    summary="List graph orphan debt",
    description=(
        "Enumerate measured graph orphan debt from the projection snapshot. "
        "This records bounded first/last-seen diagnostic metadata; it does not "
        "mutate canonical Markdown or graph links."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def list_graph_orphans(
    request: Annotated[
        ObsidianGraphOrphanListRequest,
        json_mode_body(ObsidianGraphOrphanListRequest),
    ],
    service: Annotated[
        ObsidianGraphOrphanCensusService,
        Depends(Provide[ApplicationContainer.obsidian.graph_orphan_census_service]),
    ],
    index_repo: Annotated[
        IObsidianIndexRepository,
        Depends(Provide[ApplicationContainer.obsidian.index_repo]),
    ],
) -> ObsidianGraphOrphanCensusResponse:
    """Return one deterministic orphan census page."""
    result = await service.list_orphans(
        project=request.project,
        limit=request.limit,
        cursor=request.cursor,
        index_repository=index_repo,
    )
    return ObsidianGraphOrphanCensusResponse(
        orphans=[
            ObsidianGraphOrphanEntryResponse(
                note_id=orphan.note_id,
                relative_path=orphan.relative_path,
                title=orphan.title,
                project=orphan.project,
                status=orphan.status,
                in_degree=orphan.in_degree,
                out_degree=orphan.out_degree,
                canonical_parent_count=orphan.canonical_parent_count,
                has_wikilink_connectivity=orphan.has_wikilink_connectivity,
                debt_kinds=list(orphan.debt_kinds),
                has_declared_relations=orphan.has_declared_relations,
                acknowledgement_reason=orphan.acknowledgement_reason,
                first_seen_at=(
                    None
                    if orphan.first_seen_at is None
                    else orphan.first_seen_at.isoformat()
                ),
                last_seen_at=(
                    None
                    if orphan.last_seen_at is None
                    else orphan.last_seen_at.isoformat()
                ),
                first_seen_run_id=orphan.first_seen_run_id,
                last_seen_run_id=orphan.last_seen_run_id,
                graph_run_id=orphan.graph_run_id,
            )
            for orphan in result.orphans
        ],
        total_orphans=result.total_orphans,
        next_cursor=result.next_cursor,
    )


@router.post(
    "/graph/orphans/status",
    response_model=ObsidianGraphOrphanEntryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get exact graph orphan status",
    description=(
        "Diagnose one exact note id through the current Rust-owned graph "
        "projection and preserve durable census history."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_graph_orphan_status(
    request: Annotated[
        ObsidianGraphOrphanStatusRequest,
        json_mode_body(ObsidianGraphOrphanStatusRequest),
    ],
    service: Annotated[
        ObsidianGraphOrphanCensusService,
        Depends(Provide[ApplicationContainer.obsidian.graph_orphan_census_service]),
    ],
    index_repo: Annotated[
        IObsidianIndexRepository,
        Depends(Provide[ApplicationContainer.obsidian.index_repo]),
    ],
) -> ObsidianGraphOrphanEntryResponse:
    """Return one exact current orphan status without changing census history."""
    orphan = await service.get_orphan_status(
        note_id=request.note_id,
        index_repository=index_repo,
    )
    return ObsidianGraphOrphanEntryResponse(
        note_id=orphan.note_id,
        relative_path=orphan.relative_path,
        title=orphan.title,
        project=orphan.project,
        status=orphan.status,
        in_degree=orphan.in_degree,
        out_degree=orphan.out_degree,
        canonical_parent_count=orphan.canonical_parent_count,
        has_wikilink_connectivity=orphan.has_wikilink_connectivity,
        debt_kinds=list(orphan.debt_kinds),
        has_declared_relations=orphan.has_declared_relations,
        acknowledgement_reason=orphan.acknowledgement_reason,
        first_seen_at=(
            None if orphan.first_seen_at is None else orphan.first_seen_at.isoformat()
        ),
        last_seen_at=(
            None if orphan.last_seen_at is None else orphan.last_seen_at.isoformat()
        ),
        first_seen_run_id=orphan.first_seen_run_id,
        last_seen_run_id=orphan.last_seen_run_id,
        graph_run_id=orphan.graph_run_id,
    )


@router.post(
    "/graph/orphans/acknowledge",
    response_model=ObsidianGraphOrphanEntryResponse,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge one graph orphan",
    description=(
        "Persist a durable census acknowledgement for one standalone note so "
        "future census pages report the acknowledged status."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def acknowledge_graph_orphan(
    request: Annotated[
        ObsidianGraphOrphanAcknowledgeRequest,
        json_mode_body(ObsidianGraphOrphanAcknowledgeRequest),
    ],
    service: Annotated[
        ObsidianGraphOrphanCensusService,
        Depends(Provide[ApplicationContainer.obsidian.graph_orphan_census_service]),
    ],
) -> ObsidianGraphOrphanEntryResponse:
    """Persist one orphan acknowledgement."""
    acknowledgement = await service.acknowledge_orphan(
        note_id=request.note_id,
        decision=request.decision,
        reason=request.reason,
        acknowledged_by=request.acknowledged_by,
    )
    return ObsidianGraphOrphanEntryResponse(
        note_id=acknowledgement.note_id,
        relative_path="",
        title="",
        project=None,
        status=acknowledgement.decision,
        in_degree=0,
        out_degree=0,
        canonical_parent_count=0,
        has_wikilink_connectivity=False,
        debt_kinds=[],
        has_declared_relations=False,
        acknowledgement_reason=acknowledgement.reason,
    )


@router.post(
    "/graph/orphans/suggest-relations",
    response_model=ObsidianGraphRelationSuggestionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Suggest relations for one note",
    description=(
        "Propose deterministic, evidence-backed relation candidates for one "
        "seed note; suggestions never mutate anything."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def suggest_graph_relations(
    request: Annotated[
        ObsidianGraphSuggestRelationsRequest,
        json_mode_body(ObsidianGraphSuggestRelationsRequest),
    ],
    service: Annotated[
        ObsidianGraphOrphanCensusService,
        Depends(Provide[ApplicationContainer.obsidian.graph_orphan_census_service]),
    ],
    index_repo: Annotated[
        IObsidianIndexRepository,
        Depends(Provide[ApplicationContainer.obsidian.index_repo]),
    ],
) -> ObsidianGraphRelationSuggestionsResponse:
    """Return deterministic relation suggestions for one seed note."""
    result = await service.suggest_relations(
        note_id=request.note_id,
        path=request.path,
        limit=request.limit,
        index_repository=index_repo,
    )
    return ObsidianGraphRelationSuggestionsResponse(
        note_id=result.note_id,
        relative_path=result.relative_path,
        suggestions=[
            ObsidianGraphRelationSuggestionResponse(
                candidate_note_id=s.candidate_note_id,
                candidate_path=s.candidate_path,
                candidate_title=s.candidate_title,
                relation=s.relation,
                confidence=s.confidence,
                shared_tags=list(s.shared_tags),
                shared_neighbor_count=s.shared_neighbor_count,
                title_overlap_tokens=list(s.title_overlap_tokens),
                explanation=s.explanation,
            )
            for s in result.suggestions
        ],
    )
