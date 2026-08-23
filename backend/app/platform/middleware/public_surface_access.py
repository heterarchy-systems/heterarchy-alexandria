"""Restrict public hosts to the inbound MCP OAuth protocol surface."""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.shared.schemas.http_schemas import ProtocolErrorResponse
from app.shared.utils.http_helpers.response_headers import json_response

_LOCAL_HOSTS: Final[frozenset[str]] = frozenset(
    {"127.0.0.1", "localhost", "::1", "testserver"}
)
_PUBLIC_EXACT_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/approve",
        "/authorize",
        "/health/live",
        "/register",
        "/revoke",
        "/token",
    }
)
_PUBLIC_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/.well-known/openid-configuration",
    "/mcp",
)
_DENIED_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


def install_public_surface_access_middleware(app: FastAPI) -> None:
    """Allow public hosts to reach only MCP and OAuth protocol routes.

    Args:
        app: FastAPI application receiving the public-host boundary.

    Returns:
        None.
    """

    @app.middleware("http")
    async def public_surface_access_middleware(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Reject operator and backend routes received through a public host.

        Args:
            request: Incoming HTTP request.
            call_next: Next request handler in the middleware chain.

        Returns:
            Downstream response or a public-surface denial response.
        """
        if _is_local_request(request) or _is_public_protocol_path(request.url.path):
            return await call_next(request)
        return json_response(
            ProtocolErrorResponse(
                detail="Public host exposes MCP OAuth protocol routes only"
            ).model_dump_json(),
            status_code=403,
            headers=_DENIED_HEADERS,
        )


def _is_local_request(request: Request) -> bool:
    """Return whether local request.

    Args:
        request: Validated request for this operation.

    Returns:
        Whether local request.
    """
    return request.url.hostname in _LOCAL_HOSTS


def _is_public_protocol_path(path: str) -> bool:
    """Return whether public protocol path.

    Args:
        path: Path used by this operation.

    Returns:
        Whether public protocol path.
    """
    if path in _PUBLIC_EXACT_PATHS:
        return True
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in _PUBLIC_PATH_PREFIXES
    )
