"""Read-only diagnostics tests for memory reconciliation readiness."""

from __future__ import annotations

import os

from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from app.memory.application.reconciliation.runtime.memory_reconciliation_readiness_service import (
    MemoryReconciliationReadinessService,
)
from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.entities.memory_reconciliation_diagnostics import (
    MemoryReconciliationStoreDiagnostics,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryConflictStatus,
    MemoryReconciliationStatus,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_readiness_repository import (
    IMemoryReconciliationReadinessRepository,
)
from app.memory.infrastructure.models.reconciliation_models import (
    ContextTemporalStateORM,
    MemoryConflictSetORM,
    MemoryReconciliationPlanORM,
    MemoryReconciliationResultORM,
)
from app.memory.infrastructure.repositories.memory_reconciliation_readiness_repository import (
    SqlAlchemyMemoryReconciliationReadinessRepository,
)
from app.shared.infrastructure.database import Database

NOW = datetime(2026, 7, 25, tzinfo=UTC)


class _StaticReadinessRepository(IMemoryReconciliationReadinessRepository):
    def __init__(self, snapshot: MemoryReconciliationStoreDiagnostics) -> None:
        self._snapshot = snapshot

    async def snapshot(self) -> MemoryReconciliationStoreDiagnostics:
        return self._snapshot


class _ContextCountService:
    async def list_contexts(
        self,
        *,
        limit: int,
        offset: int,
        project: str | None,
        scope: ContextScope | None,
        include_archived: bool,
    ) -> tuple[list[ContextRecord], int]:
        assert (limit, offset, project, scope, include_archived) == (
            1,
            0,
            None,
            None,
            True,
        )
        return [], 12


def test_readiness_service_calculates_temporal_backfill_gap() -> None:
    store = MemoryReconciliationStoreDiagnostics(
        reachable=True,
        total_plans=7,
        pending_review_plans=2,
        total_results=5,
        partial_apply_results=1,
        failed_results=1,
        open_conflicts=3,
        reviewing_conflicts=1,
        temporal_state_count=9,
        hard_delete_results=0,
        latest_failure_code="PARTIAL_APPLY",
        latest_failure_at=NOW,
    )

    async def scenario() -> None:
        service = MemoryReconciliationReadinessService(
            repository=_StaticReadinessRepository(store),
            context_service=_ContextCountService(),
        )
        snapshot = await service.snapshot()

        assert snapshot.total_contexts == 12
        assert snapshot.temporal_state_count == 9
        assert snapshot.missing_temporal_states == 3
        assert snapshot.pending_review_plans == 2
        assert snapshot.latest_failure_code == "PARTIAL_APPLY"

    anyio.run(scenario)


def test_sql_readiness_repository_aggregates_reconciliation_tables(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = Database(
            database_url=os.environ["DATABASE_URL"],
            create_schema=True,
        )
        await database.initialize()
        try:
            async with database.session() as session:
                session.add_all(
                    [
                        MemoryReconciliationPlanORM(
                            id="plan-review",
                            candidate_id="candidate-review",
                            idempotency_key="key-review",
                            primary_decision="CONTRADICTS",
                            status=MemoryReconciliationStatus.REVIEW_REQUIRED.value,
                            requires_review=True,
                            payload={},
                            created_at=NOW,
                        ),
                        MemoryReconciliationPlanORM(
                            id="plan-failed",
                            candidate_id="candidate-failed",
                            idempotency_key="key-failed",
                            primary_decision="UNKNOWN",
                            status=MemoryReconciliationStatus.PLANNED.value,
                            requires_review=False,
                            payload={},
                            created_at=NOW,
                        ),
                        MemoryReconciliationPlanORM(
                            id="plan-partial",
                            candidate_id="candidate-partial",
                            idempotency_key="key-partial",
                            primary_decision="SUPERSEDES",
                            status=MemoryReconciliationStatus.PLANNED.value,
                            requires_review=False,
                            payload={},
                            created_at=NOW,
                        ),
                    ]
                )
                await session.flush()
                session.add_all(
                    [
                        MemoryReconciliationResultORM(
                            id="result-failed",
                            plan_id="plan-failed",
                            status=MemoryReconciliationStatus.FAILED.value,
                            failure_code="CONTEXT_WRITE_FAILED",
                            hard_delete_performed=False,
                            payload={},
                            completed_at=NOW,
                        ),
                        MemoryReconciliationResultORM(
                            id="result-partial",
                            plan_id="plan-partial",
                            status=MemoryReconciliationStatus.PARTIAL_APPLY.value,
                            failure_code="PARTIAL_APPLY",
                            hard_delete_performed=True,
                            payload={},
                            completed_at=NOW + timedelta(minutes=1),
                        ),
                        MemoryConflictSetORM(
                            id="conflict-open",
                            candidate_id="candidate-open",
                            subject_key="subject-open",
                            claim_key="claim-open",
                            scope=ContextScope.PROJECT.value,
                            status=MemoryConflictStatus.OPEN.value,
                            validity_overlap=True,
                            payload={},
                            created_at=NOW,
                            resolved_at=None,
                        ),
                        MemoryConflictSetORM(
                            id="conflict-reviewing",
                            candidate_id="candidate-reviewing",
                            subject_key="subject-reviewing",
                            claim_key="claim-reviewing",
                            scope=ContextScope.PROJECT.value,
                            status=MemoryConflictStatus.REVIEWING.value,
                            validity_overlap=True,
                            payload={},
                            created_at=NOW,
                            resolved_at=None,
                        ),
                        ContextTemporalStateORM(
                            context_id="obsidian:one",
                            recorded_at=NOW,
                            observed_at=None,
                            valid_from=None,
                            valid_to=None,
                            is_current=True,
                            payload={},
                            updated_at=NOW,
                        ),
                    ]
                )
                await session.flush()

                repository = SqlAlchemyMemoryReconciliationReadinessRepository(session)
                snapshot = await repository.snapshot()

                assert snapshot.total_plans == 3
                assert snapshot.pending_review_plans == 1
                assert snapshot.total_results == 2
                assert snapshot.partial_apply_results == 1
                assert snapshot.failed_results == 1
                assert snapshot.open_conflicts == 1
                assert snapshot.reviewing_conflicts == 1
                assert snapshot.temporal_state_count == 1
                assert snapshot.hard_delete_results == 1
                assert snapshot.latest_failure_code == "PARTIAL_APPLY"
                assert snapshot.latest_failure_at == NOW + timedelta(minutes=1)
        finally:
            await database.shutdown()

    anyio.run(scenario)
