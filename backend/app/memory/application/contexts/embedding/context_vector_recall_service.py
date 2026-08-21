"""Vector recall orchestration across configured Context search sources."""

from __future__ import annotations

from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.application.retrieval.ranking.context_ranking import (
    rank_best_matches_per_context,
)
from app.memory.domain.contracts.context_recall_contracts import (
    ContextRecallFilter,
    ContextVectorRecall,
)
from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from asyncer import asyncify


class ContextVectorRecallService:
    """Create one query embedding and rank matches across Context sources."""

    def __init__(
        self,
        provider: EmbeddingProvider | None,
        search_sources: list[IContextSearchSource],
    ) -> None:
        """Initialize vector recall dependencies.

        Args:
            provider: Optional embedding provider.
            search_sources: Configured Context retrieval sources.
        """
        self._provider = provider
        self._search_sources = search_sources

    async def search(
        self,
        query: str,
        recall_filter: ContextRecallFilter,
    ) -> list[ContextSearchMatch]:
        """Search configured sources with one query embedding.

        Args:
            query: Search query text.
            recall_filter: Validated recall and scope filters.

        Returns:
            Ranked vector matches across configured sources.
        """
        provider = self._provider
        if provider is None:
            return []
        fingerprint = provider.fingerprint()
        query_embedding = await _embed_query(provider, query)
        if len(query_embedding) != provider.dimensions:
            raise MemoryContextValidationError(
                "Embedding provider returned an unexpected dimension"
            )
        recall = ContextVectorRecall(
            query_embedding=tuple(query_embedding),
            model_name=provider.model_name,
            dimensions=provider.dimensions,
            fingerprint_key=fingerprint.key(),
            recall_filter=recall_filter,
        )
        matches: list[ContextSearchMatch] = []
        for source in self._search_sources:
            matches.extend(await source.search_vector(recall))
        return rank_best_matches_per_context(matches, recall_filter.limit)


async def _embed_query(provider: EmbeddingProvider, text: str) -> list[float]:
    return await asyncify(provider.embed_query, abandon_on_cancel=True)(text)
