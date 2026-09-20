"""Memory Steward diagnose and seal service contracts."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import anyio
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService

from app.memory.domain.entities.context_read_models import (
    ContextEmbeddingSourceStatus,
    ContextPack,
    RagDependencyHealth,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
)
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
from app.operations.domain.entities.maintenance_job import MaintenanceQueueSnapshot
from app.operations.interface.routers.operational_readiness_router import (
    memory_steward_diagnose,
    memory_steward_seal,
)
from app.operations.interface.schemas.operations.memory_steward_schema import (
    MemoryStewardDiagnoseResponse,
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


class _FakeMaintenanceQueue:
    def __init__(self, *, unavailable: bool = False) -> None:
        self._unavailable = unavailable

    async def queue_status(self) -> MaintenanceQueueSnapshot:
        if self._unavailable:
            raise MaintenanceQueueUnavailableError("redis down")
        return MaintenanceQueueSnapshot(
            stream_length=4,
            pending=1,
            consumers=1,
            dead_letter_length=3,
        )


class _FakeCurrentCompacts:
    async def list_compacts(
        self,
        project: str | None = None,
        status: MemoryCompactStatus | None = None,
        covered_after: datetime | None = None,
        covered_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryCompact], int]:
        def _compact(compact_id: str) -> MemoryCompact:
            return MemoryCompact(
                id=compact_id,
                project="heterarchy-alexandria",
                covered_from=datetime(2026, 9, 20, tzinfo=UTC),
                covered_to=datetime(2026, 9, 21, tzinfo=UTC),
                markdown_body="# Compact\n",
                status=MemoryCompactStatus.CURRENT,
                source_refs=(),
                created_at=datetime(2026, 9, 21, tzinfo=UTC),
                updated_at=datetime(2026, 9, 21, tzinfo=UTC),
                archived_at=None,
            )

        return [_compact("c-1"), _compact("c-2")], 5


def test_steward_diagnose_surfaces_dlq_and_compact_evidence(tmp_path: Path) -> None:
    """Diagnose composes queue and CURRENT compact evidence into the verdict."""
    service, database = _readiness_service(tmp_path)

    async def scenario() -> dict[str, object]:
        try:
            result = await MemoryStewardDiagnoseService(
                service,
                _FakeMaintenanceQueue(),
                _FakeCurrentCompacts(),
            ).diagnose()
            return MemoryStewardDiagnoseResponse.from_entity(result).model_dump(
                mode="json"
            )
        finally:
            await database.shutdown()

    payload = anyio.run(scenario)

    diagnostics = payload["diagnostics"]
    assert isinstance(diagnostics, list)
    codes = {diagnostic["code"] for diagnostic in diagnostics}
    assert "DLQ_RESIDUALS" in codes
    queue = payload["queue"]
    assert isinstance(queue, dict)
    assert queue["pending"] == 1
    assert queue["dead_letter_length"] == 3
    assert payload["current_compacts"] == {"count": 5, "unique_projects": False}


def test_steward_diagnose_reports_queue_unavailable_as_residual(
    tmp_path: Path,
) -> None:
    """An unavailable queue becomes a non-blocking diagnostic, not a crash."""
    service, database = _readiness_service(tmp_path)

    async def scenario() -> tuple[str, ...]:
        try:
            result = await MemoryStewardDiagnoseService(
                service,
                _FakeMaintenanceQueue(unavailable=True),
            ).diagnose()
            return tuple(diagnostic.code for diagnostic in result.diagnostics)
        finally:
            await database.shutdown()

    codes = anyio.run(scenario)

    assert "QUEUE_UNAVAILABLE" in codes
