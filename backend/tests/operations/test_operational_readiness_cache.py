"""Operational readiness cache integration contracts."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService

from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.domain.entities.operational_readiness import (
    OperationalReadinessSnapshot,
)
from app.shared.infrastructure.database import Database


class _CountingContextService:
    def __init__(self) -> None:
        self.calls = 0

    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        self.calls += 1
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=RagHealthState.HEALTHY,
            default_strategy=RagStrategy.HYBRID,
            model_name="test-model",
            dimensions=3,
            fingerprint={"provider": "test"},
            warnings=(),
        )


class _CountingObsidianService:
    def __init__(self, tmp_path: Path) -> None:
        self.calls = 0
        vault = tmp_path / "vault"
        root = vault / "Alexandria"
        root.mkdir(parents=True, exist_ok=True)
        self._status = ObsidianVaultStatus(
            vault_path=str(vault),
            alexandria_root="Alexandria",
            vault_exists=True,
            alexandria_root_exists=True,
            indexed_notes=3,
            stale_notes=0,
            error_notes=0,
            index_errors=(),
        )

    async def status(self) -> ObsidianVaultStatus:
        self.calls += 1
        return self._status


class _RecordingReadinessCache:
    def __init__(self, cached: OperationalReadinessSnapshot | None = None) -> None:
        self.cached = cached
        self.get_calls = 0
        self.set_snapshots: list[OperationalReadinessSnapshot] = []

    async def get(self) -> OperationalReadinessSnapshot | None:
        self.get_calls += 1
        return self.cached

    async def set(self, snapshot: OperationalReadinessSnapshot) -> None:
        self.set_snapshots.append(snapshot)


async def _fresh_snapshot(
    *,
    database: Database,
    tmp_path: Path,
) -> OperationalReadinessSnapshot:
    service = OperationalReadinessService(
        database=database,
        context_service=_CountingContextService(),
        obsidian_service=_CountingObsidianService(tmp_path),
        graph_projection_service=HealthyGraphProjectionService(),
    )
    return await service.snapshot()


def test_cache_hit_skips_authoritative_dependency_probes(tmp_path: Path) -> None:
    """A readiness cache hit should avoid all expensive dependency probes."""

    async def scenario() -> tuple[bool, int, int, int, int]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            cached = await _fresh_snapshot(database=database, tmp_path=tmp_path)
            context_service = _CountingContextService()
            obsidian_service = _CountingObsidianService(tmp_path)
            cache = _RecordingReadinessCache(cached)
            service = OperationalReadinessService(
                database=database,
                context_service=context_service,
                obsidian_service=obsidian_service,
                readiness_cache=cache,
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return (
                snapshot is cached,
                cache.get_calls,
                len(cache.set_snapshots),
                context_service.calls,
                obsidian_service.calls,
            )
        finally:
            await database.shutdown()

    assert anyio.run(scenario) == (True, 1, 0, 0, 0)


def test_cache_miss_stores_one_fresh_snapshot(tmp_path: Path) -> None:
    """A cache miss should probe once and store the resulting snapshot."""

    async def scenario() -> tuple[int, int, int, int, bool]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            context_service = _CountingContextService()
            obsidian_service = _CountingObsidianService(tmp_path)
            cache = _RecordingReadinessCache()
            service = OperationalReadinessService(
                database=database,
                context_service=context_service,
                obsidian_service=obsidian_service,
                readiness_cache=cache,
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return (
                cache.get_calls,
                len(cache.set_snapshots),
                context_service.calls,
                obsidian_service.calls,
                cache.set_snapshots == [snapshot],
            )
        finally:
            await database.shutdown()

    assert anyio.run(scenario) == (1, 1, 1, 1, True)


def test_recovery_verification_bypasses_cached_readiness(tmp_path: Path) -> None:
    """Recovery verification must always inspect authoritative dependencies."""

    async def scenario() -> tuple[int, int, int, int]:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            cached = await _fresh_snapshot(database=database, tmp_path=tmp_path)
            context_service = _CountingContextService()
            obsidian_service = _CountingObsidianService(tmp_path)
            cache = _RecordingReadinessCache(cached)
            service = OperationalReadinessService(
                database=database,
                context_service=context_service,
                obsidian_service=obsidian_service,
                readiness_cache=cache,
                ignore_active_recovery_run_id="internal-verification",
                graph_projection_service=HealthyGraphProjectionService(),
            )

            await service.snapshot()
            return (
                cache.get_calls,
                len(cache.set_snapshots),
                context_service.calls,
                obsidian_service.calls,
            )
        finally:
            await database.shutdown()

    assert anyio.run(scenario) == (0, 0, 1, 1)
