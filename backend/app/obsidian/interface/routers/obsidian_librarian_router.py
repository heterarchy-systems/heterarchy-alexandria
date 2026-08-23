"""Librarian ask and resumable workflow routes for Obsidian-backed Alexandria storage."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.obsidian.application.librarian.workflow.obsidian_librarian_workflow_service import (
    ObsidianLibrarianWorkflowService,
)
from app.obsidian.application.service.obsidian_service import ObsidianService
from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianLibrarianWorkflowResume,
)
from app.obsidian.interface.schemas.obsidian.librarian.obsidian_librarian_workflow_schema import (
    ObsidianLibrarianAskRequest,
    ObsidianLibrarianAskResponse,
    ObsidianLibrarianWorkflowResponse,
    ObsidianLibrarianWorkflowResumeRequest,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import (
    OBSIDIAN_ROUTE_EXCEPTION_MAPPING,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body

router = APIRouter()


@router.post(
    "/librarian/ask",
    response_model=ObsidianLibrarianAskResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask Obsidian librarian",
    description="Ask the Alexandria librarian using active Obsidian note context.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def ask_obsidian_librarian(
    request: Annotated[
        ObsidianLibrarianAskRequest,
        Depends(model_validate_json_body(ObsidianLibrarianAskRequest)),
    ],
    service: Annotated[
        ObsidianService,
        Depends(Provide[ApplicationContainer.obsidian.obsidian_service]),
    ],
) -> ObsidianLibrarianAskResponse:
    """Ask the Obsidian-aware librarian adapter.

    Args:
        request: Librarian ask request body.
        service: Obsidian application service.

    Returns:
        Librarian response.
    """
    payload = await service.ask_librarian(request.to_command())
    response = ObsidianLibrarianAskResponse.model_validate(payload)
    return response


@router.post(
    "/librarian/workflows",
    response_model=ObsidianLibrarianWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start Obsidian librarian workflow",
    description="Start a resumable local librarian workflow and pause for approval.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def start_obsidian_librarian_workflow(
    request: Annotated[
        ObsidianLibrarianAskRequest,
        Depends(model_validate_json_body(ObsidianLibrarianAskRequest)),
    ],
    service: Annotated[
        ObsidianLibrarianWorkflowService,
        Depends(Provide[ApplicationContainer.obsidian.workflow_service]),
    ],
) -> ObsidianLibrarianWorkflowResponse:
    """Start a resumable librarian workflow.

    Args:
        request: Librarian workflow start request.
        service: Workflow application service.

    Returns:
        Workflow checkpoint response.
    """
    workflow = await service.start_workflow(request.to_command())
    return ObsidianLibrarianWorkflowResponse.from_entity(workflow)


@router.get(
    "/librarian/workflows/{thread_id}",
    response_model=ObsidianLibrarianWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Read Obsidian librarian workflow",
    description="Read a persisted librarian workflow checkpoint.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_obsidian_librarian_workflow(
    thread_id: str,
    service: Annotated[
        ObsidianLibrarianWorkflowService,
        Depends(Provide[ApplicationContainer.obsidian.workflow_service]),
    ],
) -> ObsidianLibrarianWorkflowResponse:
    """Read a persisted librarian workflow.

    Args:
        thread_id: Workflow thread id.
        service: Workflow application service.

    Returns:
        Workflow checkpoint response.
    """
    workflow = await service.get_workflow(thread_id)
    return ObsidianLibrarianWorkflowResponse.from_entity(workflow)


@router.post(
    "/librarian/workflows/{thread_id}/resume",
    response_model=ObsidianLibrarianWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume Obsidian librarian workflow",
    description="Apply approved workflow actions and persist a completed checkpoint.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def resume_obsidian_librarian_workflow(
    thread_id: str,
    request: Annotated[
        ObsidianLibrarianWorkflowResumeRequest,
        Depends(model_validate_json_body(ObsidianLibrarianWorkflowResumeRequest)),
    ],
    service: Annotated[
        ObsidianLibrarianWorkflowService,
        Depends(Provide[ApplicationContainer.obsidian.workflow_service]),
    ],
) -> ObsidianLibrarianWorkflowResponse:
    """Resume a persisted librarian workflow.

    Args:
        thread_id: Workflow thread id.
        request: Approved actions request.
        service: Workflow application service.

    Returns:
        Workflow checkpoint response.
    """
    workflow = await service.resume_workflow(
        ObsidianLibrarianWorkflowResume(
            thread_id=thread_id, approved_actions=tuple(request.approved_actions)
        )
    )
    return ObsidianLibrarianWorkflowResponse.from_entity(workflow)


@router.post(
    "/librarian/workflows/{thread_id}/cancel",
    response_model=ObsidianLibrarianWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel Obsidian librarian workflow",
    description="Cancel a persisted librarian workflow without writing notes.",
)
@router_exception_status(OBSIDIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def cancel_obsidian_librarian_workflow(
    thread_id: str,
    service: Annotated[
        ObsidianLibrarianWorkflowService,
        Depends(Provide[ApplicationContainer.obsidian.workflow_service]),
    ],
) -> ObsidianLibrarianWorkflowResponse:
    """Cancel a persisted librarian workflow.

    Args:
        thread_id: Workflow thread id.
        service: Workflow application service.

    Returns:
        Workflow checkpoint response.
    """
    workflow = await service.cancel_workflow(thread_id)
    return ObsidianLibrarianWorkflowResponse.from_entity(workflow)
