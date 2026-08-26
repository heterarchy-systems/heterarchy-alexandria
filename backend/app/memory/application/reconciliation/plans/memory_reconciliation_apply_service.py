"""Idempotently apply one validated memory reconciliation plan."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter

from app.memory.application.reconciliation.plans.memory_reconciliation_apply_policy import (
    candidate_lifecycle,
    conflict_ids,
    has_action,
    primary_decision,
    required_target,
    result_id,
    review_item_id,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_state_writer import (
    MemoryReconciliationStateWriter,
)
from app.memory.application.reconciliation.runtime.memory_reconciliation_observability import (
    log_reconciliation_apply,
    log_reconciliation_apply_exception,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryReconciliationPlan,
    MemoryReconciliationResult,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationActionType,
    MemoryReconciliationFailureCode,
    MemoryReconciliationStatus,
    MemoryRelationType,
)
from app.memory.domain.repositories.contexts.memory_canonical_mutation_gateway import (
    IMemoryCanonicalMutationGateway,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_use_case_repositories import (
    IMemoryReconciliationApplyRepository,
)
from app.shared.exceptions.memory_context_exceptions import (
    MemoryContextNotFoundError,
    MemoryContextValidationError,
)
from app.shared.types.types_convert_utils import now_utc


class MemoryReconciliationApplyService:
    """Coordinate canonical mutations and audited reconciliation state writes."""

    def __init__(
        self,
        repository: IMemoryReconciliationApplyRepository,
        canonical_gateway: IMemoryCanonicalMutationGateway,
    ) -> None:
        """Initialize MemoryReconciliationApplyService state and dependencies.

        Args:
            repository: Repository used by this operation.
            canonical_gateway: Canonical gateway used by this operation.
        """
        self._repository = repository
        self._canonical_gateway = canonical_gateway
        self._state_writer = MemoryReconciliationStateWriter(repository)

    async def apply(
        self,
        plan_id: str,
        retry_failed: bool = False,
        review_approved: bool = False,
        reviewer: str | None = None,
    ) -> MemoryReconciliationResult:
        """Apply one plan once, or retry an explicitly failed/partial execution.

        Args:
            plan_id: Plan id.
            retry_failed: Retry failed.
            review_approved: Explicit approval for a review-required plan.
            reviewer: Memory Steward identity recorded with approved mutations.

        Returns:
            MemoryReconciliationResult: Operation result.
        """
        started = perf_counter()
        plan = await self._repository.get_plan(plan_id)
        if plan is None:
            raise MemoryContextNotFoundError(
                f"Memory reconciliation plan not found: {plan_id}"
            )
        existing = await self._repository.get_result_by_plan_id(plan_id)
        if existing is not None and (
            existing.status is MemoryReconciliationStatus.APPLIED or not retry_failed
        ):
            log_reconciliation_apply(
                plan,
                existing,
                duration_ms=(perf_counter() - started) * 1000,
                reused=True,
            )
            return existing
        reviewed_by = _validated_reviewer(
            plan,
            review_approved=review_approved,
            reviewer=reviewer,
        )
        try:
            result = await self._apply_plan(plan, reviewed_by=reviewed_by)
        except Exception as error:
            log_reconciliation_apply_exception(
                plan,
                duration_ms=(perf_counter() - started) * 1000,
                error_type=type(error).__name__,
            )
            raise
        log_reconciliation_apply(
            plan,
            result,
            duration_ms=(perf_counter() - started) * 1000,
            reused=False,
        )
        return result

    async def _apply_plan(
        self,
        plan: MemoryReconciliationPlan,
        reviewed_by: str | None,
    ) -> MemoryReconciliationResult:
        """Apply plan.

        Args:
            plan: Plan used by this operation.
            reviewed_by: Approved Memory Steward identity, when review was required.

        Returns:
            MemoryReconciliationResult result produced by apply plan.
        """
        created_context_ids: list[str] = []
        updated_context_ids: list[str] = []
        superseded_context_ids: list[str] = []
        created_relation_ids: list[str] = []
        created_conflict_set_ids: list[str] = []
        review_queue_item_ids: list[str] = []
        warnings = list(plan.warnings)
        reviewed_at = now_utc() if reviewed_by is not None else None
        canonical_changed = False
        failure_code = MemoryReconciliationFailureCode.POLICY_BLOCKED
        try:
            primary = primary_decision(plan)
            plan_conflict_ids = conflict_ids(plan, primary)
            created_context_id: str | None = None
            if has_action(plan, MemoryReconciliationActionType.CREATE_CONTEXT):
                failure_code = MemoryReconciliationFailureCode.CONTEXT_WRITE_FAILED
                created_context_id = await self._canonical_gateway.create_context(
                    plan.candidate,
                    lifecycle_status=candidate_lifecycle(plan),
                    supersedes_context_id=(
                        primary.existing_context_id
                        if primary is not None
                        and primary.relation is MemoryRelationType.SUPERSEDES
                        else None
                    ),
                    conflict_set_ids=plan_conflict_ids,
                    relation=None if primary is None else primary.relation,
                    related_context_id=(
                        None if primary is None else primary.existing_context_id
                    ),
                )
                created_context_ids.append(created_context_id)
                canonical_changed = True
                failure_code = (
                    MemoryReconciliationFailureCode.READ_BACK_VERIFICATION_FAILED
                )
                if not await self._canonical_gateway.verify(created_context_id):
                    raise RuntimeError("Created Context failed canonical read-back")
            if has_action(plan, MemoryReconciliationActionType.MERGE_EVIDENCE):
                target_context_id = required_target(primary)
                failure_code = MemoryReconciliationFailureCode.CONTEXT_WRITE_FAILED
                updated = await self._canonical_gateway.merge_evidence(
                    target_context_id,
                    plan.candidate.source_refs,
                )
                updated_context_ids.append(updated)
                canonical_changed = True
                failure_code = (
                    MemoryReconciliationFailureCode.READ_BACK_VERIFICATION_FAILED
                )
                if not await self._canonical_gateway.verify(updated):
                    raise RuntimeError("Evidence merge failed canonical read-back")
            if has_action(plan, MemoryReconciliationActionType.CREATE_RELATION):
                failure_code = MemoryReconciliationFailureCode.GRAPH_WRITE_FAILED
                relation = await self._state_writer.persist_primary_relation(
                    plan,
                    primary=primary,
                    created_context_id=created_context_id,
                )
                created_relation_ids.append(relation.relation_id)
            if has_action(plan, MemoryReconciliationActionType.CREATE_CONFLICT_SET):
                failure_code = MemoryReconciliationFailureCode.CONFLICT_WRITE_FAILED
                conflict = await self._state_writer.persist_conflict(
                    plan,
                    primary=primary,
                    created_context_id=created_context_id,
                    conflict_set_id=plan_conflict_ids[0],
                )
                created_conflict_set_ids.append(conflict.conflict_set_id)
            if has_action(plan, MemoryReconciliationActionType.MARK_SUPERSEDED):
                target_context_id = required_target(primary)
                if created_context_id is None:
                    raise RuntimeError("Supersede apply requires a replacement Context")
                failure_code = MemoryReconciliationFailureCode.LIFECYCLE_UPDATE_FAILED
                await self._canonical_gateway.supersede(
                    target_context_id,
                    created_context_id,
                )
                superseded_context_ids.append(target_context_id)
                canonical_changed = True
            failure_code = MemoryReconciliationFailureCode.LIFECYCLE_UPDATE_FAILED
            await self._state_writer.persist_temporal_states(
                plan,
                primary=primary,
                created_context_id=created_context_id,
                conflict_set_ids=plan_conflict_ids,
            )
            if has_action(plan, MemoryReconciliationActionType.QUEUE_REVIEW):
                review_queue_item_ids.append(review_item_id(plan.plan_id))
            result = _successful_result(
                plan,
                created_context_ids=created_context_ids,
                updated_context_ids=updated_context_ids,
                superseded_context_ids=superseded_context_ids,
                created_relation_ids=created_relation_ids,
                created_conflict_set_ids=created_conflict_set_ids,
                review_queue_item_ids=review_queue_item_ids,
                warnings=warnings,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
            )
        except Exception as exc:
            status = (
                MemoryReconciliationStatus.PARTIAL_APPLY
                if canonical_changed or created_relation_ids or created_conflict_set_ids
                else MemoryReconciliationStatus.FAILED
            )
            warnings.append(f"{failure_code.value}: {exc}")
            result = MemoryReconciliationResult(
                reconciliation_id=result_id(plan.plan_id),
                plan_id=plan.plan_id,
                status=status,
                created_context_ids=tuple(created_context_ids),
                updated_context_ids=tuple(dict.fromkeys(updated_context_ids)),
                superseded_context_ids=tuple(superseded_context_ids),
                created_relation_ids=tuple(created_relation_ids),
                created_conflict_set_ids=tuple(created_conflict_set_ids),
                review_queue_item_ids=tuple(review_queue_item_ids),
                warnings=tuple(warnings),
                hard_delete_performed=False,
                failure_code=(
                    MemoryReconciliationFailureCode.PARTIAL_APPLY
                    if status is MemoryReconciliationStatus.PARTIAL_APPLY
                    else failure_code
                ),
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                completed_at=now_utc(),
            )
        return await self._repository.save_result(result)


def _validated_reviewer(
    plan: MemoryReconciliationPlan,
    review_approved: bool,
    reviewer: str | None,
) -> str | None:
    """Return audited reviewer identity or block unsafe review-required mutation.

    Args:
        plan: Persisted reconciliation proposal.
        review_approved: Whether the caller explicitly approved review-required mutation.
        reviewer: Memory Steward identity attached to the approval.

    Returns:
        Normalized reviewer for review-required plans, otherwise None.

    Raises:
        MemoryContextValidationError: If required approval or reviewer identity is absent.
    """
    if not plan.requires_review:
        return None
    if not review_approved:
        raise MemoryContextValidationError(
            "RECONCILIATION_REVIEW_APPROVAL_REQUIRED: explicit Memory Steward "
            "approval is required before canonical mutation"
        )
    normalized = "" if reviewer is None else reviewer.strip()
    if not normalized or len(normalized) > 255:
        raise MemoryContextValidationError(
            "RECONCILIATION_REVIEWER_REQUIRED: approved review requires a bounded "
            "Memory Steward identity"
        )
    return normalized


def _successful_result(
    plan: MemoryReconciliationPlan,
    created_context_ids: list[str],
    updated_context_ids: list[str],
    superseded_context_ids: list[str],
    created_relation_ids: list[str],
    created_conflict_set_ids: list[str],
    review_queue_item_ids: list[str],
    warnings: list[str],
    reviewed_by: str | None,
    reviewed_at: datetime | None,
) -> MemoryReconciliationResult:
    """Execute successful result.

    Args:
        plan: Plan used by this operation.
        created_context_ids: Identifiers for created context.
        updated_context_ids: Identifiers for updated context.
        superseded_context_ids: Identifiers for superseded context.
        created_relation_ids: Identifiers for created relation.
        created_conflict_set_ids: Identifiers for created conflict set.
        review_queue_item_ids: Identifiers for review queue item.
        warnings: Warnings used by this operation.
        reviewed_by: Approved Memory Steward identity.
        reviewed_at: Timestamp when explicit review approval was consumed.

    Returns:
        MemoryReconciliationResult result produced by successful result.
    """
    return MemoryReconciliationResult(
        reconciliation_id=result_id(plan.plan_id),
        plan_id=plan.plan_id,
        status=MemoryReconciliationStatus.APPLIED,
        created_context_ids=tuple(created_context_ids),
        updated_context_ids=tuple(dict.fromkeys(updated_context_ids)),
        superseded_context_ids=tuple(superseded_context_ids),
        created_relation_ids=tuple(created_relation_ids),
        created_conflict_set_ids=tuple(created_conflict_set_ids),
        merged_evidence=(
            plan.candidate.source_refs
            if has_action(plan, MemoryReconciliationActionType.MERGE_EVIDENCE)
            else ()
        ),
        review_queue_item_ids=tuple(review_queue_item_ids),
        warnings=tuple(warnings),
        hard_delete_performed=False,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        completed_at=now_utc(),
    )
