"""Server-rendered connection hub for local Alexandria operators."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

from app.connections.interface.schemas.connection_hub_schema import (
    ConnectionHubStatusResponse,
    McpOAuthClientConnectionListResponse,
    McpOAuthClientConnectionResponse,
    McpPairingCodeResponse,
)
from app.container import ApplicationContainer
from app.mcp_server.local_oauth.contracts import LocalOAuthClientConnectionRecord
from app.mcp_server.local_oauth.local_oauth_enums import (
    LocalOAuthClientConnectionStatus,
)
from app.mcp_server.local_oauth.provider import LocalMcpOAuthProvider
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.platform.config.app_config import AppConfig
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

router = APIRouter(tags=["connection-hub"])

_INTERFACE_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_HUB_HTML: Final[Path] = _INTERFACE_ROOT / "templates" / "connection_hub.html"
_MCP_CLIENTS_HTML: Final[Path] = _INTERFACE_ROOT / "templates" / "mcp_clients.html"
_HUB_CSS: Final[Path] = _INTERFACE_ROOT / "static" / "connection_hub.css"
_HUB_JS: Final[Path] = _INTERFACE_ROOT / "static" / "connection_hub.js"
_MCP_CLIENTS_JS: Final[Path] = _INTERFACE_ROOT / "static" / "mcp_clients.js"
_PAGE_SECURITY_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
_ASSET_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


@router.get(
    "/connect",
    response_class=FileResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def connection_hub_page() -> FileResponse:
    """Return the local connection hub page.

    Returns:
        Hardened HTML file response.
    """
    return FileResponse(
        _HUB_HTML,
        media_type="text/html; charset=utf-8",
        headers=_PAGE_SECURITY_HEADERS,
    )


@router.get(
    "/connect/mcp",
    response_class=FileResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def mcp_client_management_page(request: Request) -> FileResponse:
    """Return the dedicated MCP OAuth client management page.

    Args:
        request: Active FastAPI request.

    Returns:
        Hardened HTML file response.
    """
    _require_local_management_request(request)
    return FileResponse(
        _MCP_CLIENTS_HTML,
        media_type="text/html; charset=utf-8",
        headers=_PAGE_SECURITY_HEADERS,
    )


@router.get(
    "/connect/assets/connection-hub.css",
    response_class=FileResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def connection_hub_stylesheet() -> FileResponse:
    """Return the connection hub stylesheet.

    Returns:
        No-store CSS file response.
    """
    return FileResponse(
        _HUB_CSS,
        media_type="text/css; charset=utf-8",
        headers=_ASSET_HEADERS,
    )


@router.get(
    "/connect/assets/connection-hub.js",
    response_class=FileResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def connection_hub_script() -> FileResponse:
    """Return the connection hub browser controller.

    Returns:
        No-store JavaScript file response.
    """
    return FileResponse(
        _HUB_JS,
        media_type="text/javascript; charset=utf-8",
        headers=_ASSET_HEADERS,
    )


@router.get(
    "/connect/assets/mcp-clients.js",
    response_class=FileResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def mcp_clients_script() -> FileResponse:
    """Return the MCP client management browser controller.

    Returns:
        No-store JavaScript file response.
    """
    return FileResponse(
        _MCP_CLIENTS_JS,
        media_type="text/javascript; charset=utf-8",
        headers=_ASSET_HEADERS,
    )


@router.get(
    "/connect/status",
    response_model=ConnectionHubStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Read connection hub runtime status",
)
def connection_hub_status(request: Request) -> ConnectionHubStatusResponse:
    """Return non-secret runtime details for the connection page.

    Args:
        request: Active FastAPI request.

    Returns:
        Public connection state without credentials.
    """
    config = _request_app_config(request, AppConfig())
    host = request.url.hostname or ""
    request_mcp_endpoint = str(request.base_url).rstrip("/") + "/mcp"
    return ConnectionHubStatusResponse(
        app_env=config.app_env,
        mcp_auth_mode=config.mcp_auth_mode,
        mcp_endpoint=config.mcp_oauth_resource or request_mcp_endpoint,
        mcp_oauth_enabled=config.mcp_auth_mode is McpAuthMode.LOCAL_OAUTH2,
        mcp_oauth_issuer=config.mcp_oauth_issuer,
        local_only=host in {"127.0.0.1", "localhost", "::1", "testserver"},
    )


@router.post(
    "/connect/mcp/pairing-code",
    response_model=McpPairingCodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a one-time MCP pairing code",
)
@inject
async def create_mcp_pairing_code(
    request: Request,
    configured_app: Annotated[
        AppConfig, Depends(Provide[ApplicationContainer.app_config])
    ],
) -> McpPairingCodeResponse:
    """Create one local-only, short-lived approval code for MCP OAuth.

    Args:
        request: Active FastAPI request.
        configured_app: Dependency-injected configuration fallback.

    Returns:
        One-time pairing code and expiration.
    """
    _require_local_management_request(request)
    config = _request_app_config(request, configured_app)
    if config.mcp_auth_mode is not McpAuthMode.LOCAL_OAUTH2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MCP local OAuth is not enabled",
        )
    provider = _request_oauth_provider(request)
    if not isinstance(provider, LocalMcpOAuthProvider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP local OAuth is still starting",
        )
    pairing = await provider.create_pairing_code()
    return McpPairingCodeResponse(
        code=pairing.code,
        expires_at=datetime.fromtimestamp(pairing.expires_at, tz=UTC),
    )


@router.get(
    "/connect/mcp/clients",
    response_model=McpOAuthClientConnectionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List MCP OAuth client connections",
)
@inject
async def list_mcp_oauth_clients(
    request: Request,
    configured_app: Annotated[
        AppConfig, Depends(Provide[ApplicationContainer.app_config])
    ],
) -> McpOAuthClientConnectionListResponse:
    """Return OAuth clients registered against the local MCP endpoint.

    Args:
        request: Active FastAPI request.
        configured_app: Dependency-injected configuration fallback.

    Returns:
        Public-safe client records without token material.
    """
    provider = _local_oauth_provider(request, configured_app)
    connections = await provider.list_client_connections()
    return McpOAuthClientConnectionListResponse(
        clients=[_connection_response(connection) for connection in connections],
        extension_policy=(
            "Each extension adds the configured local OAuth TTL to the current "
            "refresh-token expiry; unlimited bearer tokens are not exposed."
        ),
    )


@router.post(
    "/connect/mcp/clients/{client_id}/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect one MCP OAuth client",
)
@inject
async def disconnect_mcp_oauth_client(
    client_id: str,
    request: Request,
    configured_app: Annotated[
        AppConfig, Depends(Provide[ApplicationContainer.app_config])
    ],
) -> None:
    """Hard-delete one MCP OAuth client and all related credential state.

    Args:
        client_id: Registered OAuth client id.
        request: Active FastAPI request.
        configured_app: Dependency-injected configuration fallback.

    """
    provider = _local_oauth_provider(request, configured_app)
    deleted = await provider.delete_client_connection(client_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP OAuth client is not registered",
        )


@router.post(
    "/connect/mcp/clients/{client_id}/extend",
    response_model=McpOAuthClientConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Extend one MCP OAuth client connection",
)
@inject
async def extend_mcp_oauth_client(
    client_id: str,
    request: Request,
    configured_app: Annotated[
        AppConfig, Depends(Provide[ApplicationContainer.app_config])
    ],
) -> McpOAuthClientConnectionResponse:
    """Extend active refresh tokens for one connected MCP OAuth client.

    Args:
        client_id: Registered OAuth client id.
        request: Active FastAPI request.
        configured_app: Dependency-injected configuration fallback.

    Returns:
        Updated public-safe client connection state.
    """
    provider = _local_oauth_provider(request, configured_app)
    connection = await provider.extend_client_connection(client_id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MCP OAuth client must reconnect before it can be extended",
        )
    return _connection_response(connection)


def _local_oauth_provider(
    request: Request,
    configured_app: AppConfig,
) -> LocalMcpOAuthProvider:
    _require_local_management_request(request)
    config = _request_app_config(request, configured_app)
    if config.mcp_auth_mode is not McpAuthMode.LOCAL_OAUTH2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MCP local OAuth is not enabled",
        )
    provider = _request_oauth_provider(request)
    if not isinstance(provider, LocalMcpOAuthProvider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP local OAuth is still starting",
        )
    return provider


def _request_app_config(request: Request, fallback: AppConfig) -> AppConfig:
    try:
        config = request.app.state.app_config
    except AttributeError:
        return fallback
    return config if isinstance(config, AppConfig) else fallback


def _request_oauth_provider(request: Request) -> LocalMcpOAuthProvider | None:
    try:
        provider = request.app.state.local_mcp_oauth_provider
    except AttributeError:
        return None
    return provider if isinstance(provider, LocalMcpOAuthProvider) else None


def _require_local_management_request(request: Request) -> None:
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MCP OAuth management is restricted to localhost",
        )


def _connection_response(
    connection: LocalOAuthClientConnectionRecord,
) -> McpOAuthClientConnectionResponse:
    return McpOAuthClientConnectionResponse(
        client_id=connection.client_id,
        client_name=connection.client_name,
        status=connection.status,
        connected=connection.connected,
        scopes=list(connection.scopes),
        resource=connection.resource,
        issued_at=_datetime_from_epoch(connection.issued_at),
        access_token_expires_at=_optional_datetime_from_epoch(
            connection.access_token_expires_at
        ),
        refresh_token_expires_at=_optional_datetime_from_epoch(
            connection.refresh_token_expires_at
        ),
        active_token_families=connection.active_token_families,
        supports_disconnect=True,
        supports_extension=connection.status
        is LocalOAuthClientConnectionStatus.CONNECTED,
    )


def _datetime_from_epoch(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def _optional_datetime_from_epoch(epoch: int | None) -> datetime | None:
    return None if epoch is None else _datetime_from_epoch(epoch)
