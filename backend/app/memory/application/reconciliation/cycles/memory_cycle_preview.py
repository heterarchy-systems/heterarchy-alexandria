"""Write-free planning for bounded aggregate memory cycles."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter

from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.application.reconciliation.cycles.memory_cycle_hashing import (
    semantic_plan_hash,
)
from app.memory.application.reconciliation.cycles.memory_cycle_outcomes import (
    preview_child_outcome,
)
from app.memory.application.reconciliation.cycles.memory_cycle_planning import (
    build_cycle_facts,
    compact_blockers,
    compact_snapshot,
    render_compact_body,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    MemoryCycleSourceFence,
)
from app.memory.application.reconciliation.runtime.memory_existing_reconciliation_service import (
    MemoryExistingReconciliationService,
)
from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.contracts.memory_existing_reconciliation_contracts import (
    ExistingMemoryReconciliationRequest,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleCompactChange,
    MemoryCyclePhase,
    MemoryCycleResult,
)
from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationPlan
from app.memory.domain.event_enum.context_enums import ContextScope
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleOperation,
    MemoryCyclePhaseStatus,
    MemoryCycleStatus,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactNotFoundError
from app.shared.exceptions.memory_cycle_exceptions import MemoryCycleValidationError
from app.shared.types.types_convert_utils import aware_utc_datetime

_CYCLE_RECALL_LIMIT = 20


@dataclass(frozen=True, slots=True, kw_only=True)
class CyclePreview:
    """Read-only aggregate plan and the exact child plans it represents."""

    result: MemoryCycleResult
    plans: tuple[MemoryReconciliationPlan, ...]
    compact_payload: MemoryCompactCreate
    retrieval_queries: tuple[tuple[str, str], ...]


class MemoryCyclePreviewPlanner:
    """Build a dry-run plan by reusing existing-memory and Compact owners."""

    def __init__(
        self,
        existing_reconciliation_service: MemoryExistingReconciliationService,
        source_fence: MemoryCycleSourceFence,
        compact_service: MemoryCompactService,
        compact_policy: MemoryCompactReconciliationPolicy,
    ) -> None:
        """Retain the existing read and policy authorities used by planning.

        Args:
            existing_reconciliation_service: Service for existing memory plan previews.
            source_fence: Canonical source revision fence.
            compact_service: Memory Compact query and creation service.
            compact_policy: Policy evaluator for compact publication readiness.
        """
        self._existing_reconciliation = existing_reconciliation_service
        self._source_fence = source_fence
        self._compact_service = compact_service
        self._compact_policy = compact_policy

    async def preview(self, request: MemoryCycleRequest) -> CyclePreview:
        """Build a deterministic plan without SQL, Markdown, or checkpoint writes.

        Args:
            request: Validated memory cycle request.

        Returns:
            Read-only CyclePreview containing aggregate result and child plans.
        """
        started = perf_counter()
        scan_request = ExistingMemoryReconciliationRequest(
            project=request.project,
            scope=request.scope,
            workspace_id=request.workspace_id,
            include_archived=True,
            max_contexts=request.max_contexts,
            batch_size=request.max_contexts,
            recall_limit=_CYCLE_RECALL_LIMIT,
            created_after=aware_utc_datetime(request.window_start),
            created_before=aware_utc_datetime(request.window_end),
        )
        report = await self._existing_reconciliation.preview_plans(scan_request)
        current = await self._current_compact(request.project)
        current_snapshot = compact_snapshot(current)
        facts = build_cycle_facts(report.previews)
        policy_review = self._compact_policy.review(facts.fact_buckets)
        unsafe_reasons = list(compact_blockers(facts.buckets, policy_review))
        if report.scanned == 0 or not report.previews:
            unsafe_reasons.append(
                "no eligible Context sources in requested cycle window"
            )
        if request.workspace_id is not None:
            unsafe_reasons.append(
                "workspace-filtered cycle cannot promote the project CURRENT Compact"
            )
        unsafe_reason_tuple = tuple(dict.fromkeys(unsafe_reasons))
        body = render_compact_body(
            project=request.project,
            window_start=request.window_start,
            window_end=request.window_end,
            facts=facts.fact_buckets,
            blockers=unsafe_reason_tuple,
        )
        compact_payload = MemoryCompactCreate(
            project=request.project,
            covered_from=aware_utc_datetime(request.window_start),
            covered_to=aware_utc_datetime(request.window_end),
            markdown_body=body,
            status=MemoryCompactStatus.DRAFT,
            source_refs=facts.source_refs,
        )
        compact_change = MemoryCycleCompactChange(
            status=(
                MemoryCompactStatus.DRAFT
                if unsafe_reasons
                else MemoryCompactStatus.CURRENT
            ),
            compact_id=None,
            content_hash=hash_text(body),
            source_set_hash=facts.source_set_hash,
            review_verdict=None,
            safe_to_publish=not unsafe_reasons,
            warnings=unsafe_reason_tuple,
        )
        plans = tuple(item.plan for item in report.previews if item.plan is not None)
        source_snapshot = await self._source_fence.snapshot(report.previews)
        plan_hash = semantic_plan_hash(
            request=request,
            source_snapshot=source_snapshot,
            current_compact=current_snapshot,
            plans=plans,
            compact_change=compact_change,
        )
        review_items = tuple(
            item for item in facts.buckets.review_required if item.requires_review
        )
        warnings = [*report.warnings, *policy_review.warnings]
        warnings.append("query_count_not_instrumented")
        if unsafe_reasons:
            warnings.extend(unsafe_reasons)
        phases = (
            MemoryCyclePhase(
                name="scan",
                status=MemoryCyclePhaseStatus.SUCCEEDED,
                detail=f"scanned={report.scanned}; total_available={report.total_available}",
            ),
            MemoryCyclePhase(
                name="plan",
                status=(
                    MemoryCyclePhaseStatus.REVIEW_REQUIRED
                    if review_items or unsafe_reasons
                    else MemoryCyclePhaseStatus.SUCCEEDED
                ),
                detail=f"child_plans={len(plans)}",
                warnings=tuple(unsafe_reasons),
            ),
        )
        result = MemoryCycleResult(
            operation=request.operation,
            status=(
                MemoryCycleStatus.REVIEW_REQUIRED
                if review_items or unsafe_reasons
                else MemoryCycleStatus.PREVIEW
            ),
            idempotency_key=request.idempotency_key.strip(),
            plan_hash=plan_hash,
            project=request.project,
            workspace_id=request.workspace_id,
            scope=request.scope.value,
            window_start=aware_utc_datetime(request.window_start),
            window_end=aware_utc_datetime(request.window_end),
            replayed=False,
            scanned=report.scanned,
            total_available=report.total_available,
            candidate_count=len(report.previews),
            source_snapshot=source_snapshot,
            current_compact=current_snapshot,
            buckets=replace(
                facts.buckets,
                compact_changes=(compact_change,),
            ),
            child_outcomes=tuple(preview_child_outcome(plan) for plan in plans),
            compact_change=compact_change,
            phases=phases,
            warnings=tuple(dict.fromkeys(warnings)),
            elapsed_ms=(perf_counter() - started) * 1000,
            query_count=None,
        )
        return CyclePreview(
            result=result,
            plans=plans,
            compact_payload=compact_payload,
            retrieval_queries=tuple(
                (item.context.id, item.context.title) for item in report.previews[:1]
            ),
        )

    async def _current_compact(self, project: str | None) -> MemoryCompact | None:
        """Return current Compact when one exists for the requested project.

        Args:
            project: Project scope to look up.

        Returns:
            Current MemoryCompact if present, otherwise None.
        """
        try:
            return await self._compact_service.current(project=project)
        except MemoryCompactNotFoundError:
            return None


def validate_request(request: MemoryCycleRequest) -> None:
    """Validate cycle bounds, timezone semantics, and apply fencing.

    Args:
        request: Memory cycle request to validate.

    Raises:
        MemoryCycleValidationError: If any request field violates cycle invariants.
    """
    if request.operation not in {
        MemoryCycleOperation.DRY_RUN,
        MemoryCycleOperation.APPLY,
    }:
        raise MemoryCycleValidationError("MEMORY_CYCLE_OPERATION_INVALID")
    if request.window_start.tzinfo is None or request.window_end.tzinfo is None:
        raise MemoryCycleValidationError("MEMORY_CYCLE_WINDOW_REQUIRES_AWARE_DATETIME")
    if request.window_end < request.window_start:
        raise MemoryCycleValidationError("MEMORY_CYCLE_WINDOW_INVALID")
    if request.max_contexts < 1 or request.max_contexts > 100:
        raise MemoryCycleValidationError(
            "MEMORY_CYCLE_MAX_CONTEXTS_MUST_BE_BETWEEN_1_AND_100"
        )
    if not request.idempotency_key.strip() or len(request.idempotency_key) > 512:
        raise MemoryCycleValidationError("MEMORY_CYCLE_IDEMPOTENCY_KEY_REQUIRED")
    if not request.project.strip():
        raise MemoryCycleValidationError("MEMORY_CYCLE_PROJECT_INVALID")
    if request.scope is not ContextScope.PROJECT:
        raise MemoryCycleValidationError(
            "MEMORY_CYCLE_SCOPE_MUST_BE_PROJECT: high-level cycles cannot promote "
            "non-project memory into the project CURRENT Compact"
        )
    if request.workspace_id is not None and not request.workspace_id.strip():
        raise MemoryCycleValidationError("MEMORY_CYCLE_WORKSPACE_INVALID")
    if request.operation is MemoryCycleOperation.APPLY:
        if request.expected_plan_hash is None:
            raise MemoryCycleValidationError(
                "MEMORY_CYCLE_PLAN_HASH_REQUIRED: apply requires expected_plan_hash"
            )
        if len(request.expected_plan_hash) != 64 or any(
            character not in "0123456789abcdef"
            for character in request.expected_plan_hash
        ):
            raise MemoryCycleValidationError("MEMORY_CYCLE_PLAN_HASH_INVALID")
