"""Recovery-state safety contracts for operational readiness caching."""

from __future__ import annotations

from typing import cast

import anyio
import app.operations.application.readiness.operational_readiness_service as readiness_module
import pytest
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


class _HealthyPostgresSession:
    async def __aenter__(self) -> _HealthyPostgresSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        if str(statement) != "SELECT 1":
            raise AssertionError(f"Unexpected SQL: {statement}")

    async def scalar(self, statement: object) -> str | int | None:
        rendered = str(statement)
        if rendered == "SELECT 1":
            return 1
        if "to_regclass" in rendered:
            return "alembic_version"
        if rendered == "SELECT version_num FROM alembic_version":
            return "202608062130_pg_search"
        raise AssertionError(f"Unexpected SQL: {rendered}")


class _HealthyPostgresDatabase:
    dialect_name = "postgresql"

    def session_factory(self):
        return _HealthyPostgresSession


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
    def __init__(self) -> None:
        self.calls = 0

    async def status(self) -> ObsidianVaultStatus:
        self.calls += 1
        return ObsidianVaultStatus(
            vault_path="vault",
            alexandria_root="Alexandria",
            vault_exists=True,
            alexandria_root_exists=True,
            indexed_notes=3,
            stale_notes=0,
            error_notes=0,
            index_errors=(),
        )


class _RecordingReadinessCache:
    def __init__(self, cached: OperationalReadinessSnapshot) -> None:
        self._cached = cached
        self.get_calls = 0
        self.set_calls = 0

    async def get(self) -> OperationalReadinessSnapshot:
        self.get_calls += 1
        return self._cached

    async def set(self, snapshot: OperationalReadinessSnapshot) -> None:
        del snapshot
        self.set_calls += 1


async def _fresh_snapshot() -> OperationalReadinessSnapshot:
    service = OperationalReadinessService(
        database=cast(Database, _HealthyPostgresDatabase()),
        context_service=_CountingContextService(),
        obsidian_service=_CountingObsidianService(),
    )
    return await service.snapshot()


def test_active_recovery_bypasses_cached_ready_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active recovery lock must win over an existing cached READY result."""

    async def scenario() -> tuple[str | None, int, int, int, int]:
        monkeypatch.setattr(
            readiness_module,
            "_active_recovery_run_id",
            lambda: None,
        )
        cached = await _fresh_snapshot()
        cache = _RecordingReadinessCache(cached)
        context_service = _CountingContextService()
        obsidian_service = _CountingObsidianService()
        monkeypatch.setattr(
            readiness_module,
            "_active_recovery_run_id",
            lambda: "active-recovery-run",
        )
        service = OperationalReadinessService(
            database=cast(Database, _HealthyPostgresDatabase()),
            context_service=context_service,
            obsidian_service=obsidian_service,
            readiness_cache=cache,
        )

        snapshot = await service.snapshot()
        return (
            snapshot.active_recovery_run_id,
            cache.get_calls,
            cache.set_calls,
            context_service.calls,
            obsidian_service.calls,
        )

    assert anyio.run(scenario) == ("active-recovery-run", 0, 0, 1, 1)


def test_cache_hit_still_checks_authoritative_recovery_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache hit may skip heavy probes but not the active-recovery check."""

    async def scenario() -> tuple[bool, int, int, int, int]:
        recovery_checks = 0

        def no_active_recovery() -> None:
            nonlocal recovery_checks
            recovery_checks += 1
            return None

        monkeypatch.setattr(
            readiness_module,
            "_active_recovery_run_id",
            no_active_recovery,
        )
        cached = await _fresh_snapshot()
        cache = _RecordingReadinessCache(cached)
        context_service = _CountingContextService()
        obsidian_service = _CountingObsidianService()
        service = OperationalReadinessService(
            database=cast(Database, _HealthyPostgresDatabase()),
            context_service=context_service,
            obsidian_service=obsidian_service,
            readiness_cache=cache,
        )

        snapshot = await service.snapshot()
        return (
            snapshot is cached,
            recovery_checks,
            cache.get_calls,
            context_service.calls,
            obsidian_service.calls,
        )

    assert anyio.run(scenario) == (True, 2, 1, 0, 0)
