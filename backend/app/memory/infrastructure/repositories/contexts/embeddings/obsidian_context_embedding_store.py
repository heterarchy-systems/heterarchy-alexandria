"""Embedding persistence and diagnostics for Obsidian Context recall."""

from __future__ import annotations

from app.memory.domain.contracts.context_contracts import ContextChunkEmbeddingUpdate
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
)
from app.memory.domain.event_enum.context_enums import (
    RagHealthState,
)
from app.memory.infrastructure.repositories.contexts.obsidian.obsidian_context_mapping import (
    chunk_record_from_obsidian_row,
    raw_obsidian_chunk_id,
)
from app.memory.infrastructure.repositories.contexts.search.obsidian_recall_policy import (
    _default_recall_visibility_conditions,
)
from app.obsidian.infrastructure.models.obsidian_index_models import (
    ObsidianChunkORM,
    ObsidianFileORM,
)
from app.shared.types.extra_types import JSONObject
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class ObsidianContextEmbeddingStore:
    """Manage embeddings for indexed Obsidian Context chunks."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the shared async database session.

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
        force: bool = False,
    ) -> list[ContextChunkRecord]:
        """Return indexed Obsidian chunks missing current embedding metadata.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.
            limit: Maximum chunks to scan.
            force: Whether to rebuild existing embeddings even if metadata matches.

        Returns:
            Obsidian chunks mapped into Context RAG chunk read models.
        """
        statement = (
            select(ObsidianChunkORM, ObsidianFileORM.title)
            .join(ObsidianFileORM, ObsidianFileORM.note_id == ObsidianChunkORM.note_id)
            .where(*_default_recall_visibility_conditions())
            .where(func.length(func.trim(ObsidianChunkORM.text)) > 0)
            .limit(limit)
        )
        if not force:
            statement = statement.where(
                or_(
                    ObsidianChunkORM.embedding.is_(None),
                    ObsidianChunkORM.embedding_model != model_name,
                    ObsidianChunkORM.embedding_dimensions != dimensions,
                    ObsidianChunkORM.embedding_fingerprint_key.is_(None),
                    ObsidianChunkORM.embedding_fingerprint_key != fingerprint_key,
                )
            )
        statement = statement.order_by(
            case(
                (
                    (
                        ObsidianChunkORM.embedding.is_not(None)
                        & (ObsidianChunkORM.embedding_model == model_name)
                        & (ObsidianChunkORM.embedding_dimensions == dimensions)
                        & (
                            ObsidianChunkORM.embedding_fingerprint_key
                            == fingerprint_key
                        )
                    ),
                    1,
                ),
                else_=0,
            ).asc(),
            ObsidianChunkORM.embedding_indexed_at.asc().nulls_first(),
            ObsidianChunkORM.created_at.asc(),
        )
        rows = await self._session.execute(statement)
        chunks = [
            chunk_record_from_obsidian_row(chunk, title=title)
            for chunk, title in rows.all()
        ]
        return chunks

    async def embedding_index_status(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
    ) -> RagHealthState:
        """Return whether indexed Obsidian chunks match the current fingerprint.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.

        Returns:
            HEALTHY when chunks match, otherwise REINDEX_REQUIRED.
        """
        statement = (
            select(ObsidianChunkORM.id)
            .join(ObsidianFileORM, ObsidianFileORM.note_id == ObsidianChunkORM.note_id)
            .where(*_default_recall_visibility_conditions())
            .where(func.length(func.trim(ObsidianChunkORM.text)) > 0)
            .where(
                or_(
                    ObsidianChunkORM.embedding.is_(None),
                    ObsidianChunkORM.embedding_model != model_name,
                    ObsidianChunkORM.embedding_dimensions != dimensions,
                    ObsidianChunkORM.embedding_fingerprint_key.is_(None),
                    ObsidianChunkORM.embedding_fingerprint_key != fingerprint_key,
                )
            )
            .limit(1)
        )
        stale_chunk_id = await self._session.scalar(statement)
        if stale_chunk_id is None:
            return RagHealthState.HEALTHY
        return RagHealthState.REINDEX_REQUIRED

    async def embedding_source_status(
        self,
        model_name: str,
        dimensions: int,
        fingerprint_key: str,
        current_fingerprint: JSONObject,
    ) -> ContextEmbeddingSourceStatus:
        """Return source-level Obsidian embedding fingerprint diagnostics.

        Args:
            model_name: Current embedding model name.
            dimensions: Current embedding dimensions.
            fingerprint_key: Current embedding generation fingerprint key.
            current_fingerprint: Current timestamp-free fingerprint payload.

        Returns:
            Obsidian source embedding diagnostics.
        """
        total_rows = await self._session.scalar(
            select(func.count(ObsidianChunkORM.id))
            .join(ObsidianFileORM, ObsidianFileORM.note_id == ObsidianChunkORM.note_id)
            .where(*_default_recall_visibility_conditions())
            .where(func.length(func.trim(ObsidianChunkORM.text)) > 0)
        )
        current_rows = await self._session.scalar(
            select(func.count(ObsidianChunkORM.id))
            .join(ObsidianFileORM, ObsidianFileORM.note_id == ObsidianChunkORM.note_id)
            .where(
                *_default_recall_visibility_conditions(),
                func.length(func.trim(ObsidianChunkORM.text)) > 0,
                ObsidianChunkORM.embedding.is_not(None),
                ObsidianChunkORM.embedding_model == model_name,
                ObsidianChunkORM.embedding_dimensions == dimensions,
                ObsidianChunkORM.embedding_fingerprint_key == fingerprint_key,
            )
        )
        missing_rows = await self._session.scalar(
            select(func.count(ObsidianChunkORM.id))
            .join(ObsidianFileORM, ObsidianFileORM.note_id == ObsidianChunkORM.note_id)
            .where(
                *_default_recall_visibility_conditions(),
                func.length(func.trim(ObsidianChunkORM.text)) > 0,
                or_(
                    ObsidianChunkORM.embedding.is_(None),
                    ObsidianChunkORM.embedding_fingerprint_key.is_(None),
                ),
            )
        )
        fingerprint_rows = await self._session.execute(
            select(
                ObsidianChunkORM.embedding_provider,
                ObsidianChunkORM.embedding_model,
                ObsidianChunkORM.embedding_provider_version,
                ObsidianChunkORM.embedding_pooling_mode,
                ObsidianChunkORM.embedding_normalize,
                ObsidianChunkORM.embedding_dimensions,
            )
            .join(ObsidianFileORM, ObsidianFileORM.note_id == ObsidianChunkORM.note_id)
            .where(
                *_default_recall_visibility_conditions(),
                func.length(func.trim(ObsidianChunkORM.text)) > 0,
                ObsidianChunkORM.embedding_fingerprint_key.is_not(None),
            )
            .distinct()
        )
        total = int(total_rows or 0)
        current = int(current_rows or 0)
        stale = max(total - current, 0)
        missing = int(missing_rows or 0)
        return ContextEmbeddingSourceStatus(
            source_name="obsidian_vault",
            status=RagHealthState.HEALTHY
            if stale == 0
            else RagHealthState.REINDEX_REQUIRED,
            total_rows=total,
            current_rows=current,
            stale_rows=stale,
            missing_rows=missing,
            current_fingerprint=current_fingerprint,
            stored_fingerprints=tuple(
                _fingerprint_payload(
                    provider=provider,
                    model=model,
                    provider_version=provider_version,
                    pooling_mode=pooling_mode,
                    normalize=normalize,
                    dimensions=stored_dimensions,
                )
                for (
                    provider,
                    model,
                    provider_version,
                    pooling_mode,
                    normalize,
                    stored_dimensions,
                ) in fingerprint_rows.all()
            ),
        )

    async def update_chunk_embeddings(
        self,
        updates: list[ContextChunkEmbeddingUpdate],
    ) -> int:
        """Persist embedding updates for indexed Obsidian chunks.

        Args:
            updates: Embedding updates keyed by prefixed Obsidian chunk id.

        Returns:
            Number of Obsidian chunks updated.
        """
        if not updates:
            return 0
        raw_chunk_ids = [raw_obsidian_chunk_id(update.chunk_id) for update in updates]
        rows = await self._session.scalars(
            select(ObsidianChunkORM).where(ObsidianChunkORM.id.in_(raw_chunk_ids))
        )
        chunks_by_id = {chunk.id: chunk for chunk in rows.all()}
        updated = 0
        for update in updates:
            chunk = chunks_by_id.get(raw_obsidian_chunk_id(update.chunk_id))
            if chunk is None:
                continue
            chunk.embedding = update.embedding
            chunk.embedding_model = update.embedding_model
            chunk.embedding_dimensions = update.embedding_dimensions
            chunk.embedding_provider = update.embedding_provider
            chunk.embedding_provider_version = update.embedding_provider_version
            chunk.embedding_pooling_mode = update.embedding_pooling_mode
            chunk.embedding_normalize = update.embedding_normalize
            chunk.embedding_fingerprint_key = update.embedding_fingerprint_key
            chunk.embedding_fingerprint_json = update.embedding_fingerprint
            chunk.embedding_indexed_at = update.embedding_indexed_at
            updated += 1
        await self._session.flush()
        return updated


def _fingerprint_payload(
    provider: str | None,
    model: str | None,
    provider_version: str | None,
    pooling_mode: str | None,
    normalize: bool | None,
    dimensions: int | None,
) -> JSONObject:
    return {
        "provider": provider,
        "model": model,
        "provider_version": provider_version,
        "pooling_mode": pooling_mode,
        "normalize": normalize,
        "dimensions": dimensions,
    }
