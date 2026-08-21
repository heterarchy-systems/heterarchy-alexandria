"""Context embedding health, vector recall, and index lifecycle facade."""

from __future__ import annotations

from app.memory.application.contexts.embedding.context_embedding_health_service import (
    ContextEmbeddingHealthService,
)
from app.memory.application.contexts.embedding.context_embedding_reindex_service import (
    ContextEmbeddingBatchTransaction,
    ContextEmbeddingReindexService,
)
from app.memory.application.contexts.embedding.context_vector_recall_service import (
    ContextVectorRecallService,
)
from app.memory.application.retrieval.embeddings.embedding_contract import (
    EmbeddingProvider,
)
from app.memory.domain.contracts.context_recall_contracts import ContextRecallFilter
from app.memory.domain.entities.context_read_models import (
    ContextEmbeddingSourceStatus,
    ContextReindexResult,
    ContextSearchMatch,
    RagDependencyHealth,
)
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)


class ContextEmbeddingService:
    """Expose stable embedding APIs through focused health, rebuild, and recall services."""

    def __init__(
        self,
        provider: EmbeddingProvider | None,
        vector_retrieval_enabled: bool,
        search_sources: list[IContextSearchSource],
        batch_transaction: ContextEmbeddingBatchTransaction | None = None,
    ) -> None:
        """Create focused embedding collaborators.

        Args:
            provider: Optional local embedding provider.
            vector_retrieval_enabled: Whether vector retrieval is wired.
            search_sources: Configured Context retrieval and index sources.
            batch_transaction: Optional production transaction boundary per batch.
        """
        self._health_service = ContextEmbeddingHealthService(
            provider=provider,
            vector_retrieval_enabled=vector_retrieval_enabled,
            search_sources=search_sources,
        )
        self._reindex_service = ContextEmbeddingReindexService(
            provider=provider,
            search_sources=search_sources,
            health_service=self._health_service,
            batch_transaction=batch_transaction,
        )
        self._vector_recall_service = ContextVectorRecallService(
            provider=provider,
            search_sources=search_sources,
        )

    def health(self) -> RagDependencyHealth:
        """Return current embedding and vector dependency health.

        Returns:
            Health state for FTS, vector, and embedding dependencies.
        """
        return self._health_service.health()

    async def recall_health(self) -> RagDependencyHealth:
        """Return lightweight embedding health for one search request.

        Returns:
            Recall health without source-level diagnostic row counts.
        """
        return await self._health_service.recall_health()

    async def health_with_index_status(self) -> RagDependencyHealth:
        """Return dependency health including persisted fingerprint status.

        Returns:
            Health state that marks vector recall unavailable on mismatch.
        """
        return await self._health_service.health_with_index_status()

    async def reindex(
        self,
        limit: int = 100,
        force: bool = False,
    ) -> ContextReindexResult:
        """Backfill or rebuild embeddings for stored context chunks.

        Args:
            limit: Maximum chunks to reindex in this batch.
            force: Whether existing matching embeddings should be rebuilt.

        Returns:
            Context embedding reindex result.
        """
        return await self._reindex_service.reindex(limit=limit, force=force)

    async def source_statuses(self) -> list[ContextEmbeddingSourceStatus]:
        """Return source-level embedding fingerprint diagnostics.

        Returns:
            One status object per configured Context retrieval source.
        """
        return await self._health_service.source_statuses()

    async def search_vector(
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
        return await self._vector_recall_service.search(
            query=query,
            recall_filter=recall_filter,
        )
