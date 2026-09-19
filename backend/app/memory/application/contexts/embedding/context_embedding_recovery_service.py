"""Bounded, resumable embedding recovery across Context sources."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from app.memory.application.contexts.records.context_service_ports import (
    ContextEmbeddingReindexPort,
)
from app.memory.domain.entities.context_read_models import ContextReindexResult
from app.shared.exceptions.memory_context_exceptions import MemoryContextValidationError


class ContextEmbeddingRecoveryService:
    """Drain missing or stale embeddings in bounded, non-forced batches."""

    def __init__(self, batch_size: int, max_batches: int) -> None:
        """Initialize ContextEmbeddingRecoveryService state and dependencies.

        Args:
            batch_size: Batch size used by this operation.
            max_batches: Max batches used by this operation.
        """
        if batch_size < 1:
            raise MemoryContextValidationError("batch_size must be at least 1")
        if max_batches < 1:
            raise MemoryContextValidationError("max_batches must be at least 1")
        self._batch_size = batch_size
        self._max_batches = max_batches
        self._lock = asyncio.Lock()
        self._pending_note_ids: tuple[str, ...] = ()

    def record_invalidations(self, note_ids: Sequence[str]) -> None:
        """Queue compile-invalidated note ids for the next bounded recovery.

        Args:
            note_ids: Source note identities whose chunks must re-embed.
        """
        merged = dict.fromkeys((*self._pending_note_ids, *note_ids))
        self._pending_note_ids = tuple(merged)

    async def recover(
        self,
        context_service: ContextEmbeddingReindexPort,
    ) -> ContextReindexResult:
        """Recover missing/stale embeddings without rebuilding current vectors.

        Args:
            context_service: Context boundary used for bounded reindex batches.

        Returns:
            Aggregate recovery result.
        """
        async with self._lock:
            pending_note_ids, self._pending_note_ids = self._pending_note_ids, ()
            scanned = 0
            updated = 0
            skipped = 0
            warnings: list[str] = []
            exhausted_batch_limit = True
            if pending_note_ids:
                batch = await context_service.reindex_embeddings(
                    limit=self._batch_size * self._max_batches,
                    force=False,
                    note_ids=pending_note_ids,
                )
                scanned += batch.scanned
                updated += batch.updated
                skipped += batch.skipped
                warnings.extend(
                    warning for warning in batch.warnings if warning not in warnings
                )
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
