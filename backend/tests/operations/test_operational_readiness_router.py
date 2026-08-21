"""Operational readiness router contracts."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from app.main import app as default_app, create_app
from app.memory.domain.entities.context_read_models import (
    ContextEmbeddingSourceStatus,
    RagDependencyHealth,
)
from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationDiagnostics,
)
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.application.readiness.operational_readiness_cache import (
    NoopOperationalReadinessCache,
)
from app.operations.interface.routers.operational_readiness_router import (
    operational_capabilities,
    operational_readiness,
)
from app.platform.config.app_config import AppConfig
from app.shared.infrastructure.database import Database
from dependency_injector import providers
from fastapi.testclient import TestClient

_ROUTER_PACKAGES = [
    "app.connections.interface.routers",
    "app.librarian.interface.routers",
    "app.memory.interface.routers",
    "app.obsidian.interface.routers",
    "app.operations.interface.routers",
]


class _FakeContextService:
    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=RagHealthState.REINDEX_REQUIRED,
            default_strategy=RagStrategy.FTS_ONLY,
            model_name="test-model",
            dimensions=3,
            fingerprint={"provider": "test"},
            warnings=["embedding mismatch"],
            source_statuses=[
                ContextEmbeddingSourceStatus(
                    source_name="obsidian_vault",
                    status=RagHealthState.REINDEX_REQUIRED,
                    total_rows=459,
                    current_rows=0,
                    stale_rows=459,
                    missing_rows=459,
                    current_fingerprint={"provider": "test"},
                    stored_fingerprints=[],
                )
            ],
        )


class _FakeObsidianService:
    def __init__(self, tmp_path: Path) -> None:
        self._tmp_path = tmp_path

    def vault_location(self) -> SimpleNamespace:
        vault = self._tmp_path / "vault"
        (vault / "Alexandria").mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            vault_path=str(vault),
            alexandria_root="Alexandria",
        )

    async def status(self) -> ObsidianVaultStatus:
        vault = self._tmp_path / "vault"
        root = vault / "Alexandria"
        root.mkdir(parents=True, exist_ok=True)
        return ObsidianVaultStatus(
            vault_path=str(vault),
            alexandria_root="Alexandria",
            vault_exists=True,
            alexandria_root_exists=True,
            indexed_notes=3,
            stale_notes=0,
            error_notes=0,
        )


class _BackupOnlyObsidianService:
    def __init__(self, tmp_path: Path) -> None:
        self._tmp_path = tmp_path

    def vault_location(self) -> SimpleNamespace:
        vault = self._tmp_path / "vault"
        (vault / "Alexandria").mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            vault_path=str(vault),
            alexandria_root="Alexandria",
        )

    async def status(self) -> ObsidianVaultStatus:
        raise AssertionError("backup must not open an index-status transaction")


class _FakeReconciliationService:
    async def snapshot(self) -> MemoryReconciliationDiagnostics:
        return MemoryReconciliationDiagnostics(
            reachable=True,
            total_contexts=0,
            temporal_state_count=0,
            missing_temporal_states=0,
            total_plans=0,
            pending_review_plans=0,
            total_results=0,
            partial_apply_results=0,
            failed_results=0,
            open_conflicts=0,
            reviewing_conflicts=0,
            hard_delete_results=0,
            latest_failure_code=None,
            latest_failure_at=None,
        )


def test_operational_readiness_route_returns_snapshot_payload(tmp_path: Path) -> None:
    """GET handler should expose the read-only snapshot response contract."""

    async def scenario() -> dict[str, object]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            response = await operational_readiness(
                database=database,
                context_service=_FakeContextService(),
                obsidian_service=_FakeObsidianService(tmp_path),
                reconciliation_service=None,
                readiness_cache=NoopOperationalReadinessCache(),
            )
            return response.model_dump(mode="json")
        finally:
            await database.shutdown()

    payload = anyio.run(scenario)

    assert payload["status"] == "DEGRADED_FTS_ONLY"
    assert payload["ready"] is False
    database_payload = payload["database"]
    assert isinstance(database_payload, dict)
    assert database_payload["reachable"] is True
    assert database_payload["integrity"] == "HEALTHY"
    assert isinstance(database_payload["schema_version"], str)
    assert database_payload["corruption_detected"] is False
    assert payload["vault"]["indexed_notes"] == 3
    assert payload["rag"]["effective_strategy"] == "FTS_ONLY"
    assert payload["rag"]["source_statuses"] == [
        {
            "source_name": "obsidian_vault",
            "status": "REINDEX_REQUIRED",
            "total_rows": 459,
            "current_rows": 0,
            "stale_rows": 459,
            "missing_rows": 459,
            "current_fingerprint": {"provider": "test"},
            "stored_fingerprints": [],
        }
    ]
    assert payload["active_recovery_run_id"] is None
    assert payload["last_successful_recovery_run_id"] is None
    assert payload["warnings"] == ["rag_embedding_reindex_required"]
    assert payload["next_actions"] == ["reindex_embeddings"]


def test_operational_capabilities_keep_core_ready_without_embeddings(
    tmp_path: Path,
) -> None:
    """Semantic degradation must not falsely block durable FTS-backed memory."""

    async def scenario() -> dict[str, object]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            response = await operational_capabilities(
                database=database,
                context_service=_FakeContextService(),
                obsidian_service=_FakeObsidianService(tmp_path),
                reconciliation_service=None,
                readiness_cache=NoopOperationalReadinessCache(),
            )
            return response.model_dump(mode="json")
        finally:
            await database.shutdown()

    payload = anyio.run(scenario)

    assert payload["core_memory"] == {
        "state": "READY",
        "ready": True,
        "blockers": [],
        "warnings": [],
    }
    assert payload["semantic_retrieval"]["state"] == "DEGRADED"
    assert payload["semantic_retrieval"]["ready"] is False
    assert "rag_embedding_not_healthy" in payload["semantic_retrieval"]["blockers"]
    assert payload["librarian"]["state"] == "OPTIONAL"
    assert payload["librarian"]["ready"] is True


def test_fastapi_resolves_readiness_and_recovery_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FastAPI requests must never leak dependency-injector Provide markers."""

    database_url = os.environ["DATABASE_URL"]
    database = Database(
        database_url=database_url,
        create_schema=True,
    )
    anyio.run(database.initialize)
    anyio.run(database.shutdown)
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = AppConfig(
        _env_file=None,
        obsidian_vault_path=str(tmp_path / "vault"),
        obsidian_vault_config_path=str(tmp_path / "vault-config.json"),
        operational_backup_root=str(tmp_path / "backups"),
    )
    app = create_app(config)
    root_container = app.state.container

    try:
        with (
            root_container.memory.context_service.override(
                providers.Object(_FakeContextService())
            ),
            root_container.obsidian.obsidian_service.override(
                providers.Object(_FakeObsidianService(tmp_path))
            ),
            root_container.memory.memory_reconciliation_readiness_service.override(
                providers.Object(_FakeReconciliationService())
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            readiness_response = client.get("/operations/readiness")
            capabilities_response = client.get("/operations/capabilities")
            recovery_response = client.post(
                "/operations/recovery/plan",
                json={"idempotency_key": "fastapi-di-contract"},
            )
    finally:
        default_app.state.container.wire(packages=_ROUTER_PACKAGES)

    assert readiness_response.status_code == 200
    assert readiness_response.json()["reconciliation"]["configured"] is True
    assert capabilities_response.status_code == 200
    assert capabilities_response.json()["core_memory"]["ready"] is True
    assert recovery_response.status_code == 200
    assert recovery_response.json()["idempotency_key"] == "fastapi-di-contract"
