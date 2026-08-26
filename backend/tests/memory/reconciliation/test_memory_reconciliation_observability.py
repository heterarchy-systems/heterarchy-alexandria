"""Structured observability tests for memory reconciliation workflows."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pytest import LogCaptureFixture

from app.memory.application.reconciliation.runtime.memory_reconciliation_observability import (
    log_reconciliation_apply,
    log_reconciliation_preview,
)
from app.memory.domain.contracts.memory_reconciliation_candidate_compute_contracts import (
    ReconciliationCandidateComputeMetrics,
)
from app.memory.domain.entities.memory_reconciliation import (
    CanonicalClaim,
    MemoryCandidate,
    MemoryEvolutionCandidateEvidence,
    MemoryReconciliationAction,
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
    MemoryRelationDecision,
    MemoryRelationScores,
    MemorySourceReference,
)
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryDecisionSource,
    MemoryReconciliationActionType,
    MemoryReconciliationFailureCode,
    MemoryReconciliationStatus,
    MemoryRelationType,
)

NOW = datetime(2026, 7, 25, tzinfo=UTC)
SECRET_BODY = "heterarchy-alexandria secret memory body that must never enter logs."


def _candidate() -> MemoryCandidate:
    claim = CanonicalClaim(
        subject="heterarchy-alexandria",
        predicate="uses",
        object="Obsidian",
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
    )
    source = MemorySourceReference(
        source_type="user",
        source_id="source-1",
        title="Storage evidence",
        detail_path="Contexts/storage.md",
    )
    return MemoryCandidate(
        candidate_id="candidate-1",
        title="Canonical storage decision",
        body=SECRET_BODY,
        canonical_claims=(claim,),
        scope=ContextScope.PROJECT,
        project="heterarchy-alexandria",
        tags=("memory",),
        source_refs=(source,),
        recorded_at=NOW,
        observed_at=NOW,
        valid_from=NOW,
        valid_to=None,
        requested_lifecycle="active",
        content_hash="candidate-hash",
    )


def _plan() -> MemoryReconciliationPlan:
    decision = MemoryRelationDecision(
        candidate_id="candidate-1",
        existing_context_id="obsidian:existing-1",
        relation=MemoryRelationType.CONTRADICTS,
        confidence=0.91,
        reason="Claims have conflicting polarity in the same temporal scope.",
        evidence_refs=(),
        claim_matches=("heterarchy-alexandria|uses|Obsidian",),
        scores=MemoryRelationScores(
            semantic_similarity=0.95,
            claim_overlap=1.0,
            scope_compatibility=1.0,
            temporal_compatibility=1.0,
            source_independence=1.0,
            polarity_conflict=1.0,
            specificity_change=0.0,
            freshness=0.8,
        ),
        decision_source=MemoryDecisionSource.DETERMINISTIC,
        policy_version="memory-reconciliation-v1",
        created_at=NOW,
    )
    action = MemoryReconciliationAction(
        action_type=MemoryReconciliationActionType.CREATE_CONFLICT_SET,
        target_context_id="obsidian:existing-1",
        relation=MemoryRelationType.CONTRADICTS,
        reason="Preserve both claims in an open conflict set.",
    )
    return MemoryReconciliationPlan(
        plan_id="plan-1",
        candidate=_candidate(),
        decisions=(decision,),
        primary_decision=MemoryRelationType.CONTRADICTS,
        actions=(action,),
        warnings=(),
        conflicting_context_ids=("obsidian:existing-1",),
        requires_review=True,
        idempotency_key="key-1",
        status=MemoryReconciliationStatus.REVIEW_REQUIRED,
        created_at=NOW,
        candidate_evidence=MemoryEvolutionCandidateEvidence(
            compute_authority="rust:reconciliation_candidates:v1",
            candidate_item_id="candidate-1",
            compared_context_ids=("obsidian:existing-1",),
            candidate_pairs=(),
            metrics=ReconciliationCandidateComputeMetrics(
                input_items=2,
                comparison_pairs=1,
                qualifying_pairs=1,
                retained_pairs=1,
                exact_duplicate_groups=0,
            ),
        ),
    )


def test_preview_and_apply_logs_are_structured_and_content_safe(
    caplog: LogCaptureFixture,
) -> None:
    plan = _plan()
    result = MemoryReconciliationResult(
        reconciliation_id="reconciliation-1",
        plan_id=plan.plan_id,
        status=MemoryReconciliationStatus.PARTIAL_APPLY,
        created_context_ids=("obsidian:new-1",),
        created_conflict_set_ids=("conflict-1",),
        warnings=("read-back failed",),
        hard_delete_performed=False,
        failure_code=MemoryReconciliationFailureCode.PARTIAL_APPLY,
        completed_at=NOW,
    )

    with caplog.at_level(
        logging.INFO,
        logger=(
            "app.memory.application.reconciliation.runtime.memory_reconciliation_observability"
        ),
    ):
        log_reconciliation_preview(plan, duration_ms=4.5, reused=False)
        log_reconciliation_apply(
            plan,
            result,
            duration_ms=8.25,
            reused=False,
        )

    preview_record, apply_record = caplog.records[-2:]
    preview_attributes = preview_record.__dict__["attributes"]
    apply_attributes = apply_record.__dict__["attributes"]

    assert preview_record.__dict__["event"] == (
        "memory_reconciliation_preview_completed"
    )
    assert preview_record.__dict__["duration_ms"] == 4.5
    assert preview_attributes == {
        "plan_id": "plan-1",
        "candidate_id": "candidate-1",
        "compared_context_count": 1,
        "candidate_compute_authority": "rust:reconciliation_candidates:v1",
        "candidate_comparison_pair_count": 1,
        "candidate_qualifying_pair_count": 1,
        "candidate_retained_pair_count": 1,
        "candidate_exact_duplicate_group_count": 0,
        "selected_relation": "CONTRADICTS",
        "confidence": 0.91,
        "decision_source": "DETERMINISTIC",
        "action_count": 1,
        "conflict_count": 1,
        "requires_review": True,
        "reused": False,
        "status": "REVIEW_REQUIRED",
    }
    assert apply_record.levelno == logging.WARNING
    assert apply_record.__dict__["event"] == "memory_reconciliation_apply_failed"
    assert apply_record.__dict__["duration_ms"] == 8.25
    assert apply_attributes["reconciliation_id"] == "reconciliation-1"
    assert apply_attributes["status"] == "PARTIAL_APPLY"
    assert apply_attributes["failure_code"] == "PARTIAL_APPLY"
    assert apply_attributes["created_context_count"] == 1
    assert apply_attributes["created_conflict_count"] == 1
    assert apply_attributes["hard_delete_performed"] is False
    assert SECRET_BODY not in caplog.text
    assert SECRET_BODY not in str(preview_attributes)
    assert SECRET_BODY not in str(apply_attributes)
