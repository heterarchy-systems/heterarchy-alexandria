"""Obsidian batch note routes."""

from typing import Annotated

from dependency_injector.wiring import (
    Provide,
    inject,
)
from fastapi import (
    APIRouter,
    Depends,
    status,
)

from app.container import ApplicationContainer
from app.obsidian.application.service.notes.obsidian_batch_note_service import (
    ObsidianBatchNoteService,
)
from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchReadSelector,
    BatchWriteOperation,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_batch_read_schema import (
    ObsidianBatchReadRequest,
    ObsidianBatchReadResponse,
    ObsidianBatchValidateLinkItem,
    ObsidianBatchValidateLinksRequest,
    ObsidianBatchValidateLinksResponse,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_batch_write_schema import (
    ObsidianBatchWriteItemResult,
    ObsidianBatchWriteRequest,
    ObsidianBatchWriteResponse,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_note_schema import (
    ObsidianNoteResponse,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter()


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
