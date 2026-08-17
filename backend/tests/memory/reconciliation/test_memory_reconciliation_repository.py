"""Repository round-trip tests for memory reconciliation persistence."""

from __future__ import annotations

import os

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import anyio
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryCandidate,
    MemoryConflictSet,
    MemoryReconciliationAction,
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
    MemoryRelationRecord,
    MemoryRelationScores,
    MemorySourceReference,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryConflictStatus,
    MemoryDecisionSource,
    MemoryReconciliationActionType,
    MemoryReconciliationStatus,
    MemoryRelationType,
)
from app.memory.infrastructure.repositories.memory_reconciliation_repository import (
    SqlAlchemyMemoryReconciliationRepository,
)
from app.shared.infrastructure.database import Database

NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _plan() -> MemoryReconciliationPlan:
    source = MemorySourceReference(
        source_type="context",
        source_id="source-1",
        title="Source",
        detail_path="Contexts/source.md",
    )
    candidate = MemoryCandidate(
        candidate_id="candidate-1",
        title="Candidate",
        body="heterarchy-alexandria uses Redis.",
        canonical_claims=(
            CanonicalClaim(
                subject="heterarchy-alexandria",
                predicate="uses",
                object="Redis",
                scope=ContextScope.PROJECT,
                project="heterarchy-alexandria",
            ),
        ),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=("memory",),
        source_refs=(source,),
        recorded_at=NOW,
        observed_at=NOW,
        valid_from=None,
        valid_to=None,
        requested_lifecycle="active",
        content_hash="hash-1",
    )
    return MemoryReconciliationPlan(
        plan_id="11111111-1111-1111-1111-111111111111",
        candidate=candidate,
        decisions=(),
        primary_decision=MemoryRelationType.UNRELATED,
        actions=(
            MemoryReconciliationAction(
                action_type=MemoryReconciliationActionType.CREATE_CONTEXT,
                target_context_id=None,
                relation=None,
                reason="New independent memory",
            ),
        ),
        warnings=(),
        conflicting_context_ids=(),
        requires_review=False,
        idempotency_key="idem-1",
        status=MemoryReconciliationStatus.PLANNED,
        created_at=NOW,
    )


def test_reconciliation_repository_round_trips_all_audit_records(
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
                repository = SqlAlchemyMemoryReconciliationRepository(session)
                plan = _plan()
                saved_plan = await repository.save_plan(plan)
                duplicate_plan = await repository.save_plan(
                    replace(
                        plan,
                        plan_id="22222222-2222-2222-2222-222222222222",
                    )
                )
                review_plan = replace(
                    plan,
                    plan_id="22222222-2222-2222-2222-222222222223",
                    candidate=replace(plan.candidate, candidate_id="candidate-review"),
                    primary_decision=MemoryRelationType.UNKNOWN,
                    requires_review=True,
                    idempotency_key="idem-review",
                    status=MemoryReconciliationStatus.REVIEW_REQUIRED,
                )
                saved_review_plan = await repository.save_plan(review_plan)
                result = MemoryReconciliationResult(
                    reconciliation_id="33333333-3333-3333-3333-333333333333",
                    plan_id=plan.plan_id,
                    status=MemoryReconciliationStatus.APPLIED,
                    created_context_ids=("obsidian:new-context",),
                    hard_delete_performed=False,
                    completed_at=NOW,
                )
                saved_result = await repository.save_result(result)
                scores = MemoryRelationScores(
                    semantic_similarity=1.0,
                    claim_overlap=1.0,
                    scope_compatibility=1.0,
                    temporal_compatibility=1.0,
                    source_independence=1.0,
                    polarity_conflict=0.0,
                    specificity_change=0.0,
                    freshness=0.0,
                )
                relation = MemoryRelationRecord(
                    relation_id="44444444-4444-4444-4444-444444444444",
                    source_context_id="obsidian:new-context",
                    target_context_id="obsidian:old-context",
                    candidate_id="candidate-1",
                    relation=MemoryRelationType.SUPPORTS,
                    confidence=0.98,
                    reason="Independent evidence",
                    decision_source=MemoryDecisionSource.DETERMINISTIC,
                    policy_version="memory-reconciliation-v1",
                    evidence_refs=plan.candidate.source_refs,
                    claim_matches=("heterarchy-alexandria|uses|Redis",),
                    scores=scores,
                    created_at=NOW,
                )
                saved_relation = await repository.upsert_relation(relation)
                duplicate_relation = await repository.upsert_relation(
                    replace(
                        relation,
                        relation_id="55555555-5555-5555-5555-555555555555",
                    )
                )
                conflict = MemoryConflictSet(
                    conflict_set_id="66666666-6666-6666-6666-666666666666",
                    context_ids=("obsidian:new-context", "obsidian:old-context"),
                    candidate_id="candidate-1",
                    subject_key="heterarchy-alexandria",
                    claim_key="heterarchy-alexandria|uses",
                    scope=ContextScope.PROJECT,
                    validity_overlap=True,
                    reason="Conflicting objects",
                    status=MemoryConflictStatus.OPEN,
                    resolution=None,
                    created_at=NOW,
                    resolved_at=None,
                )
                saved_conflict = await repository.upsert_conflict(conflict)
                temporal = MemoryTemporalState(
                    context_id="obsidian:new-context",
                    recorded_at=NOW,
                    observed_at=NOW,
                    valid_from=NOW,
                    valid_to=None,
                    is_current=True,
                    conflict_set_ids=(conflict.conflict_set_id,),
                    relation_summary=("supports:obsidian:old-context",),
                )
                saved_temporal = await repository.upsert_temporal_state(temporal)
                await session.commit()

                assert saved_plan == plan
                assert duplicate_plan.plan_id == plan.plan_id
                assert saved_review_plan == review_plan
                assert await repository.list_review_plans() == [review_plan]
                assert await repository.get_plan(plan.plan_id) == plan
                assert saved_result == result
                assert await repository.get_result(result.reconciliation_id) == result
                assert saved_relation == relation
                assert duplicate_relation.relation_id == relation.relation_id
                assert await repository.list_relations("obsidian:new-context") == [
                    relation
                ]
                assert saved_conflict == conflict
                assert await repository.list_conflicts(
                    status=MemoryConflictStatus.OPEN
                ) == [conflict]
                assert saved_temporal == temporal
                assert (
                    await repository.get_temporal_state(temporal.context_id) == temporal
                )
        finally:
            await database.shutdown()

    anyio.run(scenario)
