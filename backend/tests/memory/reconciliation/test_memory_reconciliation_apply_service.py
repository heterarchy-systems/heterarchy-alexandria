"""Application tests for idempotent reconciliation plan application."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest

from app.memory.application.reconciliation.candidates.memory_relation_classifier import (
    MemoryRelationClassifier,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_apply_service import (
    MemoryReconciliationApplyService,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryCandidate,
    MemoryRecallCandidate,
    MemorySourceReference,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationFailureCode,
    MemoryReconciliationStatus,
    MemoryRelationType,
)
from app.memory.domain.repositories.contexts.memory_canonical_mutation_gateway import (
    IMemoryCanonicalMutationGateway,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.infrastructure.database import Database

EARLIER = datetime(2026, 7, 1, tzinfo=UTC)
OLD_END = datetime(2026, 7, 20, tzinfo=UTC)
NOW = datetime(2026, 7, 25, tzinfo=UTC)


class RecordingCanonicalGateway(IMemoryCanonicalMutationGateway):
    """Record canonical mutations and optionally fail read-back verification."""

    def __init__(self, *, verify_result: bool = True) -> None:
        self.verify_result = verify_result
        self.created: list[str] = []
        self.merged: list[str] = []
        self.superseded: list[tuple[str, str]] = []

    async def create_context(
        self,
        candidate: MemoryCandidate,
        *,
        lifecycle_status: str,
        supersedes_context_id: str | None = None,
        conflict_set_ids: tuple[str, ...] = (),
        relation: MemoryRelationType | None = None,
        related_context_id: str | None = None,
    ) -> str:
        _ = (
            lifecycle_status,
            supersedes_context_id,
            conflict_set_ids,
            relation,
            related_context_id,
        )
        context_id = f"obsidian:{candidate.candidate_id}"
        self.created.append(context_id)
        return context_id

    async def merge_evidence(
        self,
        context_id: str,
        evidence: tuple[MemorySourceReference, ...],
    ) -> str:
        _ = evidence
        self.merged.append(context_id)
        return context_id

    async def supersede(
        self,
        context_id: str,
        replacement_context_id: str,
    ) -> None:
        self.superseded.append((context_id, replacement_context_id))

    async def verify(self, context_id: str) -> bool:
        _ = context_id
        return self.verify_result


def _source() -> MemorySourceReference:
    return MemorySourceReference(
        source_type="user",
        source_id="source-1",
        title="Source",
        detail_path="Contexts/source.md",
    )


def _claim(
    object_value: str,
    *,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> CanonicalClaim:
    return CanonicalClaim(
        subject="heterarchy-alexandria",
        predicate="uses",
        object=object_value,
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _candidate(
    *,
    object_value: str = "PostgreSQL",
    valid_from: datetime | None = NOW,
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="candidate-new",
        title="New storage decision",
        body=f"heterarchy-alexandria uses {object_value}.",
        canonical_claims=(_claim(object_value, valid_from=valid_from),),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=("memory",),
        source_refs=(_source(),),
        recorded_at=NOW,
        observed_at=NOW,
        valid_from=valid_from,
        valid_to=None,
        requested_lifecycle="active",
        content_hash=f"hash-{object_value}",
    )


def _existing(
    *,
    object_value: str = "Redis",
    valid_from: datetime | None = EARLIER,
    valid_to: datetime | None = None,
) -> MemoryRecallCandidate:
    return MemoryRecallCandidate(
        context_id="obsidian:context-old",
        title="Old storage decision",
        body=f"heterarchy-alexandria uses {object_value}.",
        canonical_claims=(
            _claim(object_value, valid_from=valid_from, valid_to=valid_to),
        ),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        source_identity=None,
        content_hash=f"old-hash-{object_value}",
        recorded_at=EARLIER,
        observed_at=valid_from,
        valid_from=valid_from,
        valid_to=valid_to,
        source_refs=(),
    )


@asynccontextmanager
async def _repository(
    tmp_path: Path,
    name: str,
) -> AsyncIterator[SqlAlchemyMemoryReconciliationRepository]:
    database = Database(
        database_url=os.environ["DATABASE_URL"],
        create_schema=True,
    )
    await database.initialize()
    try:
        async with database.session() as session:
            yield SqlAlchemyMemoryReconciliationRepository(session)
    finally:
        await database.shutdown()


def test_unrelated_plan_creates_context_and_is_idempotent(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _repository(tmp_path, "apply-unrelated.db") as repository:
            candidate = _candidate()
            plan = MemoryReconciliationPlanService().build(
                candidate=candidate,
                decisions=(),
                idempotency_key="apply-unrelated",
            )
            await repository.save_plan(plan)
            gateway = RecordingCanonicalGateway()
            service = MemoryReconciliationApplyService(
                repository=repository,
                canonical_gateway=gateway,
            )

            first = await service.apply(plan.plan_id)
            second = await service.apply(plan.plan_id)

            assert first == second
            assert first.status is MemoryReconciliationStatus.APPLIED
            assert first.created_context_ids == ("obsidian:candidate-new",)
            assert first.hard_delete_performed is False
            assert gateway.created == ["obsidian:candidate-new"]
            temporal = await repository.get_temporal_state("obsidian:candidate-new")
            assert temporal is not None and temporal.is_current is True

    anyio.run(scenario)


def test_supersede_plan_links_contexts_and_closes_old_validity(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _repository(tmp_path, "apply-supersede.db") as repository:
            candidate = _candidate()
            decision = MemoryRelationClassifier().classify(
                candidate,
                _existing(valid_to=OLD_END),
            )
            assert decision.relation is MemoryRelationType.SUPERSEDES
            plan = MemoryReconciliationPlanService().build(
                candidate=candidate,
                decisions=(decision,),
                idempotency_key="apply-supersede",
            )
            await repository.save_plan(plan)
            gateway = RecordingCanonicalGateway()

            service = MemoryReconciliationApplyService(
                repository=repository,
                canonical_gateway=gateway,
            )
            with pytest.raises(
                MemoryContextValidationError,
                match="RECONCILIATION_REVIEW_APPROVAL_REQUIRED",
            ):
                await service.apply(plan.plan_id)
            assert gateway.created == []
            assert gateway.superseded == []

            result = await service.apply(
                plan.plan_id,
                review_approved=True,
                reviewer="memory-steward",
            )

            assert result.status is MemoryReconciliationStatus.APPLIED
            assert result.reviewed_by == "memory-steward"
            assert result.reviewed_at is not None
            assert result.superseded_context_ids == ("obsidian:context-old",)
            assert gateway.superseded == [
                ("obsidian:context-old", "obsidian:candidate-new")
            ]
            old_state = await repository.get_temporal_state("obsidian:context-old")
            new_state = await repository.get_temporal_state("obsidian:candidate-new")
            assert old_state is not None and old_state.is_current is False
            assert old_state.valid_to == NOW
            assert old_state.superseded_by == ("obsidian:candidate-new",)
            assert new_state is not None
            assert new_state.supersedes == ("obsidian:context-old",)
            assert len(result.created_relation_ids) == 1

    anyio.run(scenario)


def test_contradiction_plan_preserves_both_and_creates_open_conflict(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with _repository(tmp_path, "apply-conflict.db") as repository:
            candidate = _candidate()
            decision = MemoryRelationClassifier().classify(
                candidate,
                _existing(),
            )
            assert decision.relation is MemoryRelationType.CONTRADICTS
            plan = MemoryReconciliationPlanService().build(
                candidate=candidate,
                decisions=(decision,),
                idempotency_key="apply-conflict",
            )
            await repository.save_plan(plan)
            gateway = RecordingCanonicalGateway()

            service = MemoryReconciliationApplyService(
                repository=repository,
                canonical_gateway=gateway,
            )
            with pytest.raises(
                MemoryContextValidationError,
                match="RECONCILIATION_REVIEW_APPROVAL_REQUIRED",
            ):
                await service.apply(plan.plan_id)
            assert gateway.created == []

            result = await service.apply(
                plan.plan_id,
                review_approved=True,
                reviewer="memory-steward",
            )

            assert result.status is MemoryReconciliationStatus.APPLIED
            assert result.reviewed_by == "memory-steward"
            assert result.reviewed_at is not None
            assert result.hard_delete_performed is False
            assert len(result.created_conflict_set_ids) == 1
            assert result.review_queue_item_ids == (f"memory-review:{plan.plan_id}",)
            conflicts = await repository.list_conflicts()
            assert len(conflicts) == 1
            assert conflicts[0].context_ids == (
                "obsidian:candidate-new",
                "obsidian:context-old",
            )
            old_state = await repository.get_temporal_state("obsidian:context-old")
            assert old_state is not None
            assert old_state.is_current is True
            assert old_state.conflict_set_ids == result.created_conflict_set_ids

    anyio.run(scenario)


def test_failed_readback_is_recorded_as_partial_apply_and_can_retry(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with _repository(tmp_path, "apply-retry.db") as repository:
            plan = MemoryReconciliationPlanService().build(
                candidate=_candidate(),
                decisions=(),
                idempotency_key="apply-retry",
            )
            await repository.save_plan(plan)
            gateway = RecordingCanonicalGateway(verify_result=False)
            service = MemoryReconciliationApplyService(
                repository=repository,
                canonical_gateway=gateway,
            )

            failed = await service.apply(plan.plan_id)
            assert failed.status is MemoryReconciliationStatus.PARTIAL_APPLY
            assert failed.failure_code is MemoryReconciliationFailureCode.PARTIAL_APPLY

            gateway.verify_result = True
            retried = await service.apply(plan.plan_id, retry_failed=True)
            assert retried.status is MemoryReconciliationStatus.APPLIED
            assert gateway.created == [
                "obsidian:candidate-new",
                "obsidian:candidate-new",
            ]

    anyio.run(scenario)
