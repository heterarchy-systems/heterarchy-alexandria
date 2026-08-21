"""Pure action policy for memory reconciliation decisions."""

from __future__ import annotations

from app.memory.domain.entities.memory_reconciliation import (
    MemoryReconciliationAction,
    MemoryRelationDecision,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationActionType,
    MemoryRelationType,
)

_RELATION_PRIORITY: dict[MemoryRelationType, int] = {
    MemoryRelationType.DUPLICATE: 70,
    MemoryRelationType.CONTRADICTS: 60,
    MemoryRelationType.SUPERSEDES: 50,
    MemoryRelationType.SUPPORTS: 40,
    MemoryRelationType.EXTENDS: 30,
    MemoryRelationType.UNKNOWN: 20,
    MemoryRelationType.UNRELATED: 10,
}


def select_primary_decision(
    decisions: tuple[MemoryRelationDecision, ...],
) -> MemoryRelationDecision | None:
    """Select the safest highest-priority decision across recalled Contexts.

    Args:
        decisions: Decisions.

    Returns:
        MemoryRelationDecision | None: Operation result.
    """
    return max(
        decisions,
        key=lambda item: (_RELATION_PRIORITY[item.relation], item.confidence),
        default=None,
    )


def actions_for_decision(
    decision: MemoryRelationDecision | None,
) -> tuple[MemoryReconciliationAction, ...]:
    """Translate one primary decision into explicit state-transition actions.

    Args:
        decision: Decision.

    Returns:
        tuple[MemoryReconciliationAction, ...]: Operation result.
    """
    if decision is None:
        return (
            MemoryReconciliationAction(
                action_type=MemoryReconciliationActionType.CREATE_CONTEXT,
                target_context_id=None,
                relation=None,
                reason="No related Context was recalled",
            ),
        )
    target = decision.existing_context_id
    relation = decision.relation
    if relation is MemoryRelationType.DUPLICATE:
        return (
            _action(
                MemoryReconciliationActionType.MERGE_EVIDENCE,
                target,
                relation,
                "Merge new provenance into the canonical duplicate",
            ),
            _action(
                MemoryReconciliationActionType.NOOP,
                target,
                relation,
                "Do not create a duplicate Context",
            ),
        )
    if relation is MemoryRelationType.SUPPORTS:
        return (
            _action(
                MemoryReconciliationActionType.MERGE_EVIDENCE,
                target,
                relation,
                "Attach independent supporting evidence",
            ),
            _action(
                MemoryReconciliationActionType.CREATE_RELATION,
                target,
                relation,
                "Persist the supports relation",
            ),
        )
    if relation is MemoryRelationType.EXTENDS:
        return (
            _action(
                MemoryReconciliationActionType.CREATE_CONTEXT,
                target,
                relation,
                "Create the more specific Context",
            ),
            _action(
                MemoryReconciliationActionType.CREATE_RELATION,
                target,
                relation,
                "Persist the extends relation",
            ),
        )
    if relation is MemoryRelationType.CONTRADICTS:
        return (
            _action(
                MemoryReconciliationActionType.CREATE_CONTEXT,
                target,
                relation,
                "Preserve the conflicting candidate as a separate Context",
            ),
            _action(
                MemoryReconciliationActionType.CREATE_RELATION,
                target,
                relation,
                "Persist the contradiction relation",
            ),
            _action(
                MemoryReconciliationActionType.CREATE_CONFLICT_SET,
                target,
                relation,
                "Preserve both claims in a first-class conflict set",
            ),
            _action(
                MemoryReconciliationActionType.QUEUE_REVIEW,
                target,
                relation,
                "Require an explicit conflict resolution",
            ),
        )
    if relation is MemoryRelationType.SUPERSEDES:
        return (
            _action(
                MemoryReconciliationActionType.CREATE_CONTEXT,
                target,
                relation,
                "Create the newer current Context",
            ),
            _action(
                MemoryReconciliationActionType.CREATE_RELATION,
                target,
                relation,
                "Persist the supersedes relation",
            ),
            _action(
                MemoryReconciliationActionType.MARK_SUPERSEDED,
                target,
                relation,
                "Close the previous Context validity interval without deleting it",
            ),
        )
    if relation is MemoryRelationType.UNKNOWN:
        return (
            _action(
                MemoryReconciliationActionType.CREATE_CONTEXT,
                target,
                relation,
                "Preserve the candidate as a draft Context",
            ),
            _action(
                MemoryReconciliationActionType.PRESERVE_CANDIDATE,
                target,
                relation,
                "Retain the candidate and classification evidence",
            ),
            _action(
                MemoryReconciliationActionType.QUEUE_REVIEW,
                target,
                relation,
                "Require review because the relation is unknown",
            ),
        )
    return (
        _action(
            MemoryReconciliationActionType.CREATE_CONTEXT,
            target,
            relation,
            "Create an unrelated new Context",
        ),
    )


def _action(
    action_type: MemoryReconciliationActionType,
    target_context_id: str | None,
    relation: MemoryRelationType | None,
    reason: str,
) -> MemoryReconciliationAction:
    return MemoryReconciliationAction(
        action_type=action_type,
        target_context_id=target_context_id,
        relation=relation,
        reason=reason,
    )
