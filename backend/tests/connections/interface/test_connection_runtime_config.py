"""Connection status uses the configured runtime without reloading the environment."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.config_test_data import app_config_values, mcp_config_values

from app.connections.interface.routers.connection_hub_router import router
from app.platform.config.app_config import AppConfig
from app.platform.config.mcp_config import McpConfig


@pytest.mark.parametrize("configured", [True, False])
def test_connection_status_uses_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
    configured: bool,
) -> None:
    """Explicit runtime settings work without ambient configuration; absence is 503."""
    monkeypatch.setitem(AppConfig.model_config, "env_file", None)
    monkeypatch.setitem(McpConfig.model_config, "env_file", None)
    monkeypatch.delenv("ALEXANDRIA_OPERATOR_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(router)
    if configured:
        app.state.app_config = AppConfig(_env_file=None, **app_config_values())
        app.state.mcp_config = McpConfig(_env_file=None, **mcp_config_values())

    with TestClient(app) as client:
        response = client.get("/connect/status")

    assert response.status_code == (200 if configured else 503)
    if configured:
        assert response.json()["app_env"] == "local"
        assert response.json()["mcp_endpoint"] == "http://testserver/mcp"
