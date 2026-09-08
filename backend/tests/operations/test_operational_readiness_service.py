"""Operational readiness snapshot contracts."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import anyio
import pytest
from tests.operations.operational_readiness_fakes import HealthyGraphProjectionService

from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.domain.entities.obsidian_note import (
    ObsidianIndexError,
    ObsidianVaultStatus,
)
from app.obsidian.domain.event_enum.obsidian_enums import ObsidianIndexErrorCode
from app.operations.application.readiness.operational_database_probe import (
    OperationalDatabaseProbe,
)
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.shared.infrastructure.database import Database


class _FakeContextService:
    def __init__(self, health: RagDependencyHealth) -> None:
        self._health = health

    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return self._health


class _FakeObsidianService:
    def __init__(self, status: ObsidianVaultStatus) -> None:
        self._status = status

    async def status(self) -> ObsidianVaultStatus:
        return self._status


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


def _healthy_rag() -> RagDependencyHealth:
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


def _degraded_embedding_rag() -> RagDependencyHealth:
    return RagDependencyHealth(
        fts=RagHealthState.HEALTHY,
        vector=RagHealthState.HEALTHY,
        embedding=RagHealthState.REINDEX_REQUIRED,
        default_strategy=RagStrategy.FTS_ONLY,
        model_name="test-model",
        dimensions=3,
        fingerprint={"provider": "test"},
        warnings=("embedding fingerprint mismatch",),
    )


def _healthy_components_fts_only_rag() -> RagDependencyHealth:
    return RagDependencyHealth(
        fts=RagHealthState.HEALTHY,
        vector=RagHealthState.HEALTHY,
        embedding=RagHealthState.HEALTHY,
        default_strategy=RagStrategy.FTS_ONLY,
        model_name="test-model",
        dimensions=3,
        fingerprint={"provider": "test"},
        warnings=(),
    )


def _healthy_components_warning_rag() -> RagDependencyHealth:
    return RagDependencyHealth(
        fts=RagHealthState.HEALTHY,
        vector=RagHealthState.HEALTHY,
        embedding=RagHealthState.HEALTHY,
        default_strategy=RagStrategy.HYBRID,
        model_name="test-model",
        dimensions=3,
        fingerprint={"provider": "test"},
        warnings=("vector index is stale",),
    )


def _obsidian_status(
    tmp_path: Path,
    *,
    stale: int = 0,
    errors: int = 0,
    index_errors: tuple[ObsidianIndexError, ...] = (),
) -> ObsidianVaultStatus:
    vault = tmp_path / "vault"
    root = vault / "Alexandria"
    root.mkdir(parents=True)
    return ObsidianVaultStatus(
        vault_path=str(vault),
        alexandria_root="Alexandria",
        vault_exists=True,
        alexandria_root_exists=True,
        indexed_notes=3,
        stale_notes=stale,
        error_notes=errors,
        index_errors=index_errors,
    )


def test_operational_readiness_reports_ready_when_all_dependencies_are_healthy(
    tmp_path: Path,
) -> None:
    """Healthy database, vault, and RAG should produce READY/HYBRID."""

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_healthy_rag()),
                obsidian_service=_FakeObsidianService(_obsidian_status(tmp_path)),
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return (
                snapshot.status,
                snapshot.ready,
                snapshot.rag.effective_strategy,
                snapshot.warnings,
            )
        finally:
            await database.shutdown()

    status, ready, strategy, warnings = anyio.run(scenario)

    assert status == OperationalReadinessStatus.READY
    assert ready is True
    assert strategy == RagStrategy.HYBRID
    assert warnings == ()


def test_operational_database_probe_uses_server_health_for_postgres() -> None:
    """PostgreSQL readiness should not execute SQLite integrity statements."""

    async def scenario():
        probe = OperationalDatabaseProbe(cast(Database, _HealthyPostgresDatabase()))
        snapshot = await probe.snapshot()
        return (
            snapshot.reachable,
            snapshot.integrity,
            snapshot.corruption_detected,
            snapshot.schema_version,
        )

    assert anyio.run(scenario) == (
        True,
        "HEALTHY",
        False,
        "202608062130_pg_search",
    )


def test_operational_readiness_blocks_when_rag_strategy_is_not_hybrid(
    tmp_path: Path,
) -> None:
    """All RAG components healthy still requires HYBRID default strategy."""

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_healthy_components_fts_only_rag()),
                obsidian_service=_FakeObsidianService(_obsidian_status(tmp_path)),
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return (
                snapshot.status,
                snapshot.ready,
                snapshot.rag.effective_strategy,
                snapshot.warnings,
                snapshot.blockers,
            )
        finally:
            await database.shutdown()

    status, ready, strategy, warnings, blockers = anyio.run(scenario)

    assert status == OperationalReadinessStatus.BLOCKED
    assert ready is False
    assert strategy == RagStrategy.FTS_ONLY
    assert warnings == ("rag_default_strategy_not_hybrid",)
    assert blockers == ("rag_default_strategy_not_hybrid",)


def test_operational_readiness_blocks_when_rag_health_reports_warnings(
    tmp_path: Path,
) -> None:
    """RAG health warnings should prevent operational READY."""

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_healthy_components_warning_rag()),
                obsidian_service=_FakeObsidianService(_obsidian_status(tmp_path)),
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return snapshot.status, snapshot.ready, snapshot.warnings, snapshot.blockers
        finally:
            await database.shutdown()

    status, ready, warnings, blockers = anyio.run(scenario)

    assert status == OperationalReadinessStatus.BLOCKED
    assert ready is False
    assert warnings == ("rag_status_warnings_present",)
    assert blockers == ("rag_status_warnings_present",)


def test_operational_readiness_degrades_to_fts_only_when_embedding_reindex_required(
    tmp_path: Path,
) -> None:
    """Embedding mismatch should be visible as DEGRADED_FTS_ONLY, not READY."""

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_degraded_embedding_rag()),
                obsidian_service=_FakeObsidianService(_obsidian_status(tmp_path)),
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return (
                snapshot.status,
                snapshot.ready,
                snapshot.rag.effective_strategy,
                snapshot.warnings,
                snapshot.next_actions,
            )
        finally:
            await database.shutdown()

    status, ready, strategy, warnings, next_actions = anyio.run(scenario)

    assert status == OperationalReadinessStatus.DEGRADED_FTS_ONLY
    assert ready is False
    assert strategy == RagStrategy.FTS_ONLY
    assert "rag_embedding_reindex_required" in warnings
    assert "reindex_embeddings" in next_actions


def test_operational_readiness_blocks_when_vault_has_index_errors(
    tmp_path: Path,
) -> None:
    """Vault stale/error notes should prevent READY until reindex repair succeeds."""

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_healthy_rag()),
                obsidian_service=_FakeObsidianService(
                    _obsidian_status(tmp_path, stale=1, errors=1)
                ),
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return (
                snapshot.status,
                snapshot.ready,
                snapshot.warnings,
                snapshot.next_actions,
            )
        finally:
            await database.shutdown()

    status, ready, warnings, next_actions = anyio.run(scenario)

    assert status == OperationalReadinessStatus.BLOCKED
    assert ready is False
    assert warnings == ("obsidian_stale_notes_present", "obsidian_error_notes_present")
    assert next_actions == ("reindex_vault", "inspect_obsidian_index_errors")


def test_operational_readiness_routes_frontmatter_errors_to_repair_planning(
    tmp_path: Path,
) -> None:
    """Known structural index errors need repair guidance, not another blind scan."""

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            index_error = ObsidianIndexError(
                note_path="Alexandria/Contexts/Broken.md",
                context_id="broken",
                error_code=ObsidianIndexErrorCode.FRONTMATTER_PARSE_ERROR,
                error_message="frontmatter parse failed",
                detected_at=datetime.now(UTC),
            )
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_healthy_rag()),
                obsidian_service=_FakeObsidianService(
                    _obsidian_status(
                        tmp_path,
                        errors=1,
                        index_errors=(index_error,),
                    )
                ),
                graph_projection_service=HealthyGraphProjectionService(),
            )
            return (await service.snapshot()).next_actions
        finally:
            await database.shutdown()

    assert anyio.run(scenario) == ("plan_index_error_repairs",)


def test_operational_readiness_reports_active_recovery_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Active recovery lock should fail closed as RECOVERING."""
    monkeypatch.chdir(tmp_path)

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        recovery_dir = tmp_path / "data" / ".alexandria-recovery"
        recovery_dir.mkdir(parents=True)
        (recovery_dir / "active-run.json").write_text(
            '{"run_id":"active-run","idempotency_key":"active-key"}',
            encoding="utf-8",
        )
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_healthy_rag()),
                obsidian_service=_FakeObsidianService(_obsidian_status(tmp_path)),
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return (
                snapshot.status,
                snapshot.ready,
                snapshot.active_recovery_run_id,
                snapshot.blockers,
                snapshot.next_actions,
            )
        finally:
            await database.shutdown()

    status, ready, active_run_id, blockers, next_actions = anyio.run(scenario)

    assert status == OperationalReadinessStatus.RECOVERING
    assert ready is False
    assert active_run_id == "active-run"
    assert "recovery_in_progress" in blockers
    assert "inspect_recovery_run" in next_actions


