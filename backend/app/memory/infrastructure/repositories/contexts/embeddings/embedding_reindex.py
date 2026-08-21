"""Embedding reindex persistence helpers for Context Vault chunks."""

from __future__ import annotations

from app.memory.domain.contracts.context_contracts import ContextChunkEmbeddingUpdate
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextEmbeddingSourceStatus,
)
from app.memory.domain.event_enum.context_enums import RagHealthState
from app.memory.infrastructure.models.context_models import ContextChunkORM, ContextORM
from app.memory.infrastructure.repositories.contexts.records.mapping import (
    map_chunk_row,
)
from app.shared.types.extra_types import JSONObject
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


async def chunks_missing_embeddings(
    session: AsyncSession,
    model_name: str,
    dimensions: int,
    fingerprint_key: str,
    limit: int,
    force: bool = False,
) -> list[ContextChunkRecord]:
    """Return chunks requiring embedding reindex for the current model.

    Args:
        session: Active async database session.
        model_name: Current embedding model name.
        dimensions: Current embedding dimensions.
        fingerprint_key: Current embedding generation fingerprint key.
        limit: Maximum chunks to scan.
        force: Whether to rebuild all active chunk embeddings even if model metadata matches.

    Returns:
        Chunks requiring embedding backfill or forced rebuild.
    """
    statement = (
        select(ContextChunkORM)
        .join(ContextORM, ContextORM.id == ContextChunkORM.context_id)
        .where(ContextORM.is_archived.is_(False))
        .limit(limit)
    )
    if not force:
        statement = statement.where(
            or_(
                ContextChunkORM.embedding.is_(None),
                ContextChunkORM.embedding_model != model_name,
                ContextChunkORM.embedding_dimensions != dimensions,
                ContextChunkORM.embedding_fingerprint_key.is_(None),
                ContextChunkORM.embedding_fingerprint_key != fingerprint_key,
            )
        )
    statement = statement.order_by(
        case(
            (
                (
                    ContextChunkORM.embedding.is_not(None)
                    & (ContextChunkORM.embedding_model == model_name)
                    & (ContextChunkORM.embedding_dimensions == dimensions)
                    & (ContextChunkORM.embedding_fingerprint_key == fingerprint_key)
                ),
                1,
            ),
            else_=0,
        ).asc(),
        ContextChunkORM.embedding_indexed_at.asc().nulls_first(),
        ContextChunkORM.created_at.asc(),
    )
    rows = await session.execute(statement)
    chunks = [map_chunk_row(row) for row in rows.scalars().all()]
    return chunks


async def update_chunk_embeddings(
    session: AsyncSession,
    updates: list[ContextChunkEmbeddingUpdate],
) -> int:
    """Persist context chunk embedding updates.

    Args:
        session: Active async database session.
        updates: Embedding updates keyed by chunk identifier.

    Returns:
        Number of chunks updated.
    """
    if not updates:
        return 0
    rows = await session.scalars(
        select(ContextChunkORM).where(
            ContextChunkORM.id.in_(update.chunk_id for update in updates)
        )
    )
    chunks_by_id = {chunk.id: chunk for chunk in rows.all()}
    updated = 0
    for update in updates:
        chunk = chunks_by_id.get(update.chunk_id)
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
    await session.flush()
    return updated


async def embedding_index_status(
    session: AsyncSession,
    model_name: str,
    dimensions: int,
    fingerprint_key: str,
) -> RagHealthState:
    """Return whether active context chunks match the current embedding fingerprint.

    Args:
        session: Active async database session.
        model_name: Current embedding model name.
        dimensions: Current embedding dimensions.
        fingerprint_key: Current embedding generation fingerprint key.

    Returns:
        HEALTHY when no active chunk needs embeddings; REINDEX_REQUIRED otherwise.
    """
    statement = (
        select(ContextChunkORM.id)
        .join(ContextORM, ContextORM.id == ContextChunkORM.context_id)
        .where(ContextORM.is_archived.is_(False))
        .where(
            or_(
                ContextChunkORM.embedding.is_(None),
                ContextChunkORM.embedding_model != model_name,
                ContextChunkORM.embedding_dimensions != dimensions,
                ContextChunkORM.embedding_fingerprint_key.is_(None),
                ContextChunkORM.embedding_fingerprint_key != fingerprint_key,
            )
        )
        .limit(1)
    )
    stale_chunk_id = await session.scalar(statement)
    if stale_chunk_id is None:
        return RagHealthState.HEALTHY
    return RagHealthState.REINDEX_REQUIRED


async def embedding_source_status(
    session: AsyncSession,
    source_name: str,
    model_name: str,
    dimensions: int,
    fingerprint_key: str,
    current_fingerprint: JSONObject,
) -> ContextEmbeddingSourceStatus:
    """Return source-level context embedding fingerprint diagnostics.

    Args:
        session: Active async database session.
        source_name: Human-readable source label.
        model_name: Current embedding model name.
        dimensions: Current embedding dimensions.
        fingerprint_key: Current embedding generation fingerprint key.
        current_fingerprint: Current timestamp-free fingerprint payload.

    Returns:
        Source-level embedding status and row counts.
    """
    base_conditions = (ContextORM.is_archived.is_(False),)
    total_rows = await session.scalar(
        select(func.count(ContextChunkORM.id))
        .join(ContextORM, ContextORM.id == ContextChunkORM.context_id)
        .where(*base_conditions)
    )
    current_rows = await session.scalar(
        select(func.count(ContextChunkORM.id))
        .join(ContextORM, ContextORM.id == ContextChunkORM.context_id)
        .where(
            *base_conditions,
            ContextChunkORM.embedding.is_not(None),
            ContextChunkORM.embedding_model == model_name,
            ContextChunkORM.embedding_dimensions == dimensions,
            ContextChunkORM.embedding_fingerprint_key == fingerprint_key,
        )
    )
    missing_rows = await session.scalar(
        select(func.count(ContextChunkORM.id))
        .join(ContextORM, ContextORM.id == ContextChunkORM.context_id)
        .where(
            *base_conditions,
            or_(
                ContextChunkORM.embedding.is_(None),
                ContextChunkORM.embedding_fingerprint_key.is_(None),
            ),
        )
    )
    fingerprint_rows = await session.execute(
        select(
            ContextChunkORM.embedding_provider,
            ContextChunkORM.embedding_model,
            ContextChunkORM.embedding_provider_version,
            ContextChunkORM.embedding_pooling_mode,
            ContextChunkORM.embedding_normalize,
            ContextChunkORM.embedding_dimensions,
        )
        .join(ContextORM, ContextORM.id == ContextChunkORM.context_id)
        .where(
            *base_conditions,
            ContextChunkORM.embedding_fingerprint_key.is_not(None),
        )
        .distinct()
    )
    total = int(total_rows or 0)
    current = int(current_rows or 0)
    stale = max(total - current, 0)
    missing = int(missing_rows or 0)
    return ContextEmbeddingSourceStatus(
        source_name=source_name,
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
