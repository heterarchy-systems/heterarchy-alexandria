"""Compute port for deterministic Obsidian graph projection planning."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.obsidian.domain.contracts.obsidian_graph_projection_contracts import (
    ObsidianGraphProjectionSourceSnapshot,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianEdge, ObsidianNote


class IObsidianGraphProjectionComputeProvider(ABC):
    """Compute one projection snapshot from already-loaded typed source rows."""

    @abstractmethod
    def compute(
        self,
        notes: tuple[ObsidianNote, ...],
        edges: tuple[ObsidianEdge, ...],
        batch_size: int,
    ) -> ObsidianGraphProjectionSourceSnapshot:
        """Return a deterministic source snapshot without persistence effects.

        Args:
            notes: Typed note rows loaded by the Python repository boundary.
            edges: Typed edge rows loaded by the Python repository boundary.
            batch_size: Maximum nodes and edges per projection write batch.

        Returns:
            Existing projection source snapshot DTO.
        """
