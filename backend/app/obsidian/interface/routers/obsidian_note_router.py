"""Note, search, and graph routes for Obsidian-backed Alexandria storage."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Request, status

from app.container import ApplicationContainer
from app.obsidian.application.graph.obsidian_graph_service import ObsidianGraphService
from app.obsidian.application.service.notes.obsidian_batch_note_service import (
    ObsidianBatchNoteService,
)
from app.obsidian.application.service.notes.obsidian_canonical_identity_service import (
    ObsidianCanonicalIdentityService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchReadSelector,
    BatchWriteOperation,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianWriteMode
from app.obsidian.interface.routers.obsidian_relation_router import (
    router as relation_router,
)
from app.obsidian.interface.routers.obsidian_report_bundle_router import (
    router as report_bundle_router,
)
from app.obsidian.interface.routers.obsidian_verified_upsert_router import (
    router as verified_upsert_router,
)
from app.obsidian.interface.schemas.obsidian.obsidian_note_write_schema import (
    ObsidianNoteWriteResponse,
    ObsidianSaveNoteRequest,
    ObsidianWriteNoteRequest,
)
from app.obsidian.interface.schemas.obsidian.obsidian_path_identity_schema import (
    ObsidianCanonicalIdentityRequest,
    ObsidianCanonicalIdentityResponse,
    ObsidianExactPathStatusResponse,
)
from app.obsidian.interface.schemas.obsidian.obsidian_schema import (
    ObsidianBatchReadRequest,
    ObsidianBatchReadResponse,
    ObsidianBatchValidateLinkItem,
    ObsidianBatchValidateLinksRequest,
    ObsidianBatchValidateLinksResponse,
    ObsidianBatchWriteItemResult,
    ObsidianBatchWriteRequest,
    ObsidianBatchWriteResponse,
    ObsidianNoteRawReadResponse,
    ObsidianNoteRepairRequest,
    ObsidianNoteResponse,
)
from app.obsidian.interface.schemas.obsidian.obsidian_search_schema import (
    ObsidianRelatedNoteResponse,
    ObsidianRelatedNotesResponse,
    ObsidianSearchHitResponse,
    ObsidianSearchRequest,
    ObsidianSearchResponse,
)
from app.platform.middleware.database_session import mark_database_transaction_read_only
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import (
    OBSIDIAN_ROUTE_EXCEPTION_MAPPING,
    OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter()
router.include_router(report_bundle_router)
router.include_router(relation_router)
router.include_router(verified_upsert_router)


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


@router.get(
    "/notes/raw",
    response_model=ObsidianNoteRawReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Read raw Obsidian note source",
    description=(
        "Read one note's raw source text even when its frontmatter fails to parse."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def read_obsidian_note_raw(
    request: Request,
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
    path: str | None = Query(default=None, min_length=1),
    note_id: str | None = Query(default=None, min_length=1),
) -> ObsidianNoteRawReadResponse:
    """Read one note's raw source for minimal repair inspection.

    Args:
        request: Read-only HTTP request whose projection transaction is discarded.
        path: Vault-relative Markdown path.
        note_id: Stable note id.
        service: Obsidian application service.

    Returns:
        Raw note read response.
    """
    mark_database_transaction_read_only(request)
    read = await service.read_note_raw(path=path, note_id=note_id)
    return ObsidianNoteRawReadResponse.from_entity(read)


@router.post(
    "/notes/repair",
    response_model=ObsidianNoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Repair raw Obsidian note source",
    description=(
        "Replace one note's raw Markdown after a byte-hash CAS check and "
        "parse validation, so a malformed note is recovered in place."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def repair_obsidian_note_raw(
    request: Annotated[
        ObsidianNoteRepairRequest,
        Depends(model_validate_json_body(ObsidianNoteRepairRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianNoteResponse:
    """Repair one note's raw source with CAS and parse guards.

    Args:
        request: Repair request body with current hash and replacement source.
        service: Obsidian application service.

    Returns:
        The repaired note response.
    """
    note = await service.repair_note_raw(
        path=request.path,
        expected_content_hash=request.expected_content_hash,
        raw_content=request.raw_content,
    )
    return ObsidianNoteResponse.from_entity(note)


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


@router.post(
    "/notes",
    response_model=ObsidianNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save Obsidian note",
    description="Create or replace one Alexandria-managed Markdown note.",
)
@router_exception_status(OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING)
@inject
async def save_obsidian_note(
    request: Annotated[
        ObsidianSaveNoteRequest,
        Depends(model_validate_json_body(ObsidianSaveNoteRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianNoteResponse:
    """Save one Obsidian Markdown note.

    Args:
        request: Save request body.
        service: Obsidian application service.

    Returns:
        Saved note response.
    """
    note = await service.save_note(request.to_command())
    return ObsidianNoteResponse.from_entity(note)


async def _write_obsidian_note(
    request: ObsidianWriteNoteRequest,
    service: ObsidianService,
    write_mode: ObsidianWriteMode,
) -> ObsidianNoteWriteResponse:
    """Write obsidian note.

    Args:
        request: Validated request for this operation.
        service: Application service used by this operation.
        write_mode: Write mode used by this operation.

    Returns:
        ObsidianNoteWriteResponse result produced by write obsidian note.
    """
    result = await service.write_note(request.to_write_command(write_mode))
    return ObsidianNoteWriteResponse.from_entity(result)


@router.post(
    "/notes/create",
    response_model=ObsidianNoteWriteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an Obsidian note",
    description="Create only; fail before mutation when the exact id or path exists.",
)
@router_exception_status(OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING)
@inject
async def create_obsidian_note(
    request: Annotated[
        ObsidianWriteNoteRequest,
        Depends(model_validate_json_body(ObsidianWriteNoteRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianNoteWriteResponse:
    """Create one canonical note with exact identity semantics.

    Args:
        request: Value supplied to create_obsidian_note.
        service: Value supplied to create_obsidian_note.

    Returns:
        Result produced by create_obsidian_note.
    """
    return await _write_obsidian_note(request, service, ObsidianWriteMode.CREATE)


@router.post(
    "/notes/update",
    response_model=ObsidianNoteWriteResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an Obsidian note",
    description="Update only by exact id or path; never move a note implicitly.",
)
@router_exception_status(OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING)
@inject
async def update_obsidian_note(
    request: Annotated[
        ObsidianWriteNoteRequest,
        Depends(model_validate_json_body(ObsidianWriteNoteRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianNoteWriteResponse:
    """Update one existing canonical note with exact identity semantics.

    Args:
        request: Value supplied to update_obsidian_note.
        service: Value supplied to update_obsidian_note.

    Returns:
        Result produced by update_obsidian_note.
    """
    return await _write_obsidian_note(request, service, ObsidianWriteMode.UPDATE)


@router.post(
    "/notes/upsert",
    response_model=ObsidianNoteWriteResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert an Obsidian note",
    description="Create or update by one exact selector; reject selector conflicts.",
)
@router_exception_status(OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING)
@inject
async def upsert_obsidian_note(
    request: Annotated[
        ObsidianWriteNoteRequest,
        Depends(model_validate_json_body(ObsidianWriteNoteRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianNoteWriteResponse:
    """Create or update one canonical note without ambiguous identity fallback.

    Args:
        request: Value supplied to upsert_obsidian_note.
        service: Value supplied to upsert_obsidian_note.

    Returns:
        Result produced by upsert_obsidian_note.
    """
    return await _write_obsidian_note(request, service, ObsidianWriteMode.UPSERT)


@router.post(
    "/notes/batch-read",
    response_model=ObsidianBatchReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch read Obsidian notes",
    description=(
        "Read many notes independently by path or note_id. One item's failure "
        "does not fail the batch. Bounded to 50 selectors per request."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def batch_read_notes(
    request: Annotated[
        ObsidianBatchReadRequest,
        Depends(model_validate_json_body(ObsidianBatchReadRequest)),
    ],
    batch_service: Annotated[
        ObsidianBatchNoteService,
        Depends(Provide[ApplicationContainer.obsidian.batch_note_service]),
    ],
) -> ObsidianBatchReadResponse:
    """Read many notes independently.

    Args:
        request: Batch read request body.
        batch_service: Batch note service.

    Returns:
        Batch read response with per-item outcomes.
    """
    result = await batch_service.batch_read(
        [
            BatchReadSelector(path=item.path, note_id=item.note_id)
            for item in request.selectors
        ]
    )
    notes = [
        ObsidianNoteResponse.from_entity(item.note)
        for item in result.items
        if item.note is not None
    ]
    errors = [
        {"path": item.path, "note_id": item.note_id, "status": item.status}
        for item in result.items
        if item.note is None
    ]
    return ObsidianBatchReadResponse(
        items=notes, errors=errors, total=len(result.items)
    )


@router.post(
    "/notes/batch-validate-links",
    response_model=ObsidianBatchValidateLinksResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch validate outgoing links for many notes",
    description=(
        "Validate outgoing graph links for many notes independently. One "
        "item's failure does not fail the batch. Bounded to 50 selectors."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def batch_validate_note_links(
    request: Annotated[
        ObsidianBatchValidateLinksRequest,
        Depends(model_validate_json_body(ObsidianBatchValidateLinksRequest)),
    ],
    batch_service: Annotated[
        ObsidianBatchNoteService,
        Depends(Provide[ApplicationContainer.obsidian.batch_note_service]),
    ],
) -> ObsidianBatchValidateLinksResponse:
    """Validate outgoing links for many notes.

    Args:
        request: Batch validate request body.
        batch_service: Batch note service.

    Returns:
        Batch link validation response.
    """
    selectors = [
        BatchReadSelector(path=item.path, note_id=item.note_id)
        for item in request.selectors
    ]
    result = await batch_service.batch_validate_links(selectors)
    items = [
        ObsidianBatchValidateLinkItem(
            path=item.path,
            note_id=item.note_id,
            status=item.status,
            exists=item.exists,
            parsed_count=item.parsed_count,
            resolved_count=item.resolved_count,
            unresolved_count=item.unresolved_count,
            error=item.error,
        )
        for item in result.items
    ]
    return ObsidianBatchValidateLinksResponse(items=items)


@router.post(
    "/notes/batch-write",
    response_model=ObsidianBatchWriteResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch write Obsidian notes with per-item CAS",
    description=(
        "Execute many independent CAS writes. Each item is independent: "
        "one item's conflict or failure does not affect others. Bounded to "
        "50 operations per request."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def batch_write_notes(
    request: Annotated[
        ObsidianBatchWriteRequest,
        Depends(model_validate_json_body(ObsidianBatchWriteRequest)),
    ],
    batch_service: Annotated[
        ObsidianBatchNoteService,
        Depends(Provide[ApplicationContainer.obsidian.batch_note_service]),
    ],
) -> ObsidianBatchWriteResponse:
    """Execute many independent CAS writes.

    Args:
        request: Batch write request body.
        batch_service: Batch note service.

    Returns:
        Batch write response with per-item CAS outcomes.
    """
    ops = [
        BatchWriteOperation(
            op=item.op,
            title=item.title,
            body=item.body,
            relative_path=item.relative_path,
            note_id=item.note_id,
            expected_content_hash=item.expected_content_hash,
            frontmatter=dict(item.frontmatter),
        )
        for item in request.operations
    ]
    result = await batch_service.batch_write(ops)
    return ObsidianBatchWriteResponse(
        results=[
            ObsidianBatchWriteItemResult(
                relative_path=item.path,
                note_id=item.note_id,
                status=item.status,
                content_hash=item.content_hash,
                current_content_hash=item.current_content_hash,
                error=item.error,
            )
            for item in result.items
        ],
        succeeded=result.succeeded,
        conflicted=result.conflicted,
        failed=result.failed,
    )
