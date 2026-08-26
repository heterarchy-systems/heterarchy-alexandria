"""Compute port for bounded traversal over an active Obsidian graph projection."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjection,
    ObsidianGraphTraversalRequest,
    ObsidianGraphTraversalResult,
)


class IObsidianGraphTraversalComputeProvider(ABC):
    """Execute pure deterministic traversal without owning graph persistence effects."""

    @property
    @abstractmethod
    def authority(self) -> str:
        """Return the deterministic traversal compute authority identifier.

        Returns:
            Stable compute authority identifier.
        """

    @abstractmethod
    def traverse(
        self,
        projection: ObsidianGraphProjection,
        requests: tuple[ObsidianGraphTraversalRequest, ...],
    ) -> tuple[ObsidianGraphTraversalResult, ...]:
        """Traverse one already-active projection in one coarse compute call.

        Args:
            projection: Immutable active graph projection loaded by Python.
            requests: Bounded traversal requests over seed note identities.

        Returns:
            Traversal results in request order.
        """
