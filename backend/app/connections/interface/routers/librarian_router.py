"""Routes for librarian provider settings and operations."""

from typing import Annotated

from app.connections.application.librarian_service import LibrarianService
from app.connections.interface.schemas.librarian.provider_schema import (
    LibrarianProviderCreateRequest,
    LibrarianProviderPatchRequest,
    LibrarianProviderResponse,
    LibrarianProviderResponseList,
    LibrarianProviderTestRequest,
    LibrarianProviderTestResponse,
)
from app.container import ApplicationContainer
from app.shared.exceptions.exception_decorators import router_exception_status
from app.shared.exceptions.route_exceptions import (
    CONNECTIONS_PROVIDER_TEST_EXCEPTION_MAPPING,
    CONNECTIONS_ROUTE_EXCEPTION_MAPPING,
)
from app.shared.type_validation.strict_json_body import model_validate_json_body
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(
    prefix="/settings/connections",
    tags=["librarians"],
)


@router.post(
    "",
    response_model=LibrarianProviderResponse,
    status_code=status.HTTP_201_CREATED,
    description="Librarian provider operation.",
    summary="Create librarian provider",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def create_librarian_provider(
    request: Annotated[
        LibrarianProviderCreateRequest,
        Depends(model_validate_json_body(LibrarianProviderCreateRequest)),
    ],
    service: Annotated[
        LibrarianService,
        Depends(Provide[ApplicationContainer.connections.librarian_service]),
    ],
) -> LibrarianProviderResponse:
    """Create provider settings.

    Args:
        request [LibrarianProviderCreateRequest]: Value supplied to create_librarian_provider.
        service [LibrarianService]: Value supplied to create_librarian_provider.

    Returns:
        LibrarianProviderResponse: Value produced by create_librarian_provider.
    """
    payload = await service.create_provider(
        name=request.name,
        provider_type=request.provider_type,
        auth_type=request.auth_type,
        enabled=request.enabled,
        config=request.config,
        api_key=request.api_key,
        oauth_access_token=request.oauth_access_token,
    )
    validation = LibrarianProviderResponse.model_validate(payload)
    return validation


@router.get(
    "",
    response_model=LibrarianProviderResponseList,
    description="Librarian provider operation.",
    status_code=status.HTTP_200_OK,
    summary="List librarian providers",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def list_librarian_providers(
    service: Annotated[
        LibrarianService,
        Depends(Provide[ApplicationContainer.connections.librarian_service]),
    ],
) -> LibrarianProviderResponseList:
    """List all configured providers.

    Args:
        service [LibrarianService]: Value supplied to list_librarian_providers.

    Returns:
        LibrarianProviderResponseList: Value produced by list_librarian_providers.
    """
    payloads = await service.list_providers()
    validation = LibrarianProviderResponseList.model_validate(payloads)
    return validation


@router.get(
    "/{provider_id}",
    response_model=LibrarianProviderResponse,
    description="Librarian provider operation.",
    status_code=status.HTTP_200_OK,
    summary="Get librarian provider",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def get_librarian_provider(
    provider_id: str,
    service: Annotated[
        LibrarianService,
        Depends(Provide[ApplicationContainer.connections.librarian_service]),
    ],
) -> LibrarianProviderResponse:
    """Read one provider by id.

    Args:
        provider_id [str]: Value supplied to get_librarian_provider.
        service [LibrarianService]: Value supplied to get_librarian_provider.

    Returns:
        LibrarianProviderResponse: Value produced by get_librarian_provider.
    """
    payload = await service.get_provider(provider_id)
    validation = LibrarianProviderResponse.model_validate(payload)
    return validation


@router.patch(
    "/{provider_id}",
    response_model=LibrarianProviderResponse,
    description="Librarian provider operation.",
    status_code=status.HTTP_200_OK,
    summary="Patch librarian provider",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def patch_librarian_provider(
    provider_id: str,
    request: Annotated[
        LibrarianProviderPatchRequest,
        Depends(model_validate_json_body(LibrarianProviderPatchRequest)),
    ],
    service: Annotated[
        LibrarianService,
        Depends(Provide[ApplicationContainer.connections.librarian_service]),
    ],
) -> LibrarianProviderResponse:
    """Patch provider settings.

    Args:
        provider_id [str]: Value supplied to patch_librarian_provider.
        request [LibrarianProviderPatchRequest]: Value supplied to patch_librarian_provider.
        service [LibrarianService]: Value supplied to patch_librarian_provider.

    Returns:
        LibrarianProviderResponse: Value produced by patch_librarian_provider.
    """
    payload = request.to_payload()
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided",
        )
    updated = await service.update_provider(
        provider_id,
        payload=payload,
    )
    validation = LibrarianProviderResponse.model_validate(updated)
    return validation


@router.delete(
    "/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description="Librarian provider operation.",
    summary="Delete librarian provider",
)
@router_exception_status(CONNECTIONS_ROUTE_EXCEPTION_MAPPING)
@inject
async def delete_librarian_provider(
    provider_id: str,
    service: Annotated[
        LibrarianService,
        Depends(Provide[ApplicationContainer.connections.librarian_service]),
    ],
) -> None:
    """Delete provider and associated secrets.

    Args:
        provider_id [str]: Value supplied to delete_librarian_provider.
        service [LibrarianService]: Value supplied to delete_librarian_provider.
    """
    await service.delete_provider(provider_id)


@router.post(
    "/{provider_id}/test",
    response_model=LibrarianProviderTestResponse,
    description="Librarian provider operation.",
    status_code=status.HTTP_200_OK,
    summary="Test librarian provider",
)
@router_exception_status(CONNECTIONS_PROVIDER_TEST_EXCEPTION_MAPPING)
@inject
async def test_librarian_provider(
    provider_id: str,
    request: Annotated[
        LibrarianProviderTestRequest,
        Depends(model_validate_json_body(LibrarianProviderTestRequest)),
    ],
    service: Annotated[
        LibrarianService,
        Depends(Provide[ApplicationContainer.connections.librarian_service]),
    ],
) -> LibrarianProviderTestResponse:
    """Run quick provider validation.

    Args:
        provider_id [str]: Value supplied to test_librarian_provider.
        request [LibrarianProviderTestRequest]: Value supplied to test_librarian_provider.
        service [LibrarianService]: Value supplied to test_librarian_provider.

    Returns:
        LibrarianProviderTestResponse: Value produced by test_librarian_provider.
    """
    result = await service.test_provider(
        provider_id,
        test_query=request.test_query,
    )
    validation = LibrarianProviderTestResponse.model_validate(result)
    return validation
