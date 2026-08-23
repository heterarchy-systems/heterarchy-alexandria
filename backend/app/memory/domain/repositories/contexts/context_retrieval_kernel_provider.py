"""Deterministic compute port for Context retrieval ranking."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.context_read_models import ContextSearchMatch


class IContextRetrievalKernelProvider(ABC):
    """Own deterministic candidate sizing, lane fusion, and best-match ranking."""

    @property
    @abstractmethod
    def authority(self) -> str:
        """Return the runtime compute authority identifier.

        Returns:
            Stable runtime authority identifier used for provenance checks.
        """

    @abstractmethod
    def hybrid_candidate_limit(self, limit: int) -> int:
        """Return the bounded candidate count gathered per Hybrid lane.

        Args:
            limit: Requested final result count.

        Returns:
            Bounded over-fetch count used before Hybrid fusion.
        """

    @abstractmethod
    def merge(
        self,
        fts_matches: list[ContextSearchMatch],
        vector_matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        """Return hybrid-ranked Context matches.

        Args:
            fts_matches: Already-filtered FTS lane in source rank order.
            vector_matches: Already-filtered vector lane in source rank order.
            limit: Maximum final result count.

        Returns:
            Hybrid-ranked Context matches mapped to the existing read model.
        """

    @abstractmethod
    def rank_best(
        self,
        matches: list[ContextSearchMatch],
        limit: int,
    ) -> list[ContextSearchMatch]:
        """Keep the best chunk per Context and return stable score ranking.

        Args:
            matches: Candidate matches from one or more retrieval sources.
            limit: Maximum returned Context count.

        Returns:
            Highest-scoring match per Context in deterministic order.
        """
