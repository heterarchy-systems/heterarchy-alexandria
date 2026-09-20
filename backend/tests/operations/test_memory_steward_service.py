"""Memory Steward diagnose and seal service contracts."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import anyio
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService

from app.memory.domain.entities.context_read_models import (
    ContextEmbeddingSourceStatus,
    ContextPack,
    RagDependencyHealth,
)
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.application.readiness.operational_readiness_cache import (
    NoopOperationalReadinessCache,
)
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.application.steward.memory_steward_service import (
    MemoryStewardDiagnoseService,
    MemoryStewardSealService,
)
from app.operations.interface.routers.operational_readiness_router import (
    memory_steward_diagnose,
    memory_steward_seal,
)
from app.shared.infrastructure.database import Database


class _ReindexRequiredContextService:
    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.REINDEX_REQUIRED,
            embedding=RagHealthState.REINDEX_REQUIRED,
            default_strategy=RagStrategy.FTS_ONLY,
            model_name="test-model",
            dimensions=3,
            fingerprint={"provider": "test"},
            warnings=("embedding mismatch",),
            source_statuses=(
                ContextEmbeddingSourceStatus(
                    source_name="obsidian_vault",
                    status=RagHealthState.REINDEX_REQUIRED,
                    total_rows=10,
                    current_rows=0,
                    stale_rows=10,
                    missing_rows=10,
                    current_fingerprint={"provider": "test"},
                    stored_fingerprints=(),
                ),
            ),
        )

    async def readiness_canary(
        self,
        query: str,
        strategy: RagStrategy,
        limit: int,
    ) -> ContextPack:
        return ContextPack(
            query=query,
            strategy=strategy,
            effective_strategy=strategy,
            warnings=(),
            recall_scopes=(),
            matches=(),
            context_pack="# Alexandria Context Pack\n",
        )


class _HealthyVaultObsidianService:
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
        (vault / "Alexandria").mkdir(parents=True, exist_ok=True)
        return ObsidianVaultStatus(
            vault_path=str(vault),
            alexandria_root="Alexandria",
            vault_exists=True,
            alexandria_root_exists=True,
            indexed_notes=3,
            stale_notes=0,
            error_notes=0,
        )


def _readiness_service(tmp_path: Path) -> tuple[OperationalReadinessService, Database]:
    database = Database(
        database_url=os.environ["DATABASE_URL"],
        create_schema=True,
    )
    anyio.run(database.initialize)
    service = OperationalReadinessService(
        database=database,
        context_service=_ReindexRequiredContextService(),
        obsidian_service=_HealthyVaultObsidianService(tmp_path),
        reconciliation_service=None,
        readiness_cache=NoopOperationalReadinessCache(),
        graph_projection_service=HealthyGraphProjectionService(),
    )
    return service, database


def test_steward_diagnose_reports_residual_and_degraded_state(tmp_path: Path) -> None:
    """Diagnose derives vector residuals and a degraded overall verdict."""
    service, database = _readiness_service(tmp_path)

    async def scenario() -> tuple[str, tuple[str, ...], bool]:
        try:
            result = await MemoryStewardDiagnoseService(service).diagnose()
            codes = tuple(diagnostic.code for diagnostic in result.diagnostics)
            readiness_ready = result.readiness.ready
            return result.overall_status.value, codes, readiness_ready
        finally:
            await database.shutdown()

    overall, codes, readiness_ready = anyio.run(scenario)

    assert overall == "DEGRADED"
    assert "RAG_VECTOR_REINDEX_REQUIRED" in codes
    assert readiness_ready is False


def test_steward_seal_reports_ready_with_residuals(tmp_path: Path) -> None:
    """Seal verifies final state and reports non-blocking residuals."""
    service, database = _readiness_service(tmp_path)

    async def scenario() -> tuple[str, tuple[str, ...]]:
        try:
            result = await MemoryStewardSealService(service).seal()
            codes = tuple(diagnostic.code for diagnostic in result.diagnostics)
            return result.overall_status.value, codes
        finally:
            await database.shutdown()

    overall, codes = anyio.run(scenario)

    assert overall == "READY_WITH_RESIDUALS"
    assert "RAG_VECTOR_REINDEX_REQUIRED" in codes


def test_steward_router_handlers_expose_http_contract(tmp_path: Path) -> None:
    """Router handlers map steward results to the serialized HTTP contract."""
    service, database = _readiness_service(tmp_path)

    async def scenario() -> tuple[dict[str, object], dict[str, object]]:
        try:
            diagnose_response = await memory_steward_diagnose(
                service=MemoryStewardDiagnoseService(service)
            )
            seal_response = await memory_steward_seal(
                service=MemoryStewardSealService(service)
            )
            return (
                diagnose_response.model_dump(mode="json"),
                seal_response.model_dump(mode="json"),
            )
        finally:
            await database.shutdown()

    diagnose_payload, seal_payload = anyio.run(scenario)

    assert diagnose_payload["overall_status"] == "DEGRADED"
    assert seal_payload["overall_status"] == "READY_WITH_RESIDUALS"
    diagnostics = seal_payload["diagnostics"]
    assert isinstance(diagnostics, list)
    assert {
        "code": "RAG_VECTOR_REINDEX_REQUIRED",
        "blocking": False,
        "count": 1,
        "detail_operation": "alexandria_operational_readiness",
        "recommended_operation": "alexandria_memory_steward_seal",
    } in diagnostics
    readiness_payload = seal_payload["readiness"]
    assert isinstance(readiness_payload, dict)
    assert readiness_payload["status"] == "DEGRADED_FTS_ONLY"
    assert readiness_payload["database"]["reachable"] is True
