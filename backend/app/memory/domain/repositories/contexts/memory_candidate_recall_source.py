"""Recall source port used specifically by memory reconciliation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.entities.context_read_models import ContextPack
from app.memory.domain.entities.memory_reconciliation import MemoryCandidate


class IMemoryCandidateRecallSource(ABC):
    """Retrieve existing Context candidates without exposing search implementation."""

    @abstractmethod
    async def recall(
        self,
        candidate: MemoryCandidate,
        query: str,
        limit: int,
    ) -> ContextPack:
        """Return Context matches relevant to one reconciliation candidate.

        Args:
            candidate: Candidate.
            query: Query.
            limit: Limit.

        Returns:
            ContextPack: Operation result.
        """
