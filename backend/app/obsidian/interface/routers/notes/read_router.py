"""Obsidian graph relationship and note read routes."""

from typing import Annotated

from dependency_injector.wiring import (
    Provide,
    inject,
)
from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    status,
)

from app.container import ApplicationContainer
from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.interface.schemas.obsidian.notes.obsidian_note_schema import (
    ObsidianNoteResponse,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_search_schema import (
    ObsidianRelatedNoteResponse,
    ObsidianRelatedNotesResponse,
)
from app.platform.middleware.database_session import mark_database_transaction_read_only
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING

router = APIRouter()


@router.get(
    "/notes/{note_id}/related",
    response_model=ObsidianRelatedNotesResponse,
    status_code=status.HTTP_200_OK,
    summary="Read related Obsidian notes",
    description="Return graph-related notes for one stable note id.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def related_obsidian_notes(
    note_id: str,
    service: Annotated[
        ObsidianGraphService,
        Depends(Provide[ApplicationContainer.obsidian.graph_service]),
    ],
    limit: int = Query(default=10, ge=1, le=50),
) -> ObsidianRelatedNotesResponse:
    """Return related notes for one stable note id.

    Args:
        note_id: Stable note id.
        limit: Maximum related-note count.
        service: Obsidian graph service.

    Returns:
        Related notes response.
    """
    items = await service.related_notes(note_id, limit=limit)
    responses = [ObsidianRelatedNoteResponse.from_entity(item) for item in items]
    return ObsidianRelatedNotesResponse(items=responses, total=len(responses))


@router.get(
    "/notes/{note_id}",
    response_model=ObsidianNoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Read Obsidian note",
    description="Read one Alexandria-managed note by stable id.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def read_obsidian_note(
    note_id: str,
    request: Request,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianNoteResponse:
    """Read one Obsidian note by id.

    Args:
        request: Read-only HTTP request whose projection transaction is discarded.
        note_id: Stable note id.
        service: Obsidian application service.

    Returns:
        Note response.
    """
    mark_database_transaction_read_only(request)
    note = await service.read_note(note_id)
    return ObsidianNoteResponse.from_entity(note)
