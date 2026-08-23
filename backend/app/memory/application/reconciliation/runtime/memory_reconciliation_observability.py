"""Structured, content-safe observability for memory reconciliation workflows."""

from __future__ import annotations

import logging
from typing import TypedDict

from app.memory.domain.entities.memory_reconciliation import (
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
    MemoryRelationDecision,
)
from app.shared.types.extra_types import JSONObject

logger = logging.getLogger(__name__)


class MemoryReconciliationLogExtra(TypedDict):
    """Validated logging extras consumed by the JSON log formatter."""

    event: str
    duration_ms: float
    attributes: JSONObject


def log_reconciliation_preview(
    plan: MemoryReconciliationPlan,
    duration_ms: float,
    reused: bool,
) -> None:
    """Log a completed preview without exposing candidate or evidence content.

    Args:
        plan: Plan.
        duration_ms: Duration ms.
        reused: Reused.
    """
    logger.info(
        "Memory reconciliation preview completed",
        extra=_preview_extra(plan, duration_ms=duration_ms, reused=reused),
    )


def log_reconciliation_apply(
    plan: MemoryReconciliationPlan,
    result: MemoryReconciliationResult,
    duration_ms: float,
    reused: bool,
) -> None:
    """Log a completed apply attempt with only identifiers and aggregate state.

    Args:
        plan: Plan.
        result: Result.
        duration_ms: Duration ms.
        reused: Reused.
    """
    selected = _selected_decision(plan)
    attributes = _plan_attributes(plan, selected=selected, reused=reused)
    attributes.update(
        {
            "reconciliation_id": result.reconciliation_id,
            "status": result.status.value,
            "failure_code": (
                None if result.failure_code is None else result.failure_code.value
            ),
            "created_context_count": len(result.created_context_ids),
            "updated_context_count": len(result.updated_context_ids),
            "superseded_context_count": len(result.superseded_context_ids),
            "created_relation_count": len(result.created_relation_ids),
            "created_conflict_count": len(result.created_conflict_set_ids),
            "review_queue_item_count": len(result.review_queue_item_ids),
            "hard_delete_performed": result.hard_delete_performed,
        }
    )
    event = (
        "memory_reconciliation_apply_completed"
        if result.failure_code is None
        else "memory_reconciliation_apply_failed"
    )
    log_method = logger.info if result.failure_code is None else logger.warning
    log_method(
        "Memory reconciliation apply completed",
        extra=MemoryReconciliationLogExtra(
            event=event,
            duration_ms=duration_ms,
            attributes=attributes,
        ),
    )


def log_reconciliation_apply_exception(
    plan: MemoryReconciliationPlan,
    duration_ms: float,
    error_type: str,
) -> None:
    """Log an unexpected apply orchestration failure without the exception message.

    Args:
        plan: Plan.
        duration_ms: Duration ms.
        error_type: Error type.
    """
    attributes = _plan_attributes(
        plan,
        selected=_selected_decision(plan),
        reused=False,
    )
    attributes.update(
        {
            "status": "UNHANDLED_EXCEPTION",
            "failure_code": "UNHANDLED_EXCEPTION",
            "error_type": error_type,
            "hard_delete_performed": False,
        }
    )
    logger.exception(
        "Memory reconciliation apply raised an unexpected exception",
        extra=MemoryReconciliationLogExtra(
            event="memory_reconciliation_apply_exception",
            duration_ms=duration_ms,
            attributes=attributes,
        ),
    )


def _preview_extra(
    plan: MemoryReconciliationPlan,
    duration_ms: float,
    reused: bool,
) -> MemoryReconciliationLogExtra:
    """Execute preview extra.

    Args:
        plan: Plan used by this operation.
        duration_ms: Duration ms used by this operation.
        reused: Reused used by this operation.

    Returns:
        MemoryReconciliationLogExtra result produced by preview extra.
    """
    selected = _selected_decision(plan)
    attributes = _plan_attributes(plan, selected=selected, reused=reused)
    attributes["status"] = plan.status.value
    return MemoryReconciliationLogExtra(
        event="memory_reconciliation_preview_completed",
        duration_ms=duration_ms,
        attributes=attributes,
    )


def _plan_attributes(
    plan: MemoryReconciliationPlan,
    selected: MemoryRelationDecision | None,
    reused: bool,
) -> JSONObject:
    """Execute plan attributes.

    Args:
        plan: Plan used by this operation.
        selected: Selected used by this operation.
        reused: Reused used by this operation.

    Returns:
        JSONObject result produced by plan attributes.
    """
    return {
        "plan_id": plan.plan_id,
        "candidate_id": plan.candidate.candidate_id,
        "compared_context_count": len(plan.decisions),
        "selected_relation": plan.primary_decision.value,
        "confidence": None if selected is None else selected.confidence,
        "decision_source": (
            None if selected is None else selected.decision_source.value
        ),
        "action_count": len(plan.actions),
        "conflict_count": len(plan.conflicting_context_ids),
        "requires_review": plan.requires_review,
        "reused": reused,
    }


def _selected_decision(
    plan: MemoryReconciliationPlan,
) -> MemoryRelationDecision | None:
    """Execute selected decision.

    Args:
        plan: Plan used by this operation.

    Returns:
        MemoryRelationDecision | None result produced by selected decision.
    """
    for decision in plan.decisions:
        if decision.relation is plan.primary_decision:
            return decision
    return plan.decisions[0] if plan.decisions else None
