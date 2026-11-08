"""Obsidian per-note and full graph projection rebuild routes."""

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
    ObsidianGraphProjectionRebuildResponse,
)
from app.obsidian.interface.schemas.obsidian.graph.obsidian_graph_query_schema import (
    ObsidianGraphNoteRebuildResponse,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING

router = APIRouter()


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
        service: Per-note graph diagnostics and edge rebuild service.
        note_id: Optional stable note identifier selector.
        path: Optional vault-relative note path selector.
        replace_existing_edges: Whether to replace existing cached outgoing edges.

    Returns:
        Per-note edge rebuild and projection activation report.
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
        include_issue_details: Whether to include bounded issue detail entries.
        issue_limit: Maximum number of issue detail entries to return (1..500).

    Returns:
        Full graph projection rebuild report.
    """
    report = await service.rebuild(
        include_issue_details=include_issue_details,
        issue_limit=issue_limit,
    )
    return ObsidianGraphProjectionRebuildResponse.from_entity(report)
