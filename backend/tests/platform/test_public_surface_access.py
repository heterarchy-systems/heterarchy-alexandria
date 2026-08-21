"""Public-host access boundaries for the locally operated backend."""

from __future__ import annotations

from app.main import app as default_app, create_app
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.platform.config.app_config import AppConfig
from app.platform.middleware.public_surface_access import (
    install_public_surface_access_middleware,
)
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

_ROUTER_PACKAGES = [
    "app.connections.interface.routers",
    "app.librarian.interface.routers",
    "app.memory.interface.routers",
    "app.obsidian.interface.routers",
    "app.operations.interface.routers",
]


def _create_public_oauth_test_app() -> FastAPI:
    """Build the public-surface test app with local OAuth explicitly enabled."""
    return create_app(
        AppConfig(
            _env_file=None,
            mcp_auth_mode=McpAuthMode.LOCAL_OAUTH2,
            mcp_oauth_issuer="https://alexandria.example",
            mcp_oauth_resource="https://alexandria.example/mcp",
            mcp_local_approval_key="test-approval-key-24-chars",
        )
    )


def _create_local_access_test_app() -> FastAPI:
    test_app = FastAPI()
    install_public_surface_access_middleware(test_app)

    @test_app.get("/settings/connections")
    async def local_management_route() -> Response:
        return Response(status_code=204)

    return test_app


def test_public_host_exposes_only_mcp_oauth_protocol_routes() -> None:
    """A tunnel host must not expose operator UI or backend management APIs."""
    test_app = _create_public_oauth_test_app()
    try:
        with TestClient(test_app, base_url="https://alexandria.example") as client:
            blocked = {
                "/": client.get("/"),
                "/connect": client.get("/connect"),
                "/connect/status": client.get("/connect/status"),
                "/settings/connections": client.get("/settings/connections"),
                "/operations/readiness": client.get("/operations/readiness"),
                "/docs": client.get("/docs"),
            }
            live = client.get("/health/live")
            authorization_metadata = client.get(
                "/.well-known/oauth-authorization-server"
            )
            resource_metadata = client.get("/.well-known/oauth-protected-resource/mcp")
            unauthenticated_mcp = client.get("/mcp")
    finally:
        default_app.state.container.wire(packages=_ROUTER_PACKAGES)

    assert {path: response.status_code for path, response in blocked.items()} == {
        "/": 403,
        "/connect": 403,
        "/connect/status": 403,
        "/settings/connections": 403,
        "/operations/readiness": 403,
        "/docs": 403,
    }
    assert all(
        response.headers["cache-control"] == "no-store" for response in blocked.values()
    )
    assert live.status_code == 200
    assert authorization_metadata.status_code == 200
    assert resource_metadata.status_code == 200
    assert unauthenticated_mcp.status_code == 401


def test_localhost_retains_operator_surface_access() -> None:
    """A local host must bypass the public-host restriction."""
    with TestClient(_create_local_access_test_app()) as client:
        response = client.get("/settings/connections")

    assert response.status_code == 204
