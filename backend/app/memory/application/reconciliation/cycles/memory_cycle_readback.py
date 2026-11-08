"""Canonical checkpoint replay and post-apply retrieval readback."""

from __future__ import annotations

from app.memory.application.contexts.records.context_service_ports import (
    ContextTemporalSearchPort,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.reconciliation.cycles.memory_cycle_hashing import (
    compact_source_hashes_match,
)
from app.memory.application.reconciliation.cycles.memory_cycle_preview import (
    CyclePreview,
)
from app.memory.application.reconciliation.cycles.memory_cycle_source_fence import (
    MemoryCycleSourceFence,
)
from app.memory.domain.contracts.memory_cycle_contracts import MemoryCycleRequest
from app.memory.domain.entities.memory_cycle import (
    MemoryCycleCheckpoint,
    MemoryCyclePhase,
)
from app.memory.domain.event_enum.context_enums import RagStrategy
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.event_enum.memory_cycle_enums import (
    MemoryCycleCheckpointState,
    MemoryCyclePhaseStatus,
)
from app.memory.domain.repositories.reconciliation.memory_reconciliation_use_case_repositories import (
    IMemoryReconciliationApplyRepository,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.memory_compact_exceptions import MemoryCompactNotFoundError


class MemoryCycleReadback:
    """Verify durable cycle evidence through its existing canonical owners."""

    def __init__(
        self,
        context_service: ContextTemporalSearchPort,
        source_fence: MemoryCycleSourceFence,
        reconciliation_repository: IMemoryReconciliationApplyRepository,
        compact_service: MemoryCompactService,
    ) -> None:
        """Retain the source, retrieval, and Compact read authorities.

        Args:
            context_service: Temporal context search service.
            source_fence: Canonical source revision fence.
            reconciliation_repository: Reconciliation plan/result repository.
            compact_service: Memory Compact service.
        """
        self._context_service = context_service
        self._source_fence = source_fence
        self._reconciliation_repository = reconciliation_repository
        self._compact_service = compact_service

    async def verify_retrieval(
        self,
        preview: CyclePreview,
        request: MemoryCycleRequest,
    ) -> MemoryCyclePhase:
        """Verify one bounded source retrieval after apply and commit phases.

        Args:
            preview: Dry-run cycle preview containing retrieval probe queries.
            request: Memory cycle execution request.

        Returns:
            Retrieval verification phase outcome.
        """
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

    async def verify_checkpoint(
        self,
        checkpoint: MemoryCycleCheckpoint,
        request: MemoryCycleRequest,
    ) -> str | None:
        """Return a specific failing replay fence, or None after complete readback.

        Args:
            checkpoint: Persisted cycle checkpoint under replay verification.
            request: Incoming memory cycle apply request.

        Returns:
            Failure reason code if any replay fence fails, otherwise None.
        """
        if checkpoint.state is MemoryCycleCheckpointState.ADMITTED:
            return "admission_not_completed"
        current_sources = await self._source_fence.refresh(checkpoint.source_snapshot)
        if current_sources != checkpoint.source_snapshot:
            return "source_revision_drift"
        for plan_id, result_id in zip(
            checkpoint.child_plan_ids,
            checkpoint.child_result_ids,
            strict=True,
        ):
            plan = await self._reconciliation_repository.get_plan(plan_id)
            if plan is None:
                return "child_plan_missing"
            if result_id is None:
                if not plan.requires_review:
                    return "child_result_unresolved"
                continue
            result = await self._reconciliation_repository.get_result(result_id)
            if result is None or result.plan_id != plan_id:
                return "child_result_identity_mismatch"
        compact_id = checkpoint.compact_id
        compact_change = checkpoint.result.compact_change
        if compact_id is None:
            return "compact_not_recorded"
        try:
            compact = await self._compact_service.get(compact_id)
        except MemoryCompactNotFoundError:
            return "compact_source_missing"
        if compact_change is None:
            return "compact_change_missing"
        if compact_change.content_hash != hash_text(compact.markdown_body):
            return "compact_body_hash_drift"
        if (
            compact_change.status is MemoryCompactStatus.CURRENT
            and not compact_source_hashes_match(
                compact,
                checkpoint.source_snapshot,
            )
        ):
            return "compact_source_ref_hash_drift"
        if compact_change.status is MemoryCompactStatus.CURRENT:
            current_compacts, _ = await self._compact_service.list_compacts(
                project=request.project,
                status=MemoryCompactStatus.CURRENT,
                limit=100,
                offset=0,
            )
            if len(current_compacts) != 1 or current_compacts[0].id != compact.id:
                return "current_compact_identity_drift"
        return None
