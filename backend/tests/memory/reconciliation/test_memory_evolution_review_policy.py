"""Pure safety-policy tests for Phase 7 Memory Evolution review gating."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.memory.application.reconciliation.plans.memory_reconciliation_apply_service import (
    _validated_reviewer,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryRelationDecision,
    MemoryRelationScores,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryDecisionSource,
    MemoryReconciliationActionType,
    MemoryReconciliationStatus,
    MemoryRelationType,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def _candidate() -> MemoryCandidate:
    """Return one deterministic proposal without invoking hashing adapters."""
    return MemoryCandidate(
        candidate_id="candidate-new",
        title="Current storage decision",
        body="heterarchy-alexandria uses PostgreSQL.",
        canonical_claims=(),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=(),
        source_refs=(),
        recorded_at=NOW,
        observed_at=None,
        valid_from=NOW,
        valid_to=None,
        requested_lifecycle="active",
        content_hash="a" * 64,
    )


def _decision(relation: MemoryRelationType) -> MemoryRelationDecision:
    """Return one fully typed semantic decision for plan-policy tests."""
    return MemoryRelationDecision(
        candidate_id="candidate-new",
        existing_context_id="context-old",
        relation=relation,
        confidence=0.95,
        reason="test decision",
        evidence_refs=(),
        claim_matches=(),
        scores=MemoryRelationScores(
            semantic_similarity=0.95,
            claim_overlap=1.0,
            scope_compatibility=1.0,
            temporal_compatibility=1.0,
            source_independence=1.0,
            polarity_conflict=0.0,
            specificity_change=0.0,
            freshness=1.0,
        ),
        decision_source=MemoryDecisionSource.DETERMINISTIC,
        policy_version="test-v1",
        created_at=NOW,
    )


def test_supersession_is_review_required_before_canonical_mutation() -> None:
    """A supersession proposal must be queued for explicit Steward review."""
    plan = MemoryReconciliationPlanService().build(
        candidate=_candidate(),
        decisions=(_decision(MemoryRelationType.SUPERSEDES),),
        idempotency_key="review-supersession",
    )

    assert plan.requires_review is True
    assert plan.status is MemoryReconciliationStatus.REVIEW_REQUIRED
    assert MemoryReconciliationActionType.MARK_SUPERSEDED in {
        action.action_type for action in plan.actions
    }
    assert MemoryReconciliationActionType.QUEUE_REVIEW in {
        action.action_type for action in plan.actions
    }
    with pytest.raises(
        MemoryContextValidationError,
        match="RECONCILIATION_REVIEW_APPROVAL_REQUIRED",
    ):
        _validated_reviewer(plan, review_approved=False, reviewer=None)
    assert (
        _validated_reviewer(
            plan,
            review_approved=True,
            reviewer="  memory-steward  ",
        )
        == "memory-steward"
    )


def test_non_review_plan_does_not_require_or_record_reviewer() -> None:
    """Ordinary unrelated proposals must remain automatically applicable."""
    plan = MemoryReconciliationPlanService().build(
        candidate=_candidate(),
        decisions=(),
        idempotency_key="review-unrelated",
    )

    assert plan.requires_review is False
    assert plan.status is MemoryReconciliationStatus.PLANNED
    assert _validated_reviewer(plan, review_approved=False, reviewer=None) is None
