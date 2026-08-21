"""Obsidian vault search source for Context RAG retrieval."""

from __future__ import annotations

from app.memory.domain.contracts.context_contracts import ContextChunkEmbeddingUpdate
from app.memory.domain.contracts.context_recall_contracts import (
    ContextFtsRecall,
    ContextVectorRecall,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
    ContextSearchMatch,
)
from app.memory.domain.event_enum.context_enums import RagHealthState
from app.memory.domain.repositories.contexts.context_search_source import (
    IContextSearchSource,
)
from app.memory.infrastructure.repositories.contexts.embeddings.obsidian_context_embedding_store import (
    ObsidianContextEmbeddingStore,
)
from app.memory.infrastructure.repositories.contexts.obsidian.obsidian_context_query_store import (
    ObsidianContextQueryStore,
)
from app.shared.types.extra_types import JSONObject
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyObsidianContextSearchSource(IContextSearchSource):
    """Expose indexed Obsidian notes through the Context search source port."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize focused stores sharing one transaction-scoped session.

        Args:
            session: Active async database session.
        """
        self._query_store = ObsidianContextQueryStore(session)
        self._embedding_store = ObsidianContextEmbeddingStore(session)

    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        """Search indexed Obsidian note chunks through the active lexical backend.

        Args:
            recall: Validated FTS query and recall filters.

        Returns:
            Obsidian-backed Context matches.
        """
        return await self._query_store.search_fts(recall)

    async def search_vector(
        self, recall: ContextVectorRecall
    ) -> list[ContextSearchMatch]:
        """Search indexed Obsidian note chunks through the active vector backend.

        Args:
            recall: Validated vector query and recall filters.

        Returns:
            Obsidian-backed semantic matches.
        """
        return await self._query_store.search_vector(recall)

    async def chunks_missing_embeddings(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        limit: int,
        force: bool = False,
    ) -> list[ContextChunkRecord]:
        """Return Obsidian chunks requiring embedding work.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding fingerprint key.
            limit: Maximum chunks to scan.
            force: Whether current rows should also be rebuilt.

        Returns:
            Obsidian Context chunks selected for embedding.
        """
        return await self._embedding_store.chunks_missing_embeddings(
            model_name=model_name,
            dimensions=dimensions,
            fingerprint_key=fingerprint_key,
            limit=limit,
            force=force,
        )

    async def embedding_index_status(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
    ) -> RagHealthState:
        """Return whether Obsidian embeddings match the active fingerprint.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding fingerprint key.

        Returns:
            Embedding index health state.
        """
        return await self._embedding_store.embedding_index_status(
            model_name=model_name,
            dimensions=dimensions,
            fingerprint_key=fingerprint_key,
        )

    async def embedding_source_status(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        current_fingerprint: JSONObject,
    ) -> ContextEmbeddingSourceStatus:
        """Return source-level Obsidian embedding diagnostics.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding fingerprint key.
            current_fingerprint: Active timestamp-free fingerprint payload.

        Returns:
            Obsidian embedding source diagnostics.
        """
        return await self._embedding_store.embedding_source_status(
            model_name=model_name,
            dimensions=dimensions,
            fingerprint_key=fingerprint_key,
            current_fingerprint=current_fingerprint,
        )

    async def update_chunk_embeddings(
        self,
        updates: list[ContextChunkEmbeddingUpdate],
    ) -> int:
        """Persist embedding updates for indexed Obsidian chunks.

        Args:
            updates: Embedding updates keyed by prefixed chunk id.

        Returns:
            Number of Obsidian chunks updated.
        """
        return await self._embedding_store.update_chunk_embeddings(updates)
