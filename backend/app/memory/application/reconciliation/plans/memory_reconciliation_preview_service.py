"""Preview memory reconciliation without mutating canonical Context state."""

from __future__ import annotations

from time import perf_counter

from app.memory.application.reconciliation.candidates.memory_candidate_recall_service import (
    MemoryCandidateRecallService,
)
from app.memory.application.reconciliation.candidates.memory_candidate_service import (
    MemoryCandidateService,
)
from app.memory.application.reconciliation.candidates.memory_relation_classifier import (
    MemoryRelationClassifier,
)
from app.memory.application.reconciliation.plans.memory_reconciliation_plan_service import (
    MemoryReconciliationPlanService,
)
from app.memory.application.reconciliation.runtime.memory_reconciliation_observability import (
    log_reconciliation_preview,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryReconciliationPreviewRequest,
)
from app.memory.domain.entities.memory_reconciliation import MemoryReconciliationPlan
from app.memory.domain.repositories.reconciliation.memory_reconciliation_plan_repository import (
    IMemoryReconciliationPlanRepository,
)


class MemoryReconciliationPreviewService:
    """Coordinate candidate normalization, recall, classification, and plan storage."""

    def __init__(
        self,
        candidate_service: MemoryCandidateService,
        recall_service: MemoryCandidateRecallService,
        classifier: MemoryRelationClassifier,
        plan_service: MemoryReconciliationPlanService,
        repository: IMemoryReconciliationPlanRepository,
    ) -> None:
        """Initialize MemoryReconciliationPreviewService state and dependencies.

        Args:
            candidate_service: Candidate service dependency.
            recall_service: Recall service dependency.
            classifier: Classifier used by this operation.
            plan_service: Plan service dependency.
            repository: Repository used by this operation.
        """
        self._candidate_service = candidate_service
        self._recall_service = recall_service
        self._classifier = classifier
        self._plan_service = plan_service
        self._repository = repository

    async def preview(
        self,
        request: MemoryReconciliationPreviewRequest,
    ) -> MemoryReconciliationPlan:
        """Return and persist one idempotent non-mutating reconciliation plan.

        Args:
            request: Request.

        Returns:
            MemoryReconciliationPlan: Operation result.
        """
        started = perf_counter()
        explicit_key = request.idempotency_key
        if explicit_key is not None and explicit_key.strip():
            existing = await self._repository.get_plan_by_idempotency_key(
                explicit_key.strip()
            )
            if existing is not None:
                log_reconciliation_preview(
                    existing,
                    duration_ms=(perf_counter() - started) * 1000,
                    reused=True,
                )
                return existing
        candidate = self._candidate_service.create(request.candidate)
        recalled = await self._recall_service.recall(
            candidate,
            limit=request.recall_limit,
        )
        decisions = tuple(
            [
                await self._classifier.classify_with_model(candidate, existing)
                for existing in recalled
            ]
        )
        plan = self._plan_service.build(
            candidate=candidate,
            decisions=decisions,
            idempotency_key=explicit_key,
        )
        persisted = await self._repository.save_plan(plan)
        log_reconciliation_preview(
            persisted,
            duration_ms=(perf_counter() - started) * 1000,
            reused=False,
        )
        return persisted
