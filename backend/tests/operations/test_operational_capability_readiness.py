"""Independent capability readiness and degraded-source regressions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import anyio
from sqlalchemy.exc import SQLAlchemyError

from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegritySnapshot,
)
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.application.graph.projection.obsidian_graph_projection_rebuild_service import (
    ObsidianGraphProjectionStatusReport,
)
from app.obsidian.application.service.obsidian_service_ports import (
    ObsidianReadinessPort,
)
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianVaultLocation,
    ObsidianVaultStatus,
)
from app.operations.application.readiness.operational_database_probe import (
    OperationalDatabaseProbe,
)
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalDatabaseSnapshot,
)
from app.operations.domain.event_enum.operational_capability_enums import (
    OperationalCapabilityFreshness,
    OperationalCapabilityState,
)
from app.shared.infrastructure.database import Database


def _rag(
    *,
    fts: RagHealthState = RagHealthState.HEALTHY,
    vector: RagHealthState = RagHealthState.HEALTHY,
    embedding: RagHealthState = RagHealthState.HEALTHY,
) -> RagDependencyHealth:
    return RagDependencyHealth(
        fts=fts,
        vector=vector,
        embedding=embedding,
        default_strategy=RagStrategy.HYBRID,
        model_name="test-model",
        dimensions=3,
        fingerprint={"provider": "test"},
        warnings=(),
    )


class _Context:
    def __init__(self, health: RagDependencyHealth) -> None:
        self._health = health

    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return self._health


class _Obsidian(ObsidianReadinessPort):
    def __init__(self, tmp_path: Path, *, metadata_failure: bool = False) -> None:
        self._vault = tmp_path / "vault"
        (self._vault / "Alexandria").mkdir(parents=True, exist_ok=True)
        self._metadata_failure = metadata_failure

    def vault_location(self) -> ObsidianVaultLocation:
        return ObsidianVaultLocation(
            vault_path=str(self._vault),
            alexandria_root="Alexandria",
        )

    async def status(self) -> ObsidianVaultStatus:
        if self._metadata_failure:
            raise SQLAlchemyError("metadata lookup unavailable")
        return ObsidianVaultStatus(
            vault_path=str(self._vault),
            alexandria_root="Alexandria",
            vault_exists=True,
            alexandria_root_exists=True,
            indexed_notes=3,
            stale_notes=0,
            error_notes=0,
        )


class _Graph:
    def __init__(self, status: str) -> None:
        self._status = status

    async def status(self) -> ObsidianGraphProjectionStatusReport:
        return ObsidianGraphProjectionStatusReport(
            status=self._status,
            graph_read_model="postgresql",
            enabled=True,
            node_count=3 if self._status == "ready" else 0,
            edge_count=2 if self._status == "ready" else 0,
            run_id="graph-run" if self._status == "ready" else None,
            projection_version=1 if self._status == "ready" else None,
        )


class _Projection:
    def __init__(self, *, drifted: bool) -> None:
        self._drifted = drifted

    async def snapshot(self) -> ContextProjectionIntegritySnapshot:
        return ContextProjectionIntegritySnapshot(
            checked=True,
            available=True,
            source_revision="indexed-a",
            current_source_revision="indexed-b" if self._drifted else "indexed-a",
            scanned_count=3,
            valid_count=3,
            invalid_count=0,
            failures=(),
            checked_at=None,
            stale=self._drifted,
        )


class _FailingContext:
    def __init__(self) -> None:
        self.calls = 0

    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        self.calls += 1
        raise AssertionError("RAG must be skipped after database failure")


class _FailingGraph:
    def __init__(self) -> None:
        self.calls = 0

    async def status(self) -> ObsidianGraphProjectionStatusReport:
        self.calls += 1
        raise AssertionError("graph must be skipped after database failure")


class _FailingProjection:
    def __init__(self) -> None:
        self.calls = 0

    async def snapshot(self) -> ContextProjectionIntegritySnapshot:
        self.calls += 1
        raise AssertionError("projection must be skipped after database failure")


class _FailingReconciliation:
    def __init__(self) -> None:
        self.calls = 0

    async def snapshot(self) -> object:
        self.calls += 1
        raise AssertionError("reconciliation must be skipped after database failure")


class _SourceOnlyObsidian(_Obsidian):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        self.status_calls = 0

    async def status(self) -> ObsidianVaultStatus:
        self.status_calls += 1
        raise AssertionError("metadata status must be skipped after database failure")


def _service(
    tmp_path: Path,
    *,
    health: RagDependencyHealth,
    obsidian: _Obsidian,
    graph: _Graph | None = None,
    projection: _Projection | None = None,
) -> OperationalReadinessService:
    return OperationalReadinessService(
        database=Database(database_url=os.environ["DATABASE_URL"], create_schema=True),
        context_service=_Context(health),
        obsidian_service=obsidian,
        projection_integrity_service=projection,
        graph_projection_service=graph or _Graph("ready"),
    )


def test_metadata_failure_preserves_source_capability_and_unknown_counts(
    tmp_path: Path,
) -> None:
    """Metadata outage must not turn a readable source into memory loss."""

    async def scenario():
        service = _service(
            tmp_path,
            health=_rag(),
            obsidian=_Obsidian(tmp_path, metadata_failure=True),
        )
        await service._database.initialize()
        try:
            snapshot = await service.snapshot()
        finally:
            await service._database.shutdown()
        return snapshot

    snapshot = anyio.run(scenario)
    assert snapshot.vault.readable is True
    assert snapshot.vault.indexed_notes is None
    assert snapshot.vault.stale_notes is None
    assert snapshot.vault.error_notes is None
    assert "metadata_index_unavailable" in snapshot.warnings


def test_fts_degradation_is_independent_from_source(tmp_path: Path) -> None:
    """FTS failure is visible while source availability remains healthy."""

    async def scenario():
        service = _service(
            tmp_path,
            health=_rag(fts=RagHealthState.DEGRADED),
            obsidian=_Obsidian(tmp_path),
        )
        await service._database.initialize()
        try:
            return await service.snapshot()
        finally:
            await service._database.shutdown()

    snapshot = anyio.run(scenario)
    from app.operations.application.readiness.operational_capability_policy import (
        capability_snapshot,
    )

    capabilities = capability_snapshot(snapshot)
    assert capabilities.source.state is OperationalCapabilityState.READY
    assert capabilities.fts.state is OperationalCapabilityState.DEGRADED


def test_vector_staleness_exposes_stale_freshness(tmp_path: Path) -> None:
    """Vector reindex requirement must carry explicit stale evidence."""

    async def scenario():
        service = _service(
            tmp_path,
            health=_rag(vector=RagHealthState.REINDEX_REQUIRED),
            obsidian=_Obsidian(tmp_path),
        )
        await service._database.initialize()
        try:
            return await service.snapshot()
        finally:
            await service._database.shutdown()

    snapshot = anyio.run(scenario)
    from app.operations.application.readiness.operational_capability_policy import (
        capability_snapshot,
    )

    assert (
        capability_snapshot(snapshot).vector.freshness
        is OperationalCapabilityFreshness.STALE
    )


def test_graph_unavailable_does_not_claim_graph_ready(tmp_path: Path) -> None:
    """Graph unavailability is independent from healthy source/RAG evidence."""

    async def scenario():
        service = _service(
            tmp_path,
            health=_rag(),
            obsidian=_Obsidian(tmp_path),
            graph=_Graph("unavailable"),
        )
        await service._database.initialize()
        try:
            return await service.snapshot()
        finally:
            await service._database.shutdown()

    snapshot = anyio.run(scenario)
    from app.operations.application.readiness.operational_capability_policy import (
        capability_snapshot,
    )

    graph = capability_snapshot(snapshot).graph
    assert graph.state is OperationalCapabilityState.BLOCKED
    assert graph.freshness is OperationalCapabilityFreshness.UNKNOWN


def test_projection_revision_drift_is_stale_evidence(tmp_path: Path) -> None:
    """Persisted indexed-source revision drift must not be reported current."""

    async def scenario():
        service = _service(
            tmp_path,
            health=_rag(),
            obsidian=_Obsidian(tmp_path),
            projection=_Projection(drifted=True),
        )
        await service._database.initialize()
        try:
            return await service.snapshot()
        finally:
            await service._database.shutdown()

    snapshot = anyio.run(scenario)
    from app.operations.application.readiness.operational_capability_policy import (
        capability_snapshot,
    )

    metadata = capability_snapshot(snapshot).metadata_index
    assert metadata.freshness is OperationalCapabilityFreshness.STALE
    assert metadata.source_revision == "indexed-b"
    assert metadata.projection_revision == "indexed-a"


def test_database_failure_skips_all_database_dependent_readiness_probes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """One failed DB probe must not fan out into redundant DB timeouts."""
    context = _FailingContext()
    obsidian = _SourceOnlyObsidian(tmp_path)
    graph = _FailingGraph()
    projection = _FailingProjection()
    reconciliation = _FailingReconciliation()

    async def unavailable(
        _self: OperationalDatabaseProbe,
    ) -> OperationalDatabaseSnapshot:
        return OperationalDatabaseSnapshot(
            reachable=False,
            integrity="UNAVAILABLE",
            schema_version=None,
        )

    monkeypatch.setattr(OperationalDatabaseProbe, "snapshot", unavailable)
    service = OperationalReadinessService(
        database=cast(Database, object()),
        context_service=context,
        obsidian_service=obsidian,
        reconciliation_service=reconciliation,
        projection_integrity_service=projection,
        graph_projection_service=graph,
    )

    snapshot = anyio.run(service.snapshot)

    assert snapshot.vault.readable is True
    assert "database_unreachable" in snapshot.warnings
    assert obsidian.status_calls == 0
    assert context.calls == 0
    assert graph.calls == 0
    assert projection.calls == 0
    assert reconciliation.calls == 0
