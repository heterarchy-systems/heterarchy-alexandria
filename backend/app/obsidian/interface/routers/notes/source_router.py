"""Obsidian raw source and repair routes."""

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
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.interface.schemas.obsidian.notes.obsidian_note_schema import (
    ObsidianNoteResponse,
)
from app.obsidian.interface.schemas.obsidian.notes.obsidian_source_schema import (
    ObsidianBodyPatchRequest,
    ObsidianBodyPatchResponse,
    ObsidianFrontmatterRepairRequest,
    ObsidianFrontmatterRepairResponse,
    ObsidianNoteRawReadResponse,
    ObsidianNoteRepairRequest,
)
from app.platform.middleware.database_session import mark_database_transaction_read_only
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import (
    OBSIDIAN_ROUTE_EXCEPTION_MAPPING,
    OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter()


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


@router.post(
    "/notes/repair-frontmatter",
    response_model=ObsidianFrontmatterRepairResponse,
    status_code=status.HTTP_200_OK,
    summary="Repair Obsidian frontmatter only",
    description=(
        "Replace one note's frontmatter block after a byte-hash CAS check while "
        "preserving the durable body bytes exactly; server-owned frontmatter "
        "fields are stripped and reported."
    ),
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def repair_obsidian_note_frontmatter(
    request: Annotated[
        ObsidianFrontmatterRepairRequest,
        Depends(model_validate_json_body(ObsidianFrontmatterRepairRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianFrontmatterRepairResponse:
    """Repair one note's frontmatter without touching durable body bytes."""
    result = await service.repair_note_frontmatter(
        path=request.path,
        expected_content_hash=request.expected_content_hash,
        replacement_frontmatter=request.replacement_frontmatter,
    )
    return ObsidianFrontmatterRepairResponse.from_entity(result)


@router.patch(
    "/notes/body-patch",
    response_model=ObsidianBodyPatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch exact spans in a managed Obsidian note body",
    description=(
        "Apply bounded exact body replacements behind a raw-source hash CAS. "
        "Canonical Markdown remains server-owned; the response contains only "
        "hash, index, and byte-preservation evidence."
    ),
)
@router_exception_status(OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING)
@inject
async def patch_obsidian_note_body(
    request: Annotated[
        ObsidianBodyPatchRequest,
        Depends(model_validate_json_body(ObsidianBodyPatchRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianBodyPatchResponse:
    """Patch exact body spans without returning original or patched source."""
    result = await service.patch_note_body(
        path=request.path,
        expected_content_hash=request.expected_content_hash,
        replacements=tuple(
            (replacement.old_text, replacement.new_text)
            for replacement in request.replacements
        ),
    )
    return ObsidianBodyPatchResponse.from_entity(result)
