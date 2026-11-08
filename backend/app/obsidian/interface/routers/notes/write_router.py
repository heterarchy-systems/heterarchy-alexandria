"""Obsidian note write routes."""

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
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianWriteMode
from app.obsidian.interface.schemas.obsidian.notes.obsidian_note_schema import (
    ObsidianNoteResponse,
    ObsidianNoteWriteResponse,
    ObsidianSaveNoteRequest,
    ObsidianWriteNoteRequest,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import OBSIDIAN_SAVE_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter()


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
