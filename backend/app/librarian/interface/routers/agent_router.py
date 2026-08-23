"""Agent profile routes."""

from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.container import ApplicationContainer
from app.librarian.application.agent_service import AgentService
from app.librarian.domain.entities.read_models import AgentProfile
from app.librarian.domain.types.agent_payload_types import AgentCreatePayload
from app.librarian.interface.schemas.agent.agent_schema import (
    AgentCreateRequest,
    AgentPatchRequest,
    AgentResponse,
    AgentResponseList,
)
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import LIBRARIAN_ROUTE_EXCEPTION_MAPPING
from app.shared.type_validation.strict_json_body import model_validate_json_body
from app.shared.types.types_convert_utils import now_utc

router = APIRouter(
    prefix="/librarians/profiles",
    tags=["agents"],
)


def _to_response(model: AgentProfile) -> AgentResponse:
    """Project ORM row to response model.

    Args:
        model: Agent profile read model.

    Returns:
        AgentResponse: Public agent response schema.
    """
    return AgentResponse(
        id=model.id,
        name=model.name,
        provider=model.provider,
        description=model.description,
        capabilities=list(model.capabilities),
        preferred_librarian_provider=model.preferred_librarian_provider,
        preferred_librarian_model=model.preferred_librarian_model,
        max_librarian_agents=model.max_librarian_agents,
        librarian_role_prompt=model.librarian_role_prompt,
        librarian_role=model.librarian_role,
        librarian_specialties=list(model.librarian_specialties or ()),
        librarian_routing_priority=model.librarian_routing_priority,
        librarian_enabled=model.librarian_enabled,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _create_payload(request: AgentCreateRequest) -> AgentCreatePayload:
    """Convert a create request into an application payload.

    Args:
        request: Validated create request.

    Returns:
        AgentCreatePayload: Application create payload.
    """
    now = now_utc()
    return AgentCreatePayload(
        name=request.name,
        provider=request.provider,
        description=request.description,
        capabilities=request.capabilities,
        preferred_librarian_provider=request.preferred_librarian_provider,
        preferred_librarian_model=request.preferred_librarian_model,
        max_librarian_agents=request.max_librarian_agents,
        librarian_role_prompt=request.librarian_role_prompt,
        librarian_role=request.librarian_role,
        librarian_specialties=request.librarian_specialties,
        librarian_routing_priority=request.librarian_routing_priority,
        librarian_enabled=request.librarian_enabled,
        created_at=now,
        updated_at=now,
    )


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    description="Librarian profile operation.",
    summary="Create agent",
)
@router_exception_status(LIBRARIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def create_agent(
    request: Annotated[
        AgentCreateRequest,
        Depends(model_validate_json_body(AgentCreateRequest)),
    ],
    service: Annotated[
        AgentService, Depends(Provide[ApplicationContainer.librarian.agent_service])
    ],
) -> AgentResponse:
    """Create an agent profile.

    Args:
        request [AgentCreateRequest]: Value supplied to create_agent.
        service [AgentService]: Value supplied to create_agent.

        request: Validated request for this operation.
        service: Application service used by this operation.
    Returns:
        AgentResponse: Value produced by create_agent.
    """
    model = await service.create_agent(_create_payload(request))
    return _to_response(model)


@router.get(
    "",
    response_model=AgentResponseList,
    description="Librarian profile operation.",
    status_code=status.HTTP_200_OK,
    summary="List agents",
)
@router_exception_status(LIBRARIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def list_agents(
    service: Annotated[
        AgentService, Depends(Provide[ApplicationContainer.librarian.agent_service])
    ],
) -> AgentResponseList:
    """List all agent profiles.

    Args:
        service [AgentService]: Value supplied to list_agents.

        service: Application service used by this operation.
    Returns:
        AgentResponseList: Value produced by list_agents.
    """
    rows = await service.list_agents()
    validation = AgentResponseList.model_validate(rows)
    return validation


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    description="Librarian profile operation.",
    status_code=status.HTTP_200_OK,
    summary="Get agent",
)
@router_exception_status(LIBRARIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_agent(
    agent_id: str,
    service: Annotated[
        AgentService, Depends(Provide[ApplicationContainer.librarian.agent_service])
    ],
) -> AgentResponse:
    """Get one profile.

    Args:
        agent_id [str]: Value supplied to get_agent.
        service [AgentService]: Value supplied to get_agent.

        agent_id: Identifier for agent.
        service: Application service used by this operation.
    Returns:
        AgentResponse: Value produced by get_agent.
    """
    model = await service.get_agent(agent_id)
    return _to_response(model)


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    description="Librarian profile operation.",
    status_code=status.HTTP_200_OK,
    summary="Patch agent",
)
@router_exception_status(LIBRARIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def patch_agent(
    agent_id: str,
    request: Annotated[
        AgentPatchRequest,
        Depends(model_validate_json_body(AgentPatchRequest)),
    ],
    service: Annotated[
        AgentService, Depends(Provide[ApplicationContainer.librarian.agent_service])
    ],
) -> AgentResponse:
    """Patch one profile.

    Args:
        agent_id [str]: Value supplied to patch_agent.
        request [AgentPatchRequest]: Value supplied to patch_agent.
        service [AgentService]: Value supplied to patch_agent.

        agent_id: Identifier for agent.
        request: Validated request for this operation.
        service: Application service used by this operation.
    Returns:
        AgentResponse: Value produced by patch_agent.
    """
    model = await service.update_agent(agent_id, request.to_payload())
    return _to_response(model)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description="Librarian profile operation.",
    summary="Delete agent",
)
@router_exception_status(LIBRARIAN_ROUTE_EXCEPTION_MAPPING)
@inject
async def delete_agent(
    agent_id: str,
    service: Annotated[
        AgentService, Depends(Provide[ApplicationContainer.librarian.agent_service])
    ],
) -> None:
    """Delete one profile.

    Args:
        agent_id [str]: Value supplied to delete_agent.
        service [AgentService]: Value supplied to delete_agent.
        agent_id: Identifier for agent.
        service: Application service used by this operation.
    """
    await service.delete_agent(agent_id)
