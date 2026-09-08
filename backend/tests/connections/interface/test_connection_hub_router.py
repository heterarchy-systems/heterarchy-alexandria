"""Connection hub browser surface contracts."""

from __future__ import annotations

from app.main import app
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.platform.config.app_config import AppConfig
from fastapi.testclient import TestClient


def test_connection_hub_page_has_secure_external_assets() -> None:
    """Hub HTML should be browser-ready without inline script or secret fields."""
    with TestClient(app) as client:
        response = client.get("/connect")
        script = client.get("/connect/assets/connection-hub.js")
        stylesheet = client.get("/connect/assets/connection-hub.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "<script src=" in response.text
    assert "<script>" not in response.text
    assert "operator_key" not in response.text
    assert "OpenAI Librarian" not in response.text
    assert "MCP 클라이언트 관리" in response.text
    assert "목록 새로고침" not in response.text
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")


def test_mcp_management_page_is_dedicated_and_localhost_only() -> None:
    """MCP client administration should live on a separate localhost-only page."""
    with TestClient(app) as client:
        response = client.get("/connect/mcp")
        script = client.get("/connect/assets/mcp-clients.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "<script src=" in response.text
    assert "<script>" not in response.text
    assert "OAuth 연결 클라이언트" in response.text
    assert "localhost 관리자 표면" in response.text
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "disconnected" not in script.text.lower()

    with TestClient(app, base_url="https://alexandria.example") as remote_client:
        remote_response = remote_client.get("/connect/mcp")

    assert remote_response.status_code == 403


def test_connection_hub_status_redacts_runtime_secrets() -> None:
    """Hub status should expose connection metadata but no credential material."""
    with TestClient(app) as client:
        response = client.get("/connect/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mcp_endpoint"].endswith("/mcp")
    assert payload["local_only"] is True
    assert "token" not in response.text.lower()
    assert "approval_key" not in response.text.lower()


def test_connection_hub_status_prefers_configured_public_mcp_resource() -> None:
    """The copyable endpoint must use the public OAuth resource, not localhost."""
    with TestClient(app) as client:
        previous = getattr(app.state, "app_config", None)
        app.state.app_config = AppConfig(
            _env_file=None,
            mcp_auth_mode=McpAuthMode.LOCAL_OAUTH2,
            mcp_oauth_issuer="https://alexandria.example",
            mcp_oauth_resource="https://alexandria.example/mcp",
            mcp_local_approval_key="test-approval-key-24-chars",
        )
        try:
            response = client.get("/connect/status")
        finally:
            if previous is None:
                delattr(app.state, "app_config")
            else:
                app.state.app_config = previous

    assert response.status_code == 200
    assert response.json()["mcp_endpoint"] == "https://alexandria.example/mcp"
