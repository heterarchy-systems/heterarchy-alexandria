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
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionRebuildService,
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
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING

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
