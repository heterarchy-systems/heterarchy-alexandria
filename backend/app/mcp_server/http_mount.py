"""ASGI mount helpers for the heterarchy-alexandria HTTP MCP endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.types import ASGIApp, Receive, Scope, Send

from app.mcp_server.backend_api_client import AlexandriaApiClient
from app.mcp_server.http_auth_gate import McpHttpAuthGate
from app.mcp_server.local_oauth.runtime import LocalMcpOAuthRuntime
from app.mcp_server.server_runtime import (
    DEFAULT_MCP_TRANSPORT_HOST,
    build_mcp_server,
    mcp_transport_security,
)
from app.shared.schemas.http_schemas import ProtocolErrorResponse
from app.shared.utils.http_helpers.response_headers import json_response

MCP_HTTP_MOUNT_PATH = "/"
MCP_PUBLIC_PATH = "/mcp"


class McpHttpMount:
    """Restart-safe ASGI delegate for the mounted FastMCP HTTP app."""

    def __init__(self, auth_gate: McpHttpAuthGate) -> None:
        """Create the guarded MCP mount delegate.

        Args:
            auth_gate: Public MCP request authorization gate.
        """
        self._auth_gate = auth_gate
        self._app: ASGIApp | None = None

    def set_app(self, app: ASGIApp | None) -> None:
        """Set the currently running FastMCP ASGI app.

        Args:
            app: Mounted app for the current FastAPI lifespan, or None at shutdown.
        """
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Delegate an unmatched FastAPI request to the active MCP app.

        Args:
            scope: ASGI request scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if _is_public_mcp_request(scope):
            auth_result = await self._auth_gate.authorize(scope)
            if not auth_result.allowed:
                response = json_response(
                    ProtocolErrorResponse(detail=auth_result.detail).model_dump_json(),
                    status_code=auth_result.status_code,
                    headers=dict(auth_result.headers),
                )
                await response(scope, receive, send)
                return
        if self._app is None:
            response = json_response(
                ProtocolErrorResponse(
                    detail="MCP server is not running"
                ).model_dump_json(),
                503,
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


@asynccontextmanager
async def mcp_streamable_http_lifespan(
    client: AlexandriaApiClient | None = None,
    transport_host: str = DEFAULT_MCP_TRANSPORT_HOST,
    local_oauth_runtime: LocalMcpOAuthRuntime | None = None,
) -> AsyncIterator[ASGIApp]:
    """Run one restart-safe FastMCP Streamable HTTP app lifespan.

    Args:
        client: Optional backend API client for tests.
        transport_host: Host value used by FastMCP transport security.
        local_oauth_runtime: Optional self-hosted OAuth provider and settings.

    Yields:
        Active FastMCP Streamable HTTP app.
    """
    server = build_mcp_server(
        client=client,
        local_oauth_runtime=local_oauth_runtime,
    )
    mcp_app = server.streamable_http_app(
        streamable_http_path=MCP_PUBLIC_PATH,
        json_response=True,
        transport_security=mcp_transport_security(transport_host),
        host=transport_host,
    )
    async with server.session_manager.run():
        yield mcp_app


def _is_public_mcp_request(scope: Scope) -> bool:
    """Return whether public mcp request.

    Args:
        scope: Scope used by this operation.

    Returns:
        Whether public mcp request.
    """
    if scope["type"] != "http":
        return False
    path = str(scope.get("path", ""))
    return path == MCP_PUBLIC_PATH or path.startswith(f"{MCP_PUBLIC_PATH}/")
