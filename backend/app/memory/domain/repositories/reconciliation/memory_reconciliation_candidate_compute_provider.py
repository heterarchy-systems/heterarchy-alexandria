"""Compute port for bulk memory reconciliation candidate discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.contracts.memory_reconciliation_candidate_compute_contracts import (
    ReconciliationCandidateComputeItem,
    ReconciliationCandidateComputePolicy,
    ReconciliationCandidateComputeResult,
)


class IMemoryReconciliationCandidateComputeProvider(ABC):
    """Discover candidate evidence without owning final relation policy."""

    @abstractmethod
    def discover(
        self,
        items: tuple[ReconciliationCandidateComputeItem, ...],
        policy: ReconciliationCandidateComputePolicy,
    ) -> ReconciliationCandidateComputeResult:
        """Return bounded candidate evidence for Python-owned policy.

        Args:
            items: Typed items selected by the Python application boundary.
            policy: Explicit comparison thresholds and cardinality limits.

        Returns:
            Deterministic candidate evidence, clusters, and metrics.
        """
