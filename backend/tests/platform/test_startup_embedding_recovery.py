"""Application startup embedding-recovery integration contract."""

from __future__ import annotations

import os

from pathlib import Path
from threading import Event

import anyio
import pytest
from app.main import app as default_app, create_app
from app.memory.domain.entities.context_read_models import ContextReindexResult
from app.platform.config.app_config import AppConfig
from app.shared.infrastructure.database import Database
from dependency_injector import providers
from fastapi.testclient import TestClient

_ROUTER_PACKAGES = [
    "app.connections.interface.routers",
    "app.memory.interface.routers",
    "app.obsidian.interface.routers",
    "app.operations.interface.routers",
]


class _FakeRecoveryService:
    def __init__(self, completed: Event) -> None:
        self._completed = completed

    async def recover(self, context_service: object) -> ContextReindexResult:
        assert context_service is _FAKE_CONTEXT_SERVICE
        self._completed.set()
        return ContextReindexResult(
            scanned=2,
            updated=2,
            skipped=0,
            warnings=(),
        )


_FAKE_CONTEXT_SERVICE = object()


async def _resolve_fake_context_service() -> object:
    return _FAKE_CONTEXT_SERVICE


def test_create_app_runs_enabled_embedding_recovery_after_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The startup task must await async container providers before recovery."""
    database_url = os.environ["DATABASE_URL"]

    async def prepare_database() -> None:
        database = Database(database_url=database_url, create_schema=True)
        await database.initialize()
        await database.shutdown()

    anyio.run(prepare_database)
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = AppConfig(
        _env_file=None,
        rag_embedding_recovery_on_startup=True,
        obsidian_vault_path=str(tmp_path / "vault"),
        obsidian_vault_config_path=str(tmp_path / "vault-config.json"),
    )
    app = create_app(config)
    completed = Event()

    try:
        with (
            app.state.container.memory.context_service.override(
                providers.Coroutine(_resolve_fake_context_service)
            ),
            app.state.container.memory.context_embedding_recovery_service.override(
                providers.Object(_FakeRecoveryService(completed))
            ),
            TestClient(app) as client,
        ):
            assert client.get("/health/ready").status_code == 200
            assert completed.wait(timeout=2)
    finally:
        default_app.state.container.wire(packages=_ROUTER_PACKAGES)
