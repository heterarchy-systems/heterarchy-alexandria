"""Port for AUTO-only graph candidate expansion after primary Context recall."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.memory.domain.contracts.context_recall_contracts import ContextRecallFilter
from app.memory.domain.entities.context_read_models import ContextSearchMatch


@dataclass(slots=True, kw_only=True)
class ContextGraphCandidateExpansionResult:
    """Bounded graph-aware matches plus non-fatal expansion warnings."""

    matches: tuple[ContextSearchMatch, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    discovered_candidate_count: int = 0
    selected_candidate_count: int = 0
    hydrated_candidate_count: int = 0
    filtered_candidate_count: int = 0
    appended_candidate_count: int = 0

    def __post_init__(self) -> None:
        """Normalize result collections to immutable tuples."""
        self.matches = tuple(self.matches)
        self.warnings = tuple(self.warnings)


class IContextGraphCandidateExpansionProvider(ABC):
    """Expand and rerank AUTO graph-intent results without changing fixed strategies."""

    @abstractmethod
    async def expand(
        self,
        query: str,
        matches: list[ContextSearchMatch],
        recall_filter: ContextRecallFilter,
        limit: int,
        graph_depth: int,
    ) -> ContextGraphCandidateExpansionResult:
        """Return one bounded graph-aware final match set.

        Args:
            query: Original retrieval query.
            matches: Primary retrieval results in their existing rank order.
            recall_filter: Existing visibility and scope boundary.
            limit: Public final result bound.
            graph_depth: Planner-authoritative traversal depth for this request.

        Returns:
            Graph-aware matches and bounded degradation warnings.
        """
