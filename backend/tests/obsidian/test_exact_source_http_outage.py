"""Cold-start source access through real HTTP/DI with PostgreSQL unavailable."""

import socket
from pathlib import Path

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from app.main import create_app
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.platform.config.app_config import AppConfig
from app.platform.config.database_config import DatabaseConfig
from app.platform.config.redis_config import RedisConfig

pytestmark = pytest.mark.usefixtures("restore_default_app_wiring")


def test_exact_source_http_remains_readable_when_database_cannot_connect(
    tmp_path: Path,
) -> None:
    """A failed metadata connection cannot hide already durable local Markdown."""
    vault = tmp_path / "vault"
    managed = vault / "Alexandria"
    managed.mkdir(parents=True)
    (managed / "source.md").write_text(
        "---\nid: cold-source\nalexandria_type: job_plan\n"
        "title: Durable source\nstatus: active\n---\n# Durable source\n"
        "Canonical evidence survives projection failure.\n",
        encoding="utf-8",
    )
    config = AppConfig(
        _env_file=None,
        obsidian_vault_path=str(vault),
        alexandria_obsidian_root="Alexandria",
        obsidian_vault_config_path=str(tmp_path / "vault-config.json"),
        rag_embedding_recovery_on_startup=False,
        mcp_auth_mode=McpAuthMode.NONE,
    )
    application = create_app(config)
    with socket.socket() as unavailable:
        # A bound socket without listen reliably refuses TCP connections while
        # reserving this isolated endpoint for the duration of the test.
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        database_config = DatabaseConfig(
            _env_file=None,
            url=f"postgresql+asyncpg://test:test@127.0.0.1:{port}/unavailable",
        )
        with (
            application.state.container.database_config.override(
                providers.Object(database_config)
            ),
            application.state.container.redis_config.override(
                providers.Object(RedisConfig(_env_file=None, url=None))
            ),
            TestClient(application, raise_server_exceptions=False) as client,
        ):
            by_path = client.get(
                "/obsidian/notes/by-path", params={"path": "Alexandria/source.md"}
            )
            by_id = client.get("/obsidian/notes/cold-source")
            missing = client.get("/obsidian/notes/not-present")
    for response in (by_path, by_id):
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["id"] == "cold-source"
        assert "Canonical evidence" in payload["body"]
        assert payload["index_status"] == "unindexed"
        assert payload["indexed_at"] is None
        assert payload["error_message"] == "INDEX_METADATA_UNAVAILABLE"
    assert missing.status_code == 404