def test_operational_readiness_reports_unreadable_active_recovery_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corrupt restart state should still fail closed as recovery in progress."""
    monkeypatch.chdir(tmp_path)

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        recovery_dir = tmp_path / "data" / ".alexandria-recovery"
        recovery_dir.mkdir(parents=True)
        (recovery_dir / "active-run.json").write_text("{not-json", encoding="utf-8")
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_healthy_rag()),
                obsidian_service=_FakeObsidianService(_obsidian_status(tmp_path)),
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return (
                snapshot.status,
                snapshot.ready,
                snapshot.active_recovery_run_id,
                snapshot.blockers,
                snapshot.next_actions,
            )
        finally:
            await database.shutdown()

    status, ready, active_run_id, blockers, next_actions = anyio.run(scenario)

    assert status == OperationalReadinessStatus.RECOVERING
    assert ready is False
    assert active_run_id == "unreadable-active-recovery-lock"
    assert "recovery_in_progress" in blockers
    assert "inspect_recovery_run" in next_actions


def test_operational_readiness_reports_last_successful_recovery_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness should expose the most recent completed recovery run id."""
    monkeypatch.chdir(tmp_path)

    async def scenario():
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        recovery_dir = tmp_path / "data" / ".alexandria-recovery"
        (recovery_dir / "failed-run").mkdir(parents=True)
        (recovery_dir / "failed-run" / "recovery-run.json").write_text(
            '{"id":"failed-run","status":"FAILED","finished_at":"2026-07-16T00:00:00+00:00"}',
            encoding="utf-8",
        )
        (recovery_dir / "completed-run").mkdir(parents=True)
        (recovery_dir / "completed-run" / "recovery-run.json").write_text(
            '{"id":"completed-run","status":"COMPLETED",'
            '"finished_at":"2026-07-16T01:00:00+00:00"}',
            encoding="utf-8",
        )
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_FakeContextService(_healthy_rag()),
                obsidian_service=_FakeObsidianService(_obsidian_status(tmp_path)),
                graph_projection_service=HealthyGraphProjectionService(),
            )

            snapshot = await service.snapshot()
            return snapshot.status, snapshot.last_successful_recovery_run_id
        finally:
            await database.shutdown()

    status, last_successful_recovery_run_id = anyio.run(scenario)

    assert status == OperationalReadinessStatus.READY
    assert last_successful_recovery_run_id == "completed-run"
