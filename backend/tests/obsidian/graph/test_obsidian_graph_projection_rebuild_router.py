"""FastAPI contracts for canonical PostgreSQL graph projection status."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
from fastapi.testclient import TestClient

from app.main import app as default_app, create_app
from app.platform.config.app_config import AppConfig
from app.shared.infrastructure.database import Database

_ROUTER_PACKAGES = [
    "app.connections.interface.routers",
    "app.memory.interface.routers",
    "app.obsidian.interface.routers",
    "app.operations.interface.routers",
]


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


def test_projection_status_uses_postgresql_graph_authority(tmp_path: Path) -> None:
    """Graph status should be available without any external graph service."""
    database_url = _database_url()
    database = Database(database_url=database_url, create_schema=True)
    anyio.run(database.initialize)
    anyio.run(database.shutdown)

    app = create_app(
        AppConfig(
            _env_file=None,
            obsidian_vault_path=str(tmp_path / "vault"),
            obsidian_vault_config_path=str(tmp_path / "vault-config.json"),
            operational_backup_root=str(tmp_path / "backups"),
        )
    )

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/obsidian/graph/projection/status")
    finally:
        default_app.state.container.wire(packages=_ROUTER_PACKAGES)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["graph_read_model"] == "postgresql"
    assert payload["enabled"] is True
    assert payload["node_count"] == 0
    assert payload["edge_count"] == 0
    assert payload["projection_version"] == 1
    assert payload["errors"] == []
