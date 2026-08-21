"""Routes for librarian provider OAuth lifecycle operations."""

from typing import Annotated

from app.connections.application.librarians.oauth_service import LibrarianOAuthService
from app.connections.interface.schemas.librarian.oauth_schema import (
    LibrarianOAuthStartResponse,
    LibrarianOAuthStatusResponse,
)
from app.container import ApplicationContainer
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import CONNECTIONS_ROUTE_EXCEPTION_MAPPING
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

router = APIRouter(
    prefix="/settings/connections",
    tags=["librarians"],
)


@router.post(
    "/{provider_id}/oauth/start",
    response_model=LibrarianOAuthStartResponse,
    status_code=status.HTTP_200_OK,
    description="Librarian OAuth operation.",
    summary="Start librarian OAuth device flow",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def start_librarian_provider_oauth(
    provider_id: str,
    service: Annotated[
        LibrarianOAuthService,
        Depends(Provide[ApplicationContainer.connections.librarian_oauth_service]),
    ],
) -> LibrarianOAuthStartResponse:
    """Start OAuth device authorization for a provider.

    Args:
        provider_id: Provider id.
        service: OAuth lifecycle service.

    Returns:
        LibrarianOAuthStartResponse: Public device-flow instructions.
    """
    payload = await service.start_oauth(provider_id)
    validation = LibrarianOAuthStartResponse.model_validate(payload)
    return validation


@router.post(
    "/{provider_id}/oauth/poll",
    response_model=LibrarianOAuthStatusResponse,
    status_code=status.HTTP_200_OK,
    description="Librarian OAuth operation.",
    summary="Poll librarian OAuth device flow",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def poll_librarian_provider_oauth(
    provider_id: str,
    service: Annotated[
        LibrarianOAuthService,
        Depends(Provide[ApplicationContainer.connections.librarian_oauth_service]),
    ],
) -> LibrarianOAuthStatusResponse:
    """Poll OAuth device authorization and store tokens on success.

    Args:
        provider_id: Provider id.
        service: OAuth lifecycle service.

    Returns:
        LibrarianOAuthStatusResponse: Public OAuth status.
    """
    payload = await service.poll_oauth(provider_id)
    validation = LibrarianOAuthStatusResponse.model_validate(payload)
    return validation


@router.post(
    "/{provider_id}/oauth/refresh",
    response_model=LibrarianOAuthStatusResponse,
    status_code=status.HTTP_200_OK,
    description="Librarian OAuth operation.",
    summary="Refresh librarian OAuth token when needed",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def refresh_librarian_provider_oauth(
    provider_id: str,
    service: Annotated[
        LibrarianOAuthService,
        Depends(Provide[ApplicationContainer.connections.librarian_oauth_service]),
    ],
) -> LibrarianOAuthStatusResponse:
    """Refresh OAuth token only when current token is near expiry.

    Args:
        provider_id: Provider id.
        service: OAuth lifecycle service.

    Returns:
        LibrarianOAuthStatusResponse: Public OAuth status after refresh check.
    """
    payload = await service.refresh_if_needed(provider_id)
    validation = LibrarianOAuthStatusResponse.model_validate(payload)
    return validation


@router.get(
    "/{provider_id}/oauth/status",
    response_model=LibrarianOAuthStatusResponse,
    status_code=status.HTTP_200_OK,
    description="Librarian OAuth operation.",
    summary="Read librarian OAuth status",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_librarian_provider_oauth_status(
    provider_id: str,
    service: Annotated[
        LibrarianOAuthService,
        Depends(Provide[ApplicationContainer.connections.librarian_oauth_service]),
    ],
) -> LibrarianOAuthStatusResponse:
    """Read public OAuth connection state.

    Args:
        provider_id: Provider id.
        service: OAuth lifecycle service.

    Returns:
        LibrarianOAuthStatusResponse: Public OAuth status.
    """
    payload = await service.get_oauth_status(provider_id)
    validation = LibrarianOAuthStatusResponse.model_validate(payload)
    return validation
