"""Pure helpers for reconciliation apply orchestration."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from app.memory.domain.entities.memory_reconciliation import (
    MemoryReconciliationPlan,
    MemoryRelationDecision,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationActionType,
    MemoryRelationType,
)


def primary_decision(
    plan: MemoryReconciliationPlan,
) -> MemoryRelationDecision | None:
    """Return the decision selected as the plan's primary relation.

    Args:
        plan: Plan.

    Returns:
        MemoryRelationDecision | None: Operation result.
    """
    return next(
        (
            decision
            for decision in plan.decisions
            if decision.relation is plan.primary_decision
        ),
        None,
    )


def has_action(
    plan: MemoryReconciliationPlan,
    action_type: MemoryReconciliationActionType,
) -> bool:
    """Return whether a plan includes one explicit action type.

    Args:
        plan: Plan.
        action_type: Action type.

    Returns:
        bool: Operation result.
    """
    return any(action.action_type is action_type for action in plan.actions)


def required_target(decision: MemoryRelationDecision | None) -> str:
    """Return a required decision target or fail the invalid plan.

    Args:
        decision: Decision.

    Returns:
        str: Operation result.
    """
    if decision is None:
        raise RuntimeError("Reconciliation action requires a target Context")
    return decision.existing_context_id


def required_created_context_id(context_id: str | None) -> str:
    """Return a required created Context ID or fail the invalid plan.

    Args:
        context_id: Context id.

    Returns:
        str: Operation result.
    """
    if context_id is None:
        raise RuntimeError("Reconciliation action requires a created Context")
    return context_id


def candidate_lifecycle(plan: MemoryReconciliationPlan) -> str:
    """Select a canonical Context lifecycle that preserves review requirements.

    Args:
        plan: Plan.

    Returns:
        str: Operation result.
    """
    if plan.requires_review:
        return "pending_review"
    requested = plan.candidate.requested_lifecycle
    return requested if requested in {"active", "current", "draft"} else "active"


def conflict_ids(
    plan: MemoryReconciliationPlan,
    primary: MemoryRelationDecision | None,
) -> tuple[str, ...]:
    """Return stable conflict identifiers for a contradiction plan.

    Args:
        plan: Plan.
        primary: Primary.

    Returns:
        tuple[str, ...]: Operation result.
    """
    if primary is None or primary.relation is not MemoryRelationType.CONTRADICTS:
        return ()
    return (
        str(
            uuid5(
                NAMESPACE_URL,
                f"memory-conflict:{plan.plan_id}:{claim_key(plan, primary)}",
            )
        ),
    )


def claim_key(
    plan: MemoryReconciliationPlan,
    decision: MemoryRelationDecision,
) -> str:
    """Return the canonical claim key used for conflict idempotency.

    Args:
        plan: Plan.
        decision: Decision.

    Returns:
        str: Operation result.
    """
    if decision.claim_matches:
        return decision.claim_matches[0]
    if plan.candidate.canonical_claims:
        claim = plan.candidate.canonical_claims[0]
        return f"{claim.subject}|{claim.predicate}|{claim.object}"
    return f"candidate:{plan.candidate.candidate_id}"


def subject_key(plan: MemoryReconciliationPlan) -> str:
    """Return a stable normalized subject key for one candidate.

    Args:
        plan: Plan.

    Returns:
        str: Operation result.
    """
    if plan.candidate.canonical_claims:
        return plan.candidate.canonical_claims[0].subject.casefold()
    return plan.candidate.title.casefold()


def relation_summary(
    decision: MemoryRelationDecision | None,
) -> tuple[str, ...]:
    """Return one compact relation summary for temporal overlays.

    Args:
        decision: Decision.

    Returns:
        tuple[str, ...]: Operation result.
    """
    if decision is None:
        return ()
    return (f"{decision.relation.value.lower()}:{decision.existing_context_id}",)


def result_id(plan_id: str) -> str:
    """Return the stable execution result identifier for one plan.

    Args:
        plan_id: Plan id.

    Returns:
        str: Operation result.
    """
    return str(uuid5(NAMESPACE_URL, f"memory-reconciliation-result:{plan_id}"))


def relation_id(
    source_context_id: str,
    target_context_id: str,
    relation: MemoryRelationType,
) -> str:
    """Return the stable identifier for one directed relation identity.

    Args:
        source_context_id: Source context id.
        target_context_id: Target context id.
        relation: Relation.

    Returns:
        str: Operation result.
    """
    return str(
        uuid5(
            NAMESPACE_URL,
            f"memory-relation:{source_context_id}:{target_context_id}:{relation.value}",
        )
    )


def review_item_id(plan_id: str) -> str:
    """Return the stable review queue identity reserved for one plan.

    Args:
        plan_id: Plan id.

    Returns:
        str: Operation result.
    """
    return f"memory-review:{plan_id}"
