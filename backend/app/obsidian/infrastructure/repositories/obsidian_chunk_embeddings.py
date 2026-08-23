"""Embedding preservation helpers for Obsidian chunk reindexing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.obsidian.infrastructure.models.obsidian_index_models import ObsidianChunkORM
from app.shared.types.embedding_types import EmbeddingVector
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True)
class ExistingChunkEmbedding:
    """Embedding metadata preserved across unchanged Obsidian chunks."""

    embedding: EmbeddingVector
    model: str
    dimensions: int
    provider: str | None
    provider_version: str | None
    pooling_mode: str | None
    normalize: bool | None
    fingerprint_key: str | None
    fingerprint: JSONObject | None
    indexed_at: datetime | None


async def existing_chunk_embeddings(
    session: AsyncSession,
    note_id: str,
) -> dict[tuple[int, str], ExistingChunkEmbedding]:
    """Return existing embeddings keyed by stable chunk identity.

    Args:
        session: Active async database session.
        note_id: Note whose existing chunk embeddings should be inspected.

    Returns:
        Existing embeddings keyed by chunk index and content hash.
    """
    rows = await session.execute(
        select(ObsidianChunkORM).where(ObsidianChunkORM.note_id == note_id)
    )
    embeddings: dict[tuple[int, str], ExistingChunkEmbedding] = {}
    for chunk in rows.scalars().all():
        if (
            chunk.embedding is None
            or chunk.embedding_model is None
            or chunk.embedding_dimensions is None
        ):
            continue
        embeddings[(chunk.chunk_index, chunk.content_hash)] = ExistingChunkEmbedding(
            embedding=chunk.embedding,
            model=chunk.embedding_model,
            dimensions=chunk.embedding_dimensions,
            provider=chunk.embedding_provider,
            provider_version=chunk.embedding_provider_version,
            pooling_mode=chunk.embedding_pooling_mode,
            normalize=chunk.embedding_normalize,
            fingerprint_key=chunk.embedding_fingerprint_key,
            fingerprint=chunk.embedding_fingerprint_json,
            indexed_at=chunk.embedding_indexed_at,
        )
    return embeddings
