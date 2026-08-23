"""Build immutable reconciliation plans from relation decisions."""

from __future__ import annotations

import hashlib

from app.memory.application.reconciliation.plans.memory_reconciliation_policy import (
    actions_for_decision,
    select_primary_decision,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryReconciliationPlan,
    MemoryRelationDecision,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationStatus,
    MemoryRelationType,
)
from app.shared.infrastructure.identifiers import new_uuid
from app.shared.types.types_convert_utils import now_utc


class MemoryReconciliationPlanService:
    """Select primary policy outcomes and produce an auditable preview plan."""

    def build(
        self,
        candidate: MemoryCandidate,
        decisions: tuple[MemoryRelationDecision, ...],
        idempotency_key: str | None = None,
    ) -> MemoryReconciliationPlan:
        """Build one deterministic plan without mutating canonical memory.

        Args:
            candidate: Candidate.
            decisions: Decisions.
            idempotency_key: Idempotency key.

        Returns:
            MemoryReconciliationPlan: Operation result.
        """
        primary = select_primary_decision(decisions)
        primary_relation = (
            MemoryRelationType.UNRELATED if primary is None else primary.relation
        )
        requires_review = primary_relation in {
            MemoryRelationType.CONTRADICTS,
            MemoryRelationType.UNKNOWN,
        }
        warnings: list[str] = []
        if not candidate.canonical_claims:
            warnings.append(
                "Canonical claims were unavailable; semantic classification is limited."
            )
        if not decisions:
            warnings.append("No existing Context candidate was recalled.")
        if primary_relation is MemoryRelationType.CONTRADICTS:
            warnings.append(
                "An unresolved contradiction must remain visible to recall."
            )
        if primary_relation is MemoryRelationType.UNKNOWN:
            warnings.append(
                "Relation confidence is insufficient for automatic resolution."
            )
        conflicting_context_ids = tuple(
            dict.fromkeys(
                decision.existing_context_id
                for decision in decisions
                if decision.relation is MemoryRelationType.CONTRADICTS
            )
        )
        return MemoryReconciliationPlan(
            plan_id=new_uuid(),
            candidate=candidate,
            decisions=decisions,
            primary_decision=primary_relation,
            actions=actions_for_decision(primary),
            warnings=tuple(warnings),
            conflicting_context_ids=conflicting_context_ids,
            requires_review=requires_review,
            idempotency_key=(
                idempotency_key.strip()
                if idempotency_key is not None and idempotency_key.strip()
                else _generated_idempotency_key(candidate)
            ),
            status=(
                MemoryReconciliationStatus.REVIEW_REQUIRED
                if requires_review
                else MemoryReconciliationStatus.PLANNED
            ),
            created_at=now_utc(),
        )


def _generated_idempotency_key(candidate: MemoryCandidate) -> str:
    """Execute generated idempotency key.

    Args:
        candidate: Candidate used by this operation.

    Returns:
        str result produced by generated idempotency key.
    """
    identity_parts = (
        candidate.scope.value,
        candidate.project or "",
        candidate.workspace_id or "",
        candidate.agent_id or "",
        candidate.user_id or "",
        candidate.session_id or "",
        candidate.content_hash,
    )
    return hashlib.sha256("|".join(identity_parts).encode("utf-8")).hexdigest()
