"""Routes for the optional Obsidian graph projection read model."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, status

from app.container import ApplicationContainer
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
    summary="Get optional graph projection status",
    description="Return status for the rebuildable optional Neo4j graph projection.",
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
    """Return graph build status without mutating Markdown or Neo4j.

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
        "does not mutate Markdown, PostgreSQL, or Neo4j."
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
    summary="Rebuild optional graph projection",
    description=(
        "Explicitly rebuild the optional Neo4j graph projection from the "
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
