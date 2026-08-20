"""Embedding backfill and forced rebuild operations across Context sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.memory.application.context_embedding_health_service import (
    ContextEmbeddingHealthService,
)
from app.memory.application.retrieval.embedding_contract import EmbeddingProvider
from app.memory.application.retrieval.embedding_document import (
    build_embedding_document_text,
)
from app.memory.domain.contracts.context_contracts import (
    ContextChunkEmbeddingUpdate,
)
from app.memory.domain.entities.context_read_models import (
    ContextChunkRecord,
    ContextReindexResult,
)
from app.memory.domain.event_enum.context_enums import RagHealthState
from app.memory.domain.repositories.context_search_source import IContextSearchSource
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError
from app.shared.types.embedding_types import normalize_embedding_vector
from app.shared.types.types_convert_utils import now_utc
from asyncer import asyncify


class ContextEmbeddingBatchTransaction(Protocol):
    """Transaction boundary owned by one resumable embedding batch."""

    async def release_read_transaction(self) -> None:
        """End the read transaction before CPU-intensive embedding inference."""

    async def commit_embedding_updates(self) -> None:
        """Commit the current batch so later batches cannot roll it back."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _EmbeddingSourceBatch:
    """Selected source chunks detached from their read transaction."""

    source: IContextSearchSource
    chunks: tuple[ContextChunkRecord, ...]


class ContextEmbeddingReindexService:
    """Backfill and rebuild embeddings across configured Context sources."""

    def __init__(
        self,
        *,
        provider: EmbeddingProvider | None,
        search_sources: list[IContextSearchSource],
        health_service: ContextEmbeddingHealthService,
        batch_transaction: ContextEmbeddingBatchTransaction | None = None,
    ) -> None:
        """Initialize reindex dependencies.

        Args:
            provider: Optional embedding provider.
            search_sources: Configured retrieval and index sources.
            health_service: Embedding dependency health boundary.
            batch_transaction: Optional production transaction boundary per batch.
        """
        self._provider = provider
        self._search_sources = search_sources
        self._health_service = health_service
        self._batch_transaction = batch_transaction

    async def reindex(
        self,
        limit: int = 100,
        *,
        force: bool = False,
    ) -> ContextReindexResult:
        """Backfill or rebuild embeddings for stored context chunks.

        Args:
            limit: Maximum chunks to reindex in this batch.
            force: Whether existing matching embeddings should be rebuilt.

        Returns:
            Context embedding reindex result.
        """
        if limit < 1:
            raise MemoryContextValidationError("limit must be at least 1")
        provider = self._provider
        fingerprint = None if provider is None else provider.fingerprint()
        health = self._health_service.health()
        warnings = list(health.warnings)
        if (
            provider is None
            or fingerprint is None
            or health.vector is not RagHealthState.HEALTHY
            or health.embedding is not RagHealthState.HEALTHY
        ):
            warnings.append("Vector dependencies are not healthy; reindex skipped.")
            return ContextReindexResult(
                scanned=0,
                updated=0,
                skipped=0,
                warnings=tuple(warnings),
            )
        processed_by_source: dict[int, set[str]] = {}
        fingerprint_key = fingerprint.key()
        source_batches, scanned = await _select_embedding_source_batches(
            sources=self._search_sources,
            provider=provider,
            fingerprint_key=fingerprint_key,
            limit=limit,
            force=False,
            processed_by_source=processed_by_source,
        )
        if force and scanned < limit:
            forced_batches, forced_scanned = await _select_embedding_source_batches(
                sources=self._search_sources,
                provider=provider,
                fingerprint_key=fingerprint_key,
                limit=limit - scanned,
                force=True,
                processed_by_source=processed_by_source,
            )
            source_batches.extend(forced_batches)
            scanned += forced_scanned
        if self._batch_transaction is not None:
            await self._batch_transaction.release_read_transaction()
        updated = 0
        for source_batch in source_batches:
            updates = await _embedding_updates(
                provider=provider,
                chunks=list(source_batch.chunks),
            )
            updated += await source_batch.source.update_chunk_embeddings(updates)
            if self._batch_transaction is not None:
                await self._batch_transaction.commit_embedding_updates()
        return ContextReindexResult(
            scanned=scanned,
            updated=updated,
            skipped=scanned - updated,
            warnings=tuple(warnings),
        )


async def _select_embedding_source_batches(
    *,
    sources: list[IContextSearchSource],
    provider: EmbeddingProvider,
    fingerprint_key: str,
    limit: int,
    force: bool,
    processed_by_source: dict[int, set[str]],
) -> tuple[list[_EmbeddingSourceBatch], int]:
    source_batches: list[_EmbeddingSourceBatch] = []
    scanned = 0
    for source_index, source in enumerate(sources):
        remaining = limit - scanned
        if remaining < 1:
            break
        processed_ids = processed_by_source.setdefault(source_index, set())
        chunks = await source.chunks_missing_embeddings(
            model_name=provider.model_name,
            dimensions=provider.dimensions,
            fingerprint_key=fingerprint_key,
            limit=remaining + len(processed_ids),
            force=force,
        )
        selected = tuple(chunk for chunk in chunks if chunk.id not in processed_ids)[
            :remaining
        ]
        if not selected:
            continue
        processed_ids.update(chunk.id for chunk in selected)
        scanned += len(selected)
        source_batches.append(
            _EmbeddingSourceBatch(
                source=source,
                chunks=selected,
            )
        )
    return source_batches, scanned


async def _embed_documents(
    provider: EmbeddingProvider,
    texts: list[str],
) -> list[list[float]]:
    return await asyncify(provider.embed_documents, abandon_on_cancel=True)(texts)


async def _embedding_updates(
    *,
    provider: EmbeddingProvider,
    chunks: list[ContextChunkRecord],
) -> list[ContextChunkEmbeddingUpdate]:
    if not chunks:
        return []
    document_texts = [
        build_embedding_document_text(
            content=chunk.content,
            title=_chunk_title(chunk),
            heading=chunk.heading,
        )
        for chunk in chunks
    ]
    embeddings = await _embed_documents(
        provider,
        document_texts,
    )
    if len(embeddings) != len(chunks):
        raise MemoryContextValidationError(
            "Embedding provider returned an unexpected vector count"
        )
    updates: list[ContextChunkEmbeddingUpdate] = []
    fingerprint = provider.fingerprint()
    indexed_at = now_utc()
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        if len(embedding) != provider.dimensions:
            raise MemoryContextValidationError(
                "Embedding provider returned an unexpected dimension"
            )
        try:
            normalized = normalize_embedding_vector(
                embedding,
                expected_dimensions=provider.dimensions,
            )
        except ValueError as exc:
            raise MemoryContextValidationError(str(exc)) from exc
        updates.append(
            ContextChunkEmbeddingUpdate(
                chunk_id=chunk.id,
                embedding=normalized,
                embedding_model=provider.model_name,
                embedding_dimensions=provider.dimensions,
                embedding_provider=fingerprint.provider,
                embedding_provider_version=fingerprint.provider_version,
                embedding_pooling_mode=fingerprint.pooling_mode,
                embedding_normalize=fingerprint.normalize,
                embedding_fingerprint_key=fingerprint.key(),
                embedding_fingerprint=fingerprint.snapshot_payload(
                    indexed_at=indexed_at
                ),
                embedding_indexed_at=indexed_at,
            )
        )
    return updates


def _chunk_title(chunk: ContextChunkRecord) -> str | None:
    title = chunk.chunk_metadata.get("title")
    return title if isinstance(title, str) else None
