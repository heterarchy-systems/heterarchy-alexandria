"""Single lease-owning coordinator for memory-cycle apply mutations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.reconciliation.cycles import (
    memory_cycle_checkpoints,
    memory_cycle_outcomes,
)
from app.memory.application.reconciliation.cycles.memory_cycle_compact_publication import (
    MemoryCycleCompactPublication,
)
from app.memory.application.reconciliation.cycles.memory_cycle_hashing import (
    compact_payload_for_sources,
)
from app.memory.application.reconciliation.cycles.memory_cycle_preview import (
    MemoryCyclePreviewPlanner,
)
from app.memory.application.reconciliation.cycles.memory_cycle_readback import (
    MemoryCycleReadback,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    MemoryCycleSourceFence,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_apply_service import (
    MemoryReconciliationApplyService,
)
from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleChildOutcome,
    MemoryCyclePhase,
    MemoryCycleResult,
)
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleCheckpointState,
    MemoryCycleOperation,
    MemoryCyclePhaseStatus,
    MemoryCycleStatus,
)
from app.memory.domain.event_enum.reconciliation_enums import (
    MemoryReconciliationStatus,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_use_case_repositories import (
    IMemoryReconciliationApplyRepository,
)
from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.memory_cycle_exceptions import (
    MemoryCycleRecoveryRequiredError,
    MemoryCycleStalePlanError,
    MemoryCycleValidationError,
)


class MemoryCycleApplyCoordinator:
    """Own the one exclusive lease and all aggregate apply phases."""

    def __init__(
        self,
        preview_planner: MemoryCyclePreviewPlanner,
        checkpoint_adapter: memory_cycle_checkpoints.MemoryCycleCheckpointAdapter,
        readback: MemoryCycleReadback,
        compact_publication: MemoryCycleCompactPublication,
        source_fence: MemoryCycleSourceFence,
        reconciliation_repository: IMemoryReconciliationApplyRepository,
        reconciliation_apply_service: MemoryReconciliationApplyService,
        compact_service: MemoryCompactService,
        coordinator: IndexMaintenanceCoordinator,
        commit_projection: Callable[[], Awaitable[None]],
        rollback_projection: Callable[[], Awaitable[None]],
    ) -> None:
        """Retain the existing apply and persistence authorities.

        Args:
            preview_planner: Write-free memory-cycle preview planner.
            checkpoint_adapter: Durable checkpoint persistence adapter.
            readback: Authoritative post-apply readback verifier.
            compact_publication: Post-apply compact verification and publication helper.
            source_fence: Canonical source revision fence reader.
            reconciliation_repository: Reconciliation plan persistence port.
            reconciliation_apply_service: Reconciliation plan execution service.
            compact_service: Memory Compact lifecycle service.
            coordinator: Exclusive index maintenance lease coordinator.
            commit_projection: Async callback committing the database transaction.
            rollback_projection: Async callback rolling back the database transaction.
        """
        self._preview_planner = preview_planner
        self._checkpoint_adapter = checkpoint_adapter
        self._readback = readback
        self._compact_publication = compact_publication
        self._source_fence = source_fence
        self._reconciliation_repository = reconciliation_repository
        self._reconciliation_apply = reconciliation_apply_service
        self._compact_service = compact_service
        self._coordinator = coordinator
        self._commit_projection = commit_projection
        self._rollback_projection = rollback_projection

    async def apply(self, request: MemoryCycleRequest) -> MemoryCycleResult:
        """Run the complete apply under the existing exclusive cycle lease.

        Args:
            request: Validated memory cycle apply request.

        Returns:
            Completed, partial, or replayed memory cycle result.
        """
        async with self._coordinator.operation("memory_cycle", wait=True):
            return await self._apply(request)

    async def _apply(self, request: MemoryCycleRequest) -> MemoryCycleResult:
        """Admit, execute, and checkpoint one exact cycle under the exclusive lease.

        Args:
            request: Validated memory cycle apply request.

        Returns:
            Completed, partial, or replayed memory cycle result.

        Raises:
            MemoryCycleValidationError: If expected_plan_hash is missing.
            MemoryCycleStalePlanError: If the plan hash differs from checkpoint or preview.
            MemoryCycleRecoveryRequiredError: If durable readback fails.
        """
        expected = request.expected_plan_hash
        if expected is None:
            raise MemoryCycleValidationError(
                "MEMORY_CYCLE_PLAN_HASH_REQUIRED: apply requires expected_plan_hash"
            )
        checkpoint = await self._checkpoint_adapter.load(request.idempotency_key)
        if checkpoint is not None:
            if checkpoint.plan_hash != expected:
                raise MemoryCycleStalePlanError(
                    "MEMORY_CYCLE_IDEMPOTENCY_CONFLICT: checkpoint plan hash differs"
                )
            failure = await self._readback.verify_checkpoint(
                checkpoint=checkpoint,
                request=request,
            )
            if failure is None:
                return replace(checkpoint.result, replayed=True)
            raise MemoryCycleRecoveryRequiredError(
                "MEMORY_CYCLE_RECOVERY_REQUIRED: durable checkpoint readback did not "
                "match canonical source, child results, or Compact: " + failure
            )

        preview = await self._preview_planner.preview(request)
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
        await self._checkpoint_adapter.save(
            memory_cycle_checkpoints.checkpoint_for(
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
        checkpoint_sources = preview.result.source_snapshot
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
                    child_outcomes.append(
                        memory_cycle_outcomes.review_child_outcome(persisted)
                    )
                    checkpoint_sources = await self._source_fence.refresh(
                        preview.result.source_snapshot,
                        extra_context_ids=tuple(
                            cid
                            for outcome in child_outcomes
                            for cid in outcome.affected_context_ids
                        ),
                    )
                    await self._checkpoint_adapter.save(
                        memory_cycle_checkpoints.checkpoint_for_result(
                            result=replace(
                                admitted,
                                child_outcomes=tuple(child_outcomes),
                                source_snapshot=checkpoint_sources,
                                warnings=tuple(dict.fromkeys(warnings)),
                            ),
                            state=MemoryCycleCheckpointState.ADMITTED,
                        )
                    )
                    continue
                result = await self._reconciliation_apply.apply(persisted.plan_id)
                await self._commit_projection()
                affected = (
                    *result.created_context_ids,
                    *result.updated_context_ids,
                    *result.superseded_context_ids,
                )
                child_outcomes.append(
                    MemoryCycleChildOutcome(
                        child_plan_key=persisted.idempotency_key,
                        plan_id=persisted.plan_id,
                        result_id=result.reconciliation_id,
                        relation=persisted.primary_decision,
                        status=result.status.value,
                        requires_review=persisted.requires_review,
                        warnings=result.warnings,
                        affected_context_ids=tuple(dict.fromkeys(affected)),
                    )
                )
                checkpoint_sources = await self._source_fence.refresh(
                    preview.result.source_snapshot,
                    extra_context_ids=tuple(
                        cid
                        for outcome in child_outcomes
                        for cid in outcome.affected_context_ids
                    ),
                )
                await self._checkpoint_adapter.save(
                    memory_cycle_checkpoints.checkpoint_for_result(
                        result=replace(
                            admitted,
                            child_outcomes=tuple(child_outcomes),
                            source_snapshot=checkpoint_sources,
                            warnings=tuple(dict.fromkeys(warnings)),
                        ),
                        state=MemoryCycleCheckpointState.ADMITTED,
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
                            detail=f"child plan {persisted.plan_id} returned {result.status.value}",
                            warnings=result.warnings,
                        )
                    )
                    partial = replace(
                        admitted,
                        status=MemoryCycleStatus.PARTIAL,
                        child_outcomes=tuple(child_outcomes),
                        source_snapshot=checkpoint_sources,
                        phases=tuple(phases),
                        warnings=tuple(dict.fromkeys(warnings)),
                        elapsed_ms=0.0,
                    )
                    await self._checkpoint_adapter.save(
                        memory_cycle_checkpoints.checkpoint_for_result(
                            result=partial,
                            state=MemoryCycleCheckpointState.PARTIAL,
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
                    source_snapshot=checkpoint_sources,
                    phases=tuple(phases),
                    warnings=tuple(dict.fromkeys(warnings)),
                    elapsed_ms=0.0,
                )
                await self._checkpoint_adapter.save(
                    memory_cycle_checkpoints.checkpoint_for_result(
                        result=partial,
                        state=MemoryCycleCheckpointState.PARTIAL,
                    )
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
                cid
                for outcome in child_outcomes
                for cid in outcome.affected_context_ids
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
            await self._checkpoint_adapter.save(
                memory_cycle_checkpoints.checkpoint_for_result(
                    result=partial,
                    state=MemoryCycleCheckpointState.PARTIAL,
                )
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
            (
                compact_change,
                compact_phase,
            ) = await self._compact_publication.verify_and_publish(
                compact=compact,
                compact_change=compact_change,
                sources=post_apply_sources,
                project=request.project,
            )
            phases.append(compact_phase)
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
                source_snapshot=post_apply_sources,
                compact_change=compact_change,
                phases=tuple(phases),
                warnings=tuple(dict.fromkeys(warnings)),
                elapsed_ms=0.0,
            )
            await self._checkpoint_adapter.save(
                memory_cycle_checkpoints.checkpoint_for_result(
                    result=partial,
                    state=MemoryCycleCheckpointState.PARTIAL,
                )
            )
            return partial

        retrieval_phase = await self._readback.verify_retrieval(
            preview=preview,
            request=request,
        )
        phases.append(retrieval_phase)
        retrieval_failed = (
            retrieval_phase.status is not MemoryCyclePhaseStatus.SUCCEEDED
        )
        if retrieval_failed:
            warnings.extend(retrieval_phase.warnings)

        review_required = any(item.requires_review for item in child_outcomes) or (
            not compact_change.safe_to_publish
        )
        final, final_checkpoint_state = memory_cycle_outcomes.final_result(
            admitted=admitted,
            child_outcomes=tuple(child_outcomes),
            source_snapshot=post_apply_sources,
            compact_change=compact_change,
            phases=tuple(phases),
            warnings=tuple(dict.fromkeys(warnings)),
            retrieval_failed=retrieval_failed,
            review_required=review_required,
        )
        await self._checkpoint_adapter.save(
            memory_cycle_checkpoints.checkpoint_for_result(
                result=final,
                state=final_checkpoint_state,
            )
        )
        return final
