"""Persist relation, conflict, and temporal state produced by reconciliation."""

from __future__ import annotations

from dataclasses import replace

from app.memory.application.reconciliation.plans.memory_reconciliation_apply_policy import (
    claim_key,
    relation_id,
    relation_summary,
    required_created_context_id,
    subject_key,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryConflictSet,
    MemoryReconciliationPlan,
    MemoryRelationDecision,
    MemoryRelationRecord,
    MemoryTemporalState,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryConflictStatus,
    MemoryRelationType,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_use_case_repositories import (
    IMemoryReconciliationStateRepository,
)
from app.shared.types.types_convert_utils import now_utc


class MemoryReconciliationStateWriter:
    """Write reconciliation read-model state through the repository port."""

    def __init__(self, repository: IMemoryReconciliationStateRepository) -> None:
        self._repository = repository

    async def persist_primary_relation(
        self,
        plan: MemoryReconciliationPlan,
        primary: MemoryRelationDecision | None,
        created_context_id: str | None,
    ) -> MemoryRelationRecord:
        """Persist the plan's directed primary relation idempotently.

        Args:
            plan: Plan.
            primary: Primary.
            created_context_id: Created context id.

        Returns:
            MemoryRelationRecord: Operation result.
        """
        if primary is None:
            raise RuntimeError("Relation apply requires a primary decision")
        source_context_id = (
            created_context_id or f"evidence:{plan.candidate.candidate_id}"
        )
        relation = MemoryRelationRecord(
            relation_id=relation_id(
                source_context_id,
                primary.existing_context_id,
                primary.relation,
            ),
            source_context_id=source_context_id,
            target_context_id=primary.existing_context_id,
            candidate_id=plan.candidate.candidate_id,
            relation=primary.relation,
            confidence=primary.confidence,
            reason=primary.reason,
            decision_source=primary.decision_source,
            policy_version=primary.policy_version,
            evidence_refs=primary.evidence_refs,
            claim_matches=primary.claim_matches,
            scores=primary.scores,
            created_at=now_utc(),
        )
        return await self._repository.upsert_relation(relation)

    async def persist_conflict(
        self,
        plan: MemoryReconciliationPlan,
        primary: MemoryRelationDecision | None,
        created_context_id: str | None,
        conflict_set_id: str,
    ) -> MemoryConflictSet:
        """Persist a first-class open conflict while preserving both Contexts.

        Args:
            plan: Plan.
            primary: Primary.
            created_context_id: Created context id.
            conflict_set_id: Conflict set id.

        Returns:
            MemoryConflictSet: Operation result.
        """
        if primary is None or created_context_id is None:
            raise RuntimeError("Conflict apply requires both Context identities")
        conflict = MemoryConflictSet(
            conflict_set_id=conflict_set_id,
            context_ids=(created_context_id, primary.existing_context_id),
            candidate_id=plan.candidate.candidate_id,
            subject_key=subject_key(plan),
            claim_key=claim_key(plan, primary),
            scope=plan.candidate.scope,
            validity_overlap=primary.scores.temporal_compatibility > 0.0,
            reason=primary.reason,
            status=MemoryConflictStatus.OPEN,
            resolution=None,
            created_at=now_utc(),
            resolved_at=None,
        )
        return await self._repository.upsert_conflict(conflict)

    async def persist_temporal_states(
        self,
        plan: MemoryReconciliationPlan,
        primary: MemoryRelationDecision | None,
        created_context_id: str | None,
        conflict_set_ids: tuple[str, ...],
    ) -> None:
        """Write current, superseded, and conflict temporal overlays.

        Args:
            plan: Plan.
            primary: Primary.
            created_context_id: Created context id.
            conflict_set_ids: Conflict set ids.
        """
        candidate = plan.candidate
        target_context_id = None if primary is None else primary.existing_context_id
        if created_context_id is not None:
            await self._repository.upsert_temporal_state(
                MemoryTemporalState(
                    context_id=created_context_id,
                    recorded_at=candidate.recorded_at,
                    observed_at=candidate.observed_at,
                    valid_from=candidate.valid_from,
                    valid_to=candidate.valid_to,
                    is_current=True,
                    conflict_set_ids=conflict_set_ids,
                    supersedes=(
                        (target_context_id,)
                        if primary is not None
                        and primary.relation is MemoryRelationType.SUPERSEDES
                        and target_context_id is not None
                        else ()
                    ),
                    relation_summary=relation_summary(primary),
                )
            )
        if primary is None or target_context_id is None:
            return
        existing = await self._repository.get_temporal_state(target_context_id)
        base = existing or MemoryTemporalState(
            context_id=target_context_id,
            recorded_at=candidate.recorded_at,
            observed_at=None,
            valid_from=None,
            valid_to=None,
            is_current=True,
        )
        if primary.relation is MemoryRelationType.SUPERSEDES:
            replacement_id = required_created_context_id(created_context_id)
            base = replace(
                base,
                valid_to=(
                    candidate.valid_from
                    or candidate.observed_at
                    or candidate.recorded_at
                ),
                is_current=False,
                superseded_by=tuple(
                    dict.fromkeys((*base.superseded_by, replacement_id))
                ),
                relation_summary=tuple(
                    dict.fromkeys(
                        (*base.relation_summary, f"superseded_by:{replacement_id}")
                    )
                ),
            )
        elif primary.relation is MemoryRelationType.CONTRADICTS:
            base = replace(
                base,
                conflict_set_ids=tuple(
                    dict.fromkeys((*base.conflict_set_ids, *conflict_set_ids))
                ),
                relation_summary=tuple(
                    dict.fromkeys(
                        (
                            *base.relation_summary,
                            f"contradicts:{created_context_id}",
                        )
                    )
                ),
            )
        await self._repository.upsert_temporal_state(base)
