"""FastAPI assembly tests for the local MCP OAuth mode."""

from __future__ import annotations

import os

from pathlib import Path

import anyio
import pytest
from app.main import app as default_app, create_app
from app.platform.config.app_config import AppConfig
from app.shared.infrastructure.database import Database
from fastapi.testclient import TestClient

ISSUER = "http://localhost"
RESOURCE = "http://localhost/mcp"
APPROVAL_KEY = "local-approval-key-with-32-characters"
_ROUTER_PACKAGES = [
    "app.connections.interface.routers",
    "app.librarian.interface.routers",
    "app.memory.interface.routers",
    "app.obsidian.interface.routers",
    "app.operations.interface.routers",
]


def test_create_app_exposes_local_oauth_routes_without_shadowing_rest_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root fallback mounting should preserve FastAPI and expose OAuth endpoints."""
    database_url = os.environ["DATABASE_URL"]

    async def prepare_database() -> None:
        database = Database(database_url=database_url, create_schema=True)
        await database.initialize()
        await database.shutdown()

    anyio.run(prepare_database)
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = AppConfig(
        _env_file=None,
        mcp_auth_mode="local_oauth2",
        mcp_oauth_issuer=ISSUER,
        mcp_oauth_resource=RESOURCE,
        mcp_local_approval_key=APPROVAL_KEY,
    )
    app = create_app(config)

    try:
        with TestClient(app, base_url=ISSUER) as client:
            root = client.get("/")
            authorization_metadata = client.get(
                "/.well-known/oauth-authorization-server"
            )
            protected_metadata = client.get("/.well-known/oauth-protected-resource")
            registration = client.post(
                "/register",
                json={
                    "redirect_uris": ["https://chatgpt.com/oauth/callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "scope": "alexandria:mcp offline_access",
                    "client_name": "ChatGPT",
                },
            )
            pairing = client.post("/connect/mcp/pairing-code")
            oauth_clients = client.get("/connect/mcp/clients")
            client_id = registration.json()["client_id"]
            extend_registered = client.post(f"/connect/mcp/clients/{client_id}/extend")
            disconnect_registered = client.post(
                f"/connect/mcp/clients/{client_id}/disconnect"
            )
            oauth_clients_after_disconnect = client.get("/connect/mcp/clients")
            remote_page = client.get(
                "/connect/mcp",
                headers={"host": "alexandria.example"},
            )
    finally:
        default_app.state.container.wire(packages=_ROUTER_PACKAGES)

    assert root.status_code == 200
    assert root.json()["service"] == "heterarchy-alexandria"
    assert authorization_metadata.status_code == 200
    assert authorization_metadata.json()["authorization_endpoint"] == (
        f"{ISSUER}/authorize"
    )
    assert protected_metadata.status_code == 200
    assert protected_metadata.json()["resource"] == RESOURCE
    assert registration.status_code == 201
    assert pairing.status_code == 201
    assert len(pairing.json()["code"]) == 9
    assert "token" not in pairing.text.lower()
    assert oauth_clients.status_code == 200
    oauth_client = oauth_clients.json()["clients"][0]
    assert oauth_client["client_name"] == "ChatGPT"
    assert oauth_client["status"] == "registered"
    assert oauth_client["connected"] is False
    assert oauth_client["supports_disconnect"] is True
    assert oauth_client["supports_extension"] is False
    assert extend_registered.status_code == 409
    assert disconnect_registered.status_code == 204
    assert disconnect_registered.content == b""
    assert oauth_clients_after_disconnect.json()["clients"] == []
    assert remote_page.status_code == 403
