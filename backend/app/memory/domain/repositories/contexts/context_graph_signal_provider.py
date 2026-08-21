"""Port for optional graph evidence applied after primary Context recall."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.memory.domain.entities.context_read_models import ContextSearchMatch


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextGraphEnrichmentResult:
    """Score-preserving Context matches plus graph-lane diagnostics."""

    matches: tuple[ContextSearchMatch, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize result collections to immutable tuples."""
        object.__setattr__(self, "matches", tuple(self.matches))
        object.__setattr__(self, "warnings", tuple(self.warnings))


class IContextGraphSignalProvider(ABC):
    """Read optional graph evidence without changing primary recall ranking."""

    @abstractmethod
    async def enrich(
        self,
        matches: list[ContextSearchMatch],
    ) -> ContextGraphEnrichmentResult:
        """Attach graph evidence to already-ranked Context matches.

        Args:
            matches: Primary FTS/vector results in their final order.

        Returns:
            Enriched matches in the same order with unchanged scores.
        """
