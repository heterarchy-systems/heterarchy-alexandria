"""Obsidian lookup, path, and canonical identity routes."""

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
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.interface.schemas.obsidian.notes.obsidian_note_schema import (
    ObsidianNoteResponse,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_search_schema import (
    ObsidianRelatedNoteResponse,
    ObsidianRelatedNotesResponse,
    ObsidianSearchHitResponse,
    ObsidianSearchRequest,
    ObsidianSearchResponse,
)
from app.obsidian.interface.schemas.obsidian.obsidian_path_identity_schema import (
    ObsidianCanonicalIdentityRequest,
    ObsidianCanonicalIdentityResponse,
    ObsidianExactPathStatusResponse,
)
from app.platform.middleware.database_session import mark_database_transaction_read_only
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter()


@router.post(
    "/search",
    response_model=ObsidianSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Obsidian notes",
    description="Search Alexandria-managed Obsidian Markdown notes.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def search_obsidian_notes(
    request: Annotated[
        ObsidianSearchRequest, Depends(model_validate_json_body(ObsidianSearchRequest))
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianSearchResponse:
    """Search indexed Obsidian notes.

    Args:
        request: Search request body.
        service: Obsidian application service.

    Returns:
        Search result response.
    """
    hits = await service.search(request.to_query(), refresh=request.refresh)
    items = [ObsidianSearchHitResponse.from_entity(hit) for hit in hits]
    return ObsidianSearchResponse(items=items, total=len(items))


@router.get(
    "/notes/by-path/related",
    response_model=ObsidianRelatedNotesResponse,
    status_code=status.HTTP_200_OK,
    summary="Read related Obsidian notes by path",
    description="Return graph-related notes for one vault-relative Markdown path.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def related_obsidian_notes_by_path(
    service: Annotated[
        ObsidianGraphService,
        Depends(Provide[ApplicationContainer.obsidian.graph_service]),
    ],
    path: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
) -> ObsidianRelatedNotesResponse:
    """Return related notes for one path.

    Args:
        path: Vault-relative Markdown path.
        limit: Maximum related-note count.
        service: Obsidian graph service.

    Returns:
        Related notes response.
    """
    items = await service.related_notes_by_path(path, limit=limit)
    responses = [ObsidianRelatedNoteResponse.from_entity(item) for item in items]
    return ObsidianRelatedNotesResponse(items=responses, total=len(responses))


@router.get(
    "/notes/by-path",
    response_model=ObsidianNoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Read Obsidian note by path",
    description="Read one Alexandria-managed note by vault-relative path.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def read_obsidian_note_by_path(
    request: Request,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
    path: str = Query(min_length=1),
) -> ObsidianNoteResponse:
    """Read one Obsidian note by path.

    Args:
        request: Read-only HTTP request whose projection transaction is discarded.
        path: Vault-relative path.
        service: Obsidian application service.

    Returns:
        Note response.
    """
    mark_database_transaction_read_only(request)
    note = await service.read_note_by_path(path)
    return ObsidianNoteResponse.from_entity(note)


@router.get(
    "/notes/check-path",
    response_model=ObsidianExactPathStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Check an exact Obsidian path",
    description="Resolve the managed root and return exact path existence and identity.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def check_obsidian_note_path(
    service: Annotated[
        ObsidianCanonicalIdentityService,
        Depends(Provide[ApplicationContainer.obsidian.canonical_identity_service]),
    ],
    path: str = Query(min_length=1),
) -> ObsidianExactPathStatusResponse:
    """Check one exact canonical managed path without fuzzy matching.

    Args:
        path: Value supplied to check_obsidian_note_path.
        service: Value supplied to check_obsidian_note_path.

    Returns:
        Result produced by check_obsidian_note_path.
    """
    result = await service.check_path(path)
    return ObsidianExactPathStatusResponse.from_entity(result)


@router.post(
    "/notes/resolve-canonical-identity",
    response_model=ObsidianCanonicalIdentityResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve canonical report identity",
    description=(
        "Resolve project/report/date/entity/edition against existing metadata and "
        "declared aliases without hardcoded product aliases."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def resolve_obsidian_canonical_identity(
    request: Annotated[
        ObsidianCanonicalIdentityRequest,
        Depends(model_validate_json_body(ObsidianCanonicalIdentityRequest)),
    ],
    service: Annotated[
        ObsidianCanonicalIdentityService,
        Depends(Provide[ApplicationContainer.obsidian.canonical_identity_service]),
    ],
) -> ObsidianCanonicalIdentityResponse:
    """Resolve one logical report identity into a canonical family and path.

    Args:
        request: Value supplied to resolve_obsidian_canonical_identity.
        service: Value supplied to resolve_obsidian_canonical_identity.

    Returns:
        Result produced by resolve_obsidian_canonical_identity.
    """
    result = await service.resolve(
        project=request.project,
        report=request.report,
        date=request.date,
        entity=request.entity,
        edition=request.edition,
    )
    return ObsidianCanonicalIdentityResponse.from_entity(result)
