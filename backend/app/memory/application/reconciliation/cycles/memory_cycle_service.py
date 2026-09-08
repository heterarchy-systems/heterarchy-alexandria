"""Bounded aggregate orchestration for Memory reconciliation and Compacts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import partial
from time import perf_counter
from typing import Final, Protocol

import anyio
from pydantic import TypeAdapter

from app.memory.application.contexts.records.context_service_ports import (
    ContextTemporalSearchPort,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.application.reconciliation.cycles.memory_cycle_planning import (
    build_cycle_facts,
    compact_blockers,
    compact_payload_for_sources,
    compact_snapshot,
    compact_source_hashes_match,
    render_compact_body,
    semantic_plan_hash,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    MemoryCycleSourceFence,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_apply_service import (
    MemoryReconciliationApplyService,
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
    MemoryCycleCheckpoint,
    MemoryCycleChildOutcome,
    MemoryCycleCompactChange,
    MemoryCyclePhase,
    MemoryCycleResult,
)
from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationPlan
from app.memory.domain.event_enum.context_enums import ContextScope, RagStrategy
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleCheckpointState,
    MemoryCycleOperation,
    MemoryCyclePhaseStatus,
    MemoryCycleStatus,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationStatus,
)
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_use_case_repositories import (
    IMemoryReconciliationApplyRepository,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactNotFoundError
from app.shared.exceptions.memory_cycle_exceptions import (
    MemoryCycleRecoveryRequiredError,
    MemoryCycleStalePlanError,
    MemoryCycleValidationError,
)
from app.shared.types.types_convert_utils import aware_utc_datetime


class MemoryCycleCheckpointStore(Protocol):
    """Typed blocking checkpoint surface owned by the report-bundle run store."""

    def load_typed(
        self,
        idempotency_key: str,
        adapter: TypeAdapter[MemoryCycleCheckpoint],
    ) -> MemoryCycleCheckpoint | None:
        """Load one typed cycle checkpoint."""

    def save_typed(
        self,
        idempotency_key: str,
        record: MemoryCycleCheckpoint,
        adapter: TypeAdapter[MemoryCycleCheckpoint],
    ) -> None:
        """Atomically save one typed cycle checkpoint."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _CyclePreview:
    """Read-only aggregate plan and the exact child plans it represents."""

    result: MemoryCycleResult
    plans: tuple[MemoryReconciliationPlan, ...]
    compact_payload: MemoryCompactCreate
    retrieval_queries: tuple[tuple[str, str], ...]


_CHECKPOINT_ADAPTER: Final[TypeAdapter[MemoryCycleCheckpoint]] = TypeAdapter(
    MemoryCycleCheckpoint
)
_CHECKPOINT_PREFIX: Final[str] = "memory-cycle:"
_CYCLE_RECALL_LIMIT: Final[int] = 20


