"""Prepare reconciliation-aware fact buckets for safe Memory Compact generation."""

from __future__ import annotations

from typing import Protocol

from app.memory.application.reconciliation.compacts.memory_compact_reconciliation_policy import (
    MemoryCompactReconciliationPolicy,
)
from app.memory.domain.contracts.memory_reconciliation_contracts import (
    MemoryTemporalRecallRequest,
)
from app.memory.domain.entities.memory_reconciliation import (
    MemoryCompactSafetyReview,
    MemoryTemporalRecallPack,
)
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode


class TemporalRecallForCompaction(Protocol):
    """Minimal temporal recall surface required by Compact preparation."""

    async def recall(
        self,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryTemporalRecallPack:
        """Return one reconciliation-aware temporal recall pack.

        Args:
            request: Request.

        Returns:
            MemoryTemporalRecallPack: Operation result.
        """


class MemoryCompactReconciliationService:
    """Recall all relevant temporal states and prepare safe Compact input."""

    def __init__(
        self,
        temporal_recall_service: TemporalRecallForCompaction,
        policy: MemoryCompactReconciliationPolicy,
    ) -> None:
        self._temporal_recall_service = temporal_recall_service
        self._policy = policy

    async def prepare(
        self,
        request: MemoryTemporalRecallRequest,
    ) -> MemoryCompactSafetyReview:
        """Return structured fact buckets and safety issues without publishing.

        Args:
            request: Request.

        Returns:
            MemoryCompactSafetyReview: Operation result.
        """
        recall_request = MemoryTemporalRecallRequest(
            query=request.query,
            mode=MemoryTemporalRecallMode.ALL,
            as_of=request.as_of,
            strategy=request.strategy,
            limit=request.limit,
            project=request.project,
            kind=request.kind,
            include_scopes=request.include_scopes,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            user_id=request.user_id,
            session_id=request.session_id,
            include_lifecycle_statuses=request.include_lifecycle_statuses,
        )
        pack = await self._temporal_recall_service.recall(recall_request)
        return self._policy.prepare(pack)
