"""Pure mappings from cycle execution evidence to public result values."""

from __future__ import annotations

from dataclasses import replace

from app.memory.domain.entities.memory_cycle import (
    MemoryCycleChildOutcome,
    MemoryCycleCompactChange,
    MemoryCyclePhase,
    MemoryCycleResult,
    MemoryCycleSourceSnapshot,
)
from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationPlan
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleCheckpointState,
    MemoryCycleStatus,
)


def preview_child_outcome(
    plan: MemoryReconciliationPlan,
) -> MemoryCycleChildOutcome:
    """Map one in-memory child plan into bounded output evidence.

    Args:
        plan: Dry-run child reconciliation plan.

    Returns:
        Bounded child outcome summary for preview output.
    """
    return MemoryCycleChildOutcome(
        child_plan_key=plan.idempotency_key,
        plan_id=None,
        result_id=None,
        relation=plan.primary_decision,
        status=plan.status.value,
        requires_review=plan.requires_review,
        warnings=plan.warnings,
    )


def review_child_outcome(
    plan: MemoryReconciliationPlan,
) -> MemoryCycleChildOutcome:
    """Map one persisted review-required child plan without auto-approval.

    Args:
        plan: Persisted child reconciliation plan requiring human review.

    Returns:
        Child outcome summary marked as review required.
    """
    return MemoryCycleChildOutcome(
        child_plan_key=plan.idempotency_key,
        plan_id=plan.plan_id,
        result_id=None,
        relation=plan.primary_decision,
        status=MemoryCycleStatus.REVIEW_REQUIRED.value,
        requires_review=True,
        warnings=plan.warnings,
    )


def final_result(
    admitted: MemoryCycleResult,
    child_outcomes: tuple[MemoryCycleChildOutcome, ...],
    source_snapshot: tuple[MemoryCycleSourceSnapshot, ...],
    compact_change: MemoryCycleCompactChange,
    phases: tuple[MemoryCyclePhase, ...],
    warnings: tuple[str, ...],
    retrieval_failed: bool,
    review_required: bool,
) -> tuple[MemoryCycleResult, MemoryCycleCheckpointState]:
    """Assemble final output evidence while preserving cycle status precedence.

    Args:
        admitted: Admitted cycle result baseline.
        child_outcomes: Recorded child reconciliation outcomes.
        source_snapshot: Post-apply source revision snapshots.
        compact_change: Final compact publication change record.
        phases: Recorded execution phases.
        warnings: Deduplicated cycle warnings.
        retrieval_failed: Whether post-apply retrieval verification degraded.
        review_required: Whether any child or compact requires human review.

    Returns:
        Tuple of final MemoryCycleResult and terminal MemoryCycleCheckpointState.
    """
    if retrieval_failed:
        status = MemoryCycleStatus.PARTIAL
        checkpoint_state = MemoryCycleCheckpointState.PARTIAL
    elif review_required:
        status = MemoryCycleStatus.REVIEW_REQUIRED
        checkpoint_state = MemoryCycleCheckpointState.REVIEW_REQUIRED
    else:
        status = MemoryCycleStatus.APPLIED
        checkpoint_state = MemoryCycleCheckpointState.COMPLETED
    result = replace(
        admitted,
        status=status,
        child_outcomes=child_outcomes,
        source_snapshot=source_snapshot,
        compact_change=compact_change,
        buckets=replace(
            admitted.buckets,
            compact_changes=(compact_change,),
        ),
        phases=phases,
        warnings=warnings,
        elapsed_ms=0.0,
    )
    return result, checkpoint_state
