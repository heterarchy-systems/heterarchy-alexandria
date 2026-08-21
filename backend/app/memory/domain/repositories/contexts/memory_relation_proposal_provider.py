"""External model proposal port for uncertain memory relations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.memory_reconciliation import (
    MemoryCandidate,
    MemoryRecallCandidate,
)
from app.memory.domain.entities.memory_relation_proposal import (
    MemoryRelationModelProposal,
)


class IMemoryRelationProposalProvider(ABC):
    """Propose a relation without receiving authority to mutate memory state."""

    @abstractmethod
    async def propose(
        self,
        candidate: MemoryCandidate,
        existing: MemoryRecallCandidate,
    ) -> MemoryRelationModelProposal | None:
        """Return one validated model proposal, or None when unavailable.

        Args:
            candidate: Candidate.
            existing: Existing.

        Returns:
            MemoryRelationModelProposal | None: Operation result.
        """
