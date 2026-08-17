"""Build MCP OAuth protected-resource metadata payloads."""

from __future__ import annotations

from starlette.requests import Request

from app.mcp_server.http_mount import MCP_PUBLIC_PATH
from app.mcp_server.interface.schemas.protected_resource_schemas import (
    McpProtectedResourceMetadata,
)
from app.platform.config.app_config import AppConfig
from app.shared.types.extra_types import JSONObject


def request_origin(request: Request) -> str:
    """Return the public request origin inferred from proxy-aware request data.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Public scheme and host origin.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"


def mcp_resource_url(request: Request) -> str:
    """Return the public MCP resource URL for metadata and challenges.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Public MCP endpoint URL.
    """
    return f"{request_origin(request)}{MCP_PUBLIC_PATH}"


def protected_resource_metadata(request: Request, config: AppConfig) -> JSONObject:
    """Build validated OAuth protected-resource metadata for ChatGPT.

    Args:
        request: Incoming FastAPI request.
        config: Application configuration.

    Returns:
        JSON object containing protected-resource metadata.
    """
    scopes = config.mcp_oauth_required_scopes()
    payload = McpProtectedResourceMetadata(
        resource=config.mcp_oauth_resource or mcp_resource_url(request),
        authorization_servers=tuple(config.mcp_oauth_authorization_server_urls()),
        scopes_supported=scopes,
        resource_documentation="heterarchy-alexandria MCP server for librarian tools.",
    )
    return payload.model_dump(mode="json")
