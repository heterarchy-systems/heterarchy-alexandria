"""Hydration port for graph-discovered Context candidates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.memory.domain.contracts.context_recall_contracts import ContextRecallFilter
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextRecord,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextGraphHydratedCandidate:
    """Canonical Context and representative persisted chunk for one graph candidate."""

    note_id: str
    context: ContextRecord
    chunk: ContextChunkRecord


class IContextGraphCandidateHydrator(ABC):
    """Hydrate graph note identities without owning graph selection or ranking."""

    @abstractmethod
    async def hydrate(
        self,
        note_ids: tuple[str, ...],
        recall_filter: ContextRecallFilter,
    ) -> tuple[ContextGraphHydratedCandidate, ...]:
        """Hydrate eligible graph candidates in caller order.

        Args:
            note_ids: Bounded selected Obsidian note identities.
            recall_filter: Existing Context recall visibility and scope boundary.

        Returns:
            Available eligible Context/chunk pairs restored in caller order.
        """
