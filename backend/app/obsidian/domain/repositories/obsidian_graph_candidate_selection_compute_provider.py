"""Compute port for relevance-bounded graph candidate selection."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphCandidateSelectionResult,
    ObsidianGraphProjection,
    ObsidianGraphTraversalRequest,
)


class IObsidianGraphCandidateSelectionComputeProvider(ABC):
    """Select bounded graph candidates without owning graph persistence effects."""

    @property
    @abstractmethod
    def authority(self) -> str:
        """Return the deterministic candidate-selection authority identifier.

        Returns:
            Stable compute authority identifier.
        """

    @abstractmethod
    def select_candidates(
        self,
        projection: ObsidianGraphProjection,
        requests: tuple[ObsidianGraphTraversalRequest, ...],
        primary_note_ids: tuple[str, ...],
        query: str,
        max_candidates: int,
        min_shared_trigrams: int,
    ) -> ObsidianGraphCandidateSelectionResult:
        """Traverse and select a small query-relevant graph candidate set.

        Args:
            projection: Immutable active graph projection loaded by Python.
            requests: Bounded traversal requests over ranked seed identities.
            primary_note_ids: Existing ranked primary note identities needing title evidence.
            query: Original retrieval query used for deterministic title relevance.
            max_candidates: Maximum selected graph candidates returned to policy code.
            min_shared_trigrams: Minimum shared normalized title/query trigrams.

        Returns:
            Traversal trace plus bounded selected candidate identities.
        """