class MemoryCycleService:
    """Coordinate existing reconciliation and Compact authorities under one fence."""

    def __init__(
        self,
        existing_reconciliation_service: MemoryExistingReconciliationService,
        context_service: ContextTemporalSearchPort,
        source_fence: MemoryCycleSourceFence,
        reconciliation_repository: IMemoryReconciliationApplyRepository,
        reconciliation_apply_service: MemoryReconciliationApplyService,
        compact_service: MemoryCompactService,
        compact_policy: MemoryCompactReconciliationPolicy,
        index_maintenance_coordinator: IndexMaintenanceCoordinator,
        checkpoint_store: MemoryCycleCheckpointStore,
        commit_projection: Callable[[], Awaitable[None]],
        rollback_projection: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize one request-scoped aggregate memory-cycle facade."""
        self._existing_reconciliation = existing_reconciliation_service
        self._context_service = context_service
        self._source_fence = source_fence
        self._reconciliation_repository = reconciliation_repository
        self._reconciliation_apply = reconciliation_apply_service
        self._compact_service = compact_service
        self._compact_policy = compact_policy
        self._coordinator = index_maintenance_coordinator
        self._checkpoint_store = checkpoint_store
        self._commit_projection = commit_projection
        self._rollback_projection = rollback_projection

    async def execute(self, request: MemoryCycleRequest) -> MemoryCycleResult:
        """Run one write-free preview or fenced aggregate apply."""
        _validate_request(request)
        if request.operation is MemoryCycleOperation.DRY_RUN:
            return (await self._preview(request)).result
        async with self._coordinator.operation("memory_cycle", wait=True):
            return await self._apply(request)

    async def _preview(self, request: MemoryCycleRequest) -> _CyclePreview:
        """Build a deterministic plan without SQL, Markdown, or checkpoint writes."""
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
        if request.workspace_id is not None:
            unsafe_reasons.append(
                "workspace-filtered cycle cannot promote the project CURRENT Compact"
            )
        unsafe_reason_tuple = tuple(dict.fromkeys(unsafe_reasons))
        if unsafe_reasons:
            body = render_compact_body(
                project=request.project,
                window_start=request.window_start,
                window_end=request.window_end,
                facts=facts.fact_buckets,
                blockers=unsafe_reason_tuple,
            )
        else:
            body = render_compact_body(
                project=request.project,
                window_start=request.window_start,
                window_end=request.window_end,
                facts=facts.fact_buckets,
                blockers=(),
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
            child_outcomes=tuple(_preview_child_outcome(plan) for plan in plans),
            compact_change=compact_change,
            phases=phases,
            warnings=tuple(dict.fromkeys(warnings)),
            elapsed_ms=(perf_counter() - started) * 1000,
            query_count=None,
        )
        return _CyclePreview(
            result=result,
            plans=plans,
            compact_payload=compact_payload,
            retrieval_queries=tuple(
                (item.context.id, item.context.title) for item in report.previews[:1]
            ),
        )

    async def _apply(self, request: MemoryCycleRequest) -> MemoryCycleResult:
        """Admit, execute, and checkpoint one exact cycle under the exclusive lease."""
        expected = request.expected_plan_hash
        if expected is None:
            raise MemoryCycleValidationError(
                "MEMORY_CYCLE_PLAN_HASH_REQUIRED: apply requires expected_plan_hash"
            )
        checkpoint = await self._load_checkpoint(request.idempotency_key)
        if checkpoint is not None:
            if checkpoint.plan_hash != expected:
                raise MemoryCycleStalePlanError(
                    "MEMORY_CYCLE_IDEMPOTENCY_CONFLICT: checkpoint plan hash differs"
                )
            if await self._verify_checkpoint(checkpoint, request):
                return replace(checkpoint.result, replayed=True)
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_RECOVERY_REQUIRED: durable checkpoint readback did not "
                "match canonical source, child results, or Compact"
            )

        preview = await self._preview(request)
        if preview.result.plan_hash != expected:
            raise MemoryCycleStalePlanError(
                "MEMORY_CYCLE_STALE_PLAN: source or current Compact changed since "
                "dry-run; create a new plan"
            )
        admitted = replace(
            preview.result,
            operation=MemoryCycleOperation.APPLY,
            status=MemoryCycleStatus.ADMITTED,
        )
        await self._save_checkpoint(
            _checkpoint_for(
                result=admitted,
                state=MemoryCycleCheckpointState.ADMITTED,
                child_plan_ids=(),
                child_result_ids=(),
                compact_id=None,
            )
        )

        child_outcomes: list[MemoryCycleChildOutcome] = []
        phases = list(admitted.phases)
        warnings = list(admitted.warnings)
        for plan in preview.plans:
            try:
                persisted = (
                    await self._reconciliation_repository.get_plan_by_idempotency_key(
                        plan.idempotency_key
                    )
                )
                if persisted is None:
                    persisted = await self._reconciliation_repository.save_plan(plan)
                if persisted.requires_review:
                    await self._commit_projection()
                    child_outcomes.append(_review_child_outcome(persisted))
                    await self._save_checkpoint(
                        _checkpoint_for_result(
                            replace(
                                admitted,
                                child_outcomes=tuple(child_outcomes),
                                warnings=tuple(dict.fromkeys(warnings)),
                            ),
                            MemoryCycleCheckpointState.ADMITTED,
                        )
                    )
                    continue
                result = await self._reconciliation_apply.apply(persisted.plan_id)
                await self._commit_projection()
                child_outcomes.append(
                    MemoryCycleChildOutcome(
                        child_plan_key=persisted.idempotency_key,
                        plan_id=persisted.plan_id,
                        result_id=result.reconciliation_id,
                        relation=persisted.primary_decision,
                        status=result.status.value,
                        requires_review=persisted.requires_review,
                        warnings=result.warnings,
                        affected_context_ids=tuple(
                            dict.fromkeys(
                                (
                                    *result.created_context_ids,
                                    *result.updated_context_ids,
                                    *result.superseded_context_ids,
                                )
                            )
                        ),
                    )
                )
                await self._save_checkpoint(
                    _checkpoint_for_result(
                        replace(
                            admitted,
                            child_outcomes=tuple(child_outcomes),
                            warnings=tuple(dict.fromkeys(warnings)),
                        ),
                        MemoryCycleCheckpointState.ADMITTED,
                    )
                )
                if result.status is not MemoryReconciliationStatus.APPLIED:
                    warnings.append(
                        f"child_plan_failed:{persisted.idempotency_key}:{result.status.value}"
                    )
                    phases.append(
                        MemoryCyclePhase(
                            name="children",
                            status=MemoryCyclePhaseStatus.PARTIAL,
                            detail=(
                                f"child plan {persisted.plan_id} returned "
                                f"{result.status.value}"
                            ),
                            warnings=result.warnings,
                        )
                    )
                    partial = replace(
                        admitted,
                        status=MemoryCycleStatus.PARTIAL,
                        child_outcomes=tuple(child_outcomes),
                        phases=tuple(phases),
                        warnings=tuple(dict.fromkeys(warnings)),
                        elapsed_ms=0.0,
                    )
                    await self._save_checkpoint(
                        _checkpoint_for_result(
                            partial, MemoryCycleCheckpointState.PARTIAL
                        )
                    )
                    return partial
            except Exception as exc:
                await self._rollback_projection()
                warnings.append(f"child_phase_failed:{type(exc).__name__}:{exc}")
                phases.append(
                    MemoryCyclePhase(
                        name="children",
                        status=MemoryCyclePhaseStatus.PARTIAL,
                        detail="Child execution stopped after an observable failure.",
                        warnings=(str(exc),),
                    )
                )
                partial = replace(
                    admitted,
                    status=MemoryCycleStatus.PARTIAL,
                    child_outcomes=tuple(child_outcomes),
                    phases=tuple(phases),
                    warnings=tuple(dict.fromkeys(warnings)),
                    elapsed_ms=0.0,
                )
                await self._save_checkpoint(
                    _checkpoint_for_result(partial, MemoryCycleCheckpointState.PARTIAL)
                )
                return partial

        phases.append(
            MemoryCyclePhase(
                name="children",
                status=(
                    MemoryCyclePhaseStatus.REVIEW_REQUIRED
                    if any(item.requires_review for item in child_outcomes)
                    else MemoryCyclePhaseStatus.SUCCEEDED
                ),
                detail=f"admitted_children={len(child_outcomes)}",
            )
        )
        compact_change = preview.result.compact_change
        if compact_change is None:
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_RECOVERY_REQUIRED: compact change missing from admitted plan"
            )
        affected_context_ids = tuple(
            dict.fromkeys(
                context_id
                for outcome in child_outcomes
                for context_id in outcome.affected_context_ids
            )
        )
        try:
            post_apply_sources = await self._source_fence.refresh(
                preview.result.source_snapshot,
                extra_context_ids=affected_context_ids,
            )
        except MemoryCycleRecoveryRequiredError as exc:
            warnings.append(str(exc))
            phases.append(
                MemoryCyclePhase(
                    name="source_readback",
                    status=MemoryCyclePhaseStatus.PARTIAL,
                    detail="Post-child canonical source revision could not be fenced.",
                    warnings=(str(exc),),
                )
            )
            partial = replace(
                admitted,
                status=MemoryCycleStatus.PARTIAL,
                child_outcomes=tuple(child_outcomes),
                phases=tuple(phases),
                warnings=tuple(dict.fromkeys(warnings)),
                elapsed_ms=0.0,
            )
            await self._save_checkpoint(
                _checkpoint_for_result(partial, MemoryCycleCheckpointState.PARTIAL)
            )
            return partial
        compact_payload = compact_payload_for_sources(
            preview.compact_payload,
            post_apply_sources,
        )
        try:
            compact = await self._compact_service.create(compact_payload)
            compact_change = replace(
                compact_change,
                compact_id=compact.id,
                content_hash=hash_text(compact.markdown_body),
                source_set_hash=compact.source_set_hash,
                status=compact.status,
            )
            if compact_change.safe_to_publish:
                if not compact_source_hashes_match(
                    compact,
                    post_apply_sources,
                ):
                    raise RuntimeError(
                        "Memory Compact source hash readback verification failed"
                    )
                current = await self._compact_service.mark_current(compact.id)
                current_compacts, _ = await self._compact_service.list_compacts(
                    project=request.project,
                    status=MemoryCompactStatus.CURRENT,
                    limit=100,
                    offset=0,
                )
                if len(current_compacts) != 1 or current_compacts[0].id != current.id:
                    raise RuntimeError(
                        "Memory Compact CURRENT cardinality/readback verification failed"
                    )
                compact_change = replace(
                    compact_change,
                    status=MemoryCompactStatus.CURRENT,
                    review_verdict=current.review_verdict,
                    content_hash=hash_text(current.markdown_body),
                )
                phases.append(
                    MemoryCyclePhase(
                        name="compact",
                        status=MemoryCyclePhaseStatus.SUCCEEDED,
                        detail=f"current_compact={current.id}",
                    )
                )
            else:
                phases.append(
                    MemoryCyclePhase(
                        name="compact",
                        status=MemoryCyclePhaseStatus.REVIEW_REQUIRED,
                        detail=f"draft_compact={compact.id}",
                        warnings=compact_change.warnings,
                    )
                )
        except Exception as exc:
            await self._rollback_projection()
            warnings.append(f"compact_phase_failed:{type(exc).__name__}:{exc}")
            phases.append(
                MemoryCyclePhase(
                    name="compact",
                    status=MemoryCyclePhaseStatus.PARTIAL,
                    detail="Compact publication did not complete.",
                    warnings=(str(exc),),
                )
            )
            partial = replace(
                admitted,
                status=MemoryCycleStatus.PARTIAL,
                child_outcomes=tuple(child_outcomes),
                compact_change=compact_change,
                phases=tuple(phases),
                warnings=tuple(dict.fromkeys(warnings)),
                elapsed_ms=0.0,
            )
            await self._save_checkpoint(
                _checkpoint_for_result(partial, MemoryCycleCheckpointState.PARTIAL)
            )
            return partial

        retrieval_phase = await self._verify_retrieval(preview, request)
        phases.append(retrieval_phase)
        retrieval_failed = (
            retrieval_phase.status is not MemoryCyclePhaseStatus.SUCCEEDED
        )
        if retrieval_failed:
            warnings.extend(retrieval_phase.warnings)

        review_required = any(item.requires_review for item in child_outcomes) or (
            not compact_change.safe_to_publish
        )
        final = replace(
            admitted,
            status=(
                MemoryCycleStatus.PARTIAL
                if retrieval_failed
                else (
                    MemoryCycleStatus.REVIEW_REQUIRED
                    if review_required
                    else MemoryCycleStatus.APPLIED
                )
            ),
            child_outcomes=tuple(child_outcomes),
            source_snapshot=post_apply_sources,
            compact_change=compact_change,
            buckets=replace(
                admitted.buckets,
                compact_changes=(compact_change,),
            ),
            phases=tuple(phases),
            warnings=tuple(dict.fromkeys(warnings)),
            elapsed_ms=0.0,
        )
        await self._save_checkpoint(
            _checkpoint_for_result(
                final,
                (
                    MemoryCycleCheckpointState.PARTIAL
                    if retrieval_failed
                    else (
                        MemoryCycleCheckpointState.REVIEW_REQUIRED
                        if review_required
                        else MemoryCycleCheckpointState.COMPLETED
                    )
                ),
            )
        )
        return final

    async def _verify_retrieval(
        self,
        preview: _CyclePreview,
        request: MemoryCycleRequest,
    ) -> MemoryCyclePhase:
        """Verify one bounded source retrieval after apply and commit phases."""
        if not preview.retrieval_queries:
            return MemoryCyclePhase(
                name="retrieval",
                status=MemoryCyclePhaseStatus.SKIPPED,
                detail="No source Context was selected for retrieval verification.",
            )
        context_id, query = preview.retrieval_queries[0]
        include_scopes = [] if request.scope is None else [request.scope]
        try:
            pack = await self._context_service.search(
                query=query,
                strategy=RagStrategy.HYBRID,
                limit=10,
                project=request.project,
                include_scopes=include_scopes,
                workspace_id=request.workspace_id,
            )
        except Exception as exc:
            return MemoryCyclePhase(
                name="retrieval",
                status=MemoryCyclePhaseStatus.PARTIAL,
                detail="Retrieval verification failed after mutation phases.",
                warnings=(f"retrieval_verification_failed:{type(exc).__name__}:{exc}",),
            )
        matched = any(match.context.id == context_id for match in pack.matches)
        if not matched:
            return MemoryCyclePhase(
                name="retrieval",
                status=MemoryCyclePhaseStatus.PARTIAL,
                detail="Canonical source was not returned by post-apply retrieval.",
                warnings=("retrieval_projection_pending_or_missing",),
            )
        return MemoryCyclePhase(
            name="retrieval",
            status=MemoryCyclePhaseStatus.SUCCEEDED,
            detail=f"verified_context={context_id}",
            warnings=pack.warnings,
        )

    async def _current_compact(self, project: str | None) -> MemoryCompact | None:
        """Return current Compact when one exists for the requested project."""
        try:
            return await self._compact_service.current(project=project)
        except MemoryCompactNotFoundError:
            return None

    async def _load_checkpoint(
        self,
        idempotency_key: str,
    ) -> MemoryCycleCheckpoint | None:
        """Read typed run-store state through the bounded blocking bridge."""
        return await anyio.to_thread.run_sync(
            partial(
                self._checkpoint_store.load_typed,
                _checkpoint_key(idempotency_key),
                _CHECKPOINT_ADAPTER,
            )
        )

    async def _save_checkpoint(self, checkpoint: MemoryCycleCheckpoint) -> None:
        """Persist one typed checkpoint atomically outside the canonical note root."""
        await anyio.to_thread.run_sync(
            partial(
                self._checkpoint_store.save_typed,
                _checkpoint_key(checkpoint.idempotency_key),
                checkpoint,
                _CHECKPOINT_ADAPTER,
            )
        )

    async def _verify_checkpoint(
        self,
        checkpoint: MemoryCycleCheckpoint,
        request: MemoryCycleRequest,
    ) -> bool:
        """Verify replay state before returning a durable prior result."""
        if checkpoint.state is MemoryCycleCheckpointState.ADMITTED:
            return False
        current_sources = await self._source_fence.refresh(checkpoint.source_snapshot)
        if current_sources != checkpoint.source_snapshot:
            return False
        for plan_id, result_id in zip(
            checkpoint.child_plan_ids,
            checkpoint.child_result_ids,
            strict=True,
        ):
            plan = await self._reconciliation_repository.get_plan(plan_id)
            if plan is None:
                return False
            if result_id is None:
                if not plan.requires_review:
                    return False
                continue
            result = await self._reconciliation_repository.get_result(result_id)
            if result is None or result.plan_id != plan_id:
                return False
        compact_id = checkpoint.compact_id
        compact_change = checkpoint.result.compact_change
        if compact_id is None:
            return False
        try:
            compact = await self._compact_service.get(compact_id)
        except MemoryCompactNotFoundError:
            return False
        if compact_change is None:
            return False
        if compact_change.content_hash != hash_text(compact.markdown_body):
            return False
        if (
            compact_change.status is MemoryCompactStatus.CURRENT
            and not compact_source_hashes_match(
                compact,
                checkpoint.source_snapshot,
            )
        ):
            return False
        if compact_change.status is MemoryCompactStatus.CURRENT:
            current_compacts, _ = await self._compact_service.list_compacts(
                project=request.project,
                status=MemoryCompactStatus.CURRENT,
                limit=100,
                offset=0,
            )
            if len(current_compacts) != 1 or current_compacts[0].id != compact.id:
                return False
        return True


def _validate_request(request: MemoryCycleRequest) -> None:
    """Validate cycle bounds, timezone semantics, and apply fencing."""
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


def _checkpoint_key(idempotency_key: str) -> str:
    """Namespace cycle checkpoints in the existing run-store authority."""
    return _CHECKPOINT_PREFIX + idempotency_key.strip()


def _preview_child_outcome(
    plan: MemoryReconciliationPlan,
) -> MemoryCycleChildOutcome:
    """Map one in-memory child plan into bounded output evidence."""
    return MemoryCycleChildOutcome(
        child_plan_key=plan.idempotency_key,
        plan_id=None,
        result_id=None,
        relation=plan.primary_decision,
        status=plan.status.value,
        requires_review=plan.requires_review,
        warnings=plan.warnings,
    )


def _review_child_outcome(
    plan: MemoryReconciliationPlan,
) -> MemoryCycleChildOutcome:
    """Map one persisted review-required child plan without auto-approval."""
    return MemoryCycleChildOutcome(
        child_plan_key=plan.idempotency_key,
        plan_id=plan.plan_id,
        result_id=None,
        relation=plan.primary_decision,
        status=MemoryCycleStatus.REVIEW_REQUIRED.value,
        requires_review=True,
        warnings=plan.warnings,
    )


def _checkpoint_for(
    result: MemoryCycleResult,
    state: MemoryCycleCheckpointState,
    child_plan_ids: tuple[str, ...],
    child_result_ids: tuple[str | None, ...],
    compact_id: str | None,
) -> MemoryCycleCheckpoint:
    """Build an admitted checkpoint with explicit durable child identity."""
    return MemoryCycleCheckpoint(
        idempotency_key=result.idempotency_key,
        plan_hash=result.plan_hash,
        state=state,
        result=result,
        source_snapshot=result.source_snapshot,
        compact_id=compact_id,
        child_plan_ids=child_plan_ids,
        child_result_ids=child_result_ids,
    )


def _checkpoint_for_result(
    result: MemoryCycleResult,
    state: MemoryCycleCheckpointState,
) -> MemoryCycleCheckpoint:
    """Build a completed/partial checkpoint from aggregate output evidence."""
    child_plan_ids = tuple(
        item.plan_id for item in result.child_outcomes if item.plan_id is not None
    )
    child_result_ids = tuple(
        item.result_id for item in result.child_outcomes if item.plan_id is not None
    )
    compact_id = (
        None if result.compact_change is None else result.compact_change.compact_id
    )
    return _checkpoint_for(
        result=result,
        state=state,
        child_plan_ids=child_plan_ids,
        child_result_ids=child_result_ids,
        compact_id=compact_id,
    )
