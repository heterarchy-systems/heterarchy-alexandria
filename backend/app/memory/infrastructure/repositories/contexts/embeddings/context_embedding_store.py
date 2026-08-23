"""SQL-backed Context embedding metadata and update store."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.domain.contracts.context_contracts import ContextChunkEmbeddingUpdate
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
)
from app.memory.domain.event_enum.context_enums import RagHealthState
from app.memory.infrastructure.repositories.contexts.embeddings.embedding_reindex import (
    chunks_missing_embeddings,
    embedding_index_status,
    embedding_source_status,
    update_chunk_embeddings,
)
from app.shared.types.extra_types import JSONObject


class ContextEmbeddingStore:
    """Own embedding work queues, fingerprint status, and vector updates."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the Context embedding store.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def chunks_missing_embeddings(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        limit: int,
        force: bool,
    ) -> list[ContextChunkRecord]:
        """Return chunks needing embedding work.

        Args:
            model_name: Embedding model name.
            dimensions: Embedding vector dimensions.
            fingerprint_key: Current embedding pipeline fingerprint.
            limit: Maximum chunks to return.
            force: Whether matching embeddings may be rebuilt.

        Returns:
            Context chunks that require embedding work.
        """
        return await chunks_missing_embeddings(
            session=self._session,
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
        """Return embedding index compatibility for the current provider.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding vector dimensions.
            fingerprint_key: Current embedding pipeline fingerprint.

        Returns:
            Embedding index health state.
        """
        return await embedding_index_status(
            session=self._session,
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
        """Return source-level embedding diagnostics.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding vector dimensions.
            fingerprint_key: Current embedding pipeline fingerprint.
            current_fingerprint: Public current provider identity payload.

        Returns:
            Source-level embedding diagnostic payload.
        """
        return await embedding_source_status(
            session=self._session,
            source_name="context_vault",
            model_name=model_name,
            dimensions=dimensions,
            fingerprint_key=fingerprint_key,
            current_fingerprint=current_fingerprint,
        )

    async def update_chunk_embeddings(
        self,
        updates: list[ContextChunkEmbeddingUpdate],
    ) -> int:
        """Persist embedding updates and return affected row count.

        Args:
            updates: Embedding update contracts.

        Returns:
            Number of updated chunk rows.
        """
        return await update_chunk_embeddings(session=self._session, updates=updates)
