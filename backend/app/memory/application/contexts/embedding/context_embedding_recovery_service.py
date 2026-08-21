"""Bounded, resumable embedding recovery across Context sources."""

from __future__ import annotations

import asyncio
from typing import Protocol

from app.memory.domain.entities.context_read_models import ContextReindexResult
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError


class ContextEmbeddingRecoveryTarget(Protocol):
    """Minimal Context boundary required by incremental recovery."""

    async def reindex_embeddings(
        self,
        limit: int = 100,
        force: bool = False,
    ) -> ContextReindexResult:
        """Backfill one embedding batch.

        Args:
            limit: Maximum rows scanned.
            force: Whether current vectors should also be rebuilt.

        Returns:
            One batch reindex result.
        """


class ContextEmbeddingRecoveryService:
    """Drain missing or stale embeddings in bounded, non-forced batches."""

    def __init__(self, batch_size: int, max_batches: int) -> None:
        if batch_size < 1:
            raise MemoryContextValidationError("batch_size must be at least 1")
        if max_batches < 1:
            raise MemoryContextValidationError("max_batches must be at least 1")
        self._batch_size = batch_size
        self._max_batches = max_batches
        self._lock = asyncio.Lock()

    async def recover(
        self,
        context_service: ContextEmbeddingRecoveryTarget,
    ) -> ContextReindexResult:
        """Recover missing/stale embeddings without rebuilding current vectors.

        Args:
            context_service: Context boundary used for bounded reindex batches.

        Returns:
            Aggregate recovery result.
        """
        async with self._lock:
            scanned = 0
            updated = 0
            skipped = 0
            warnings: list[str] = []
            exhausted_batch_limit = True
            for _ in range(self._max_batches):
                batch = await context_service.reindex_embeddings(
                    limit=self._batch_size,
                    force=False,
                )
                scanned += batch.scanned
                updated += batch.updated
                skipped += batch.skipped
                warnings.extend(
                    warning for warning in batch.warnings if warning not in warnings
                )
                if (
                    batch.warnings
                    or batch.updated == 0
                    or batch.scanned < self._batch_size
                ):
                    exhausted_batch_limit = False
                    break
            if exhausted_batch_limit:
                warnings.append(
                    "Embedding recovery reached its batch limit; resume is required."
                )
            return ContextReindexResult(
                scanned=scanned,
                updated=updated,
                skipped=skipped,
                warnings=tuple(warnings),
            )
