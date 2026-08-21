"""Search-source port for Context RAG retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.memory.domain.contracts.context_contracts import (
    ContextChunkEmbeddingUpdate,
)
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
from app.shared.types.extra_types import JSONObject


class IContextSearchSource(ABC):
    """Persistence-backed source that can contribute Context RAG matches."""

    @abstractmethod
    async def search_fts(self, recall: ContextFtsRecall) -> list[ContextSearchMatch]:
        """Search source chunks with the active lexical-search backend.

        Args:
            recall: Validated FTS query and recall filters.

        Returns:
            Ranked source matches mapped into Context RAG read models.
        """

    @abstractmethod
    async def search_vector(
        self, recall: ContextVectorRecall
    ) -> list[ContextSearchMatch]:
        """Search source chunks with stored embeddings.

        Args:
            recall: Validated vector query and recall filters.

        Returns:
            Ranked source matches mapped into Context RAG read models.
        """

    @abstractmethod
    async def chunks_missing_embeddings(
        self,
        # type-contract: allow-keyword-only -- fingerprint fields form a public protocol contract.
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        limit: int,
        force: bool = False,
    ) -> list[ContextChunkRecord]:
        """Return source chunks that need embedding backfill or rebuild.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.
            limit: Maximum chunks to scan.
            force: Whether to rebuild existing embeddings even if metadata matches.

        Returns:
            Chunks missing current embedding metadata or selected for rebuild.
        """

    @abstractmethod
    async def embedding_index_status(
        self,
        # type-contract: allow-keyword-only -- fingerprint fields form a public protocol contract.
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
    ) -> RagHealthState:
        """Return whether the source embedding index matches the current provider.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.

        Returns:
            HEALTHY when indexed embeddings match; REINDEX_REQUIRED otherwise.
        """

    @abstractmethod
    async def embedding_source_status(
        self,
        # type-contract: allow-keyword-only -- fingerprint fields form a public protocol contract.
        *,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        current_fingerprint: JSONObject,
    ) -> ContextEmbeddingSourceStatus:
        """Return row counts and stored fingerprints for this source.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.
            current_fingerprint: Current timestamp-free fingerprint payload.

        Returns:
            Source-level embedding fingerprint diagnostics.
        """

    @abstractmethod
    async def update_chunk_embeddings(
        self,
        updates: list[ContextChunkEmbeddingUpdate],
    ) -> int:
        """Persist source chunk embedding updates.

        Args:
            updates: Embedding updates keyed by source-specific chunk identifier.

        Returns:
            Number of chunks updated.
        """
