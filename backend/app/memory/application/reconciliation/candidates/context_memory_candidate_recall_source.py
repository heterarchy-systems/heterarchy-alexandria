"""Context RAG adapter for reconciliation-specific candidate recall."""

from __future__ import annotations

from app.memory.application.contexts.records.context_service import ContextService
from app.memory.domain.entities.context_read_models import ContextPack
from app.memory.domain.entities.memory_reconciliation import MemoryCandidate
from app.memory.domain.event_enum.context_enums import RagStrategy
from app.memory.domain.repositories.contexts.memory_candidate_recall_source import (
    IMemoryCandidateRecallSource,
)


class ContextMemoryCandidateRecallSource(IMemoryCandidateRecallSource):
    """Adapt the existing Context search service to reconciliation recall."""

    def __init__(self, search_service: ContextService) -> None:
        """Initialize ContextMemoryCandidateRecallSource state and dependencies.

        Args:
            search_service: Search service dependency.
        """
        self._search_service = search_service

    async def recall(
        self,
        candidate: MemoryCandidate,
        query: str,
        limit: int,
    ) -> ContextPack:
        """Search only the candidate's explicit scope identity.

        Args:
            candidate: Candidate.
            query: Query.
            limit: Limit.

        Returns:
            ContextPack: Operation result.
        """
        return await self._search_service.search(
            query=query,
            strategy=RagStrategy.HYBRID,
            limit=limit,
            project=candidate.project,
            include_scopes=[candidate.scope],
            workspace_id=candidate.workspace_id,
            agent_id=candidate.agent_id,
            user_id=candidate.user_id,
            session_id=candidate.session_id,
        )
