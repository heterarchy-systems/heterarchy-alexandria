"""Operational readiness policy tests for memory reconciliation diagnostics."""

from __future__ import annotations

import os

from datetime import UTC, datetime
from pathlib import Path

import anyio
from app.memory.domain.entities.context_read_models import RagDependencyHealth
from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationDiagnostics,
)
from app.memory.domain.event_enum.context_enums import RagHealthState, RagStrategy
from app.obsidian.domain.entities.obsidian_note import ObsidianVaultStatus
from app.operations.application.readiness.operational_readiness_service import (
    OperationalReadinessService,
)
from app.operations.domain.event_enum.operational_readiness_enums import (
    OperationalReadinessStatus,
)
from app.shared.infrastructure.database import Database
from sqlalchemy.exc import SQLAlchemyError

NOW = datetime(2026, 7, 25, tzinfo=UTC)


class _ContextService:
    async def rag_health_with_index_status(self) -> RagDependencyHealth:
        return RagDependencyHealth(
            fts=RagHealthState.HEALTHY,
            vector=RagHealthState.HEALTHY,
            embedding=RagHealthState.HEALTHY,
            default_strategy=RagStrategy.HYBRID,
            model_name="test-model",
            dimensions=3,
            fingerprint={"provider": "test"},
            warnings=[],
        )


class _ObsidianService:
    def __init__(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "Alexandria").mkdir(parents=True)
        self._status = ObsidianVaultStatus(
            vault_path=str(vault),
            alexandria_root="Alexandria",
            vault_exists=True,
            alexandria_root_exists=True,
            indexed_notes=12,
            stale_notes=0,
            error_notes=0,
        )

    async def status(self) -> ObsidianVaultStatus:
        return self._status


class _ReconciliationService:
    def __init__(self, diagnostics: MemoryReconciliationDiagnostics) -> None:
        self._diagnostics = diagnostics

    async def snapshot(self) -> MemoryReconciliationDiagnostics:
        return self._diagnostics


class _UnavailableReconciliationService:
    async def snapshot(self) -> MemoryReconciliationDiagnostics:
        raise SQLAlchemyError("reconciliation store unavailable")


def _diagnostics(
    *,
    missing_temporal_states: int = 0,
    pending_review_plans: int = 0,
    partial_apply_results: int = 0,
    failed_results: int = 0,
    open_conflicts: int = 0,
    reviewing_conflicts: int = 0,
    hard_delete_results: int = 0,
) -> MemoryReconciliationDiagnostics:
    return MemoryReconciliationDiagnostics(
        reachable=True,
        total_contexts=12,
        temporal_state_count=12 - missing_temporal_states,
        missing_temporal_states=missing_temporal_states,
        total_plans=5,
        pending_review_plans=pending_review_plans,
        total_results=4,
        partial_apply_results=partial_apply_results,
        failed_results=failed_results,
        open_conflicts=open_conflicts,
        reviewing_conflicts=reviewing_conflicts,
        hard_delete_results=hard_delete_results,
        latest_failure_code=("PARTIAL_APPLY" if partial_apply_results else None),
        latest_failure_at=NOW if partial_apply_results or failed_results else None,
    )


def test_readiness_surfaces_backfill_and_review_work_as_nonblocking_warnings(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_ContextService(),
                obsidian_service=_ObsidianService(tmp_path),
                reconciliation_service=_ReconciliationService(
                    _diagnostics(
                        missing_temporal_states=3,
                        pending_review_plans=2,
                        open_conflicts=1,
                        reviewing_conflicts=1,
                    )
                ),
            )

            snapshot = await service.snapshot()

            assert snapshot.status is OperationalReadinessStatus.UNKNOWN
            assert snapshot.ready is False
            assert snapshot.blockers == ()
            assert snapshot.reconciliation.backfill_complete is False
            assert snapshot.reconciliation.missing_temporal_states == 3
            assert {
                "memory_reconciliation_temporal_backfill_required",
                "memory_reconciliation_review_required",
                "memory_reconciliation_open_conflicts",
                "memory_reconciliation_reviews_in_progress",
            } <= set(snapshot.warnings)
            assert "preview_existing_memory_reconciliation" in snapshot.next_actions
            assert "review_memory_reconciliation" in snapshot.next_actions
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_readiness_blocks_partial_failed_or_hard_delete_reconciliation_state(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_ContextService(),
                obsidian_service=_ObsidianService(tmp_path),
                reconciliation_service=_ReconciliationService(
                    _diagnostics(
                        partial_apply_results=1,
                        failed_results=1,
                        hard_delete_results=1,
                    )
                ),
            )

            snapshot = await service.snapshot()

            assert snapshot.status is OperationalReadinessStatus.BLOCKED
            assert {
                "memory_reconciliation_partial_apply_present",
                "memory_reconciliation_failed_results_present",
                "memory_reconciliation_hard_delete_detected",
            } <= set(snapshot.blockers)
            assert "inspect_memory_reconciliation_failures" in snapshot.next_actions
            assert "audit_memory_reconciliation_integrity" in snapshot.next_actions
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_readiness_blocks_when_reconciliation_diagnostics_are_unreachable(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            service = OperationalReadinessService(
                database=database,
                context_service=_ContextService(),
                obsidian_service=_ObsidianService(tmp_path),
                reconciliation_service=_UnavailableReconciliationService(),
            )

            snapshot = await service.snapshot()

            assert snapshot.status is OperationalReadinessStatus.BLOCKED
            assert snapshot.reconciliation.configured is True
            assert snapshot.reconciliation.reachable is False
            assert "memory_reconciliation_repository_unreachable" in snapshot.blockers
            assert "inspect_memory_reconciliation_repository" in snapshot.next_actions
        finally:
            await database.shutdown()

    anyio.run(scenario)
