"""Bounded, resumable embedding recovery across Context sources."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

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
        *,
        batch_observer: Callable[[ContextReindexResult], None] | None = None,
    ) -> ContextReindexResult:
        """Recover missing/stale embeddings without rebuilding current vectors.

        Args:
            context_service: Context boundary used for bounded reindex batches.
            batch_observer: Optional synchronous observer called once for every
                actual bounded batch result.

        Returns:
            Aggregate recovery result.
        """
        async with self._lock:
            pending_note_ids = self._pending_note_ids
            self._pending_note_ids = ()

            def retain_pending(note_ids: tuple[str, ...]) -> None:
                """Merge uncertain identities without overwriting newer invalidations."""
                self._pending_note_ids = tuple(
                    dict.fromkeys((*note_ids, *self._pending_note_ids))
                )

            scanned = 0
            updated = 0
            skipped = 0
            warnings: list[str] = []
            actual_batches = 0
            reached_batch_limit = False
            stopped_without_progress = False

            def record_batch(batch: ContextReindexResult) -> None:
                """Accumulate one result and publish exact batch evidence."""
                nonlocal scanned, updated, skipped
                scanned += batch.scanned
                updated += batch.updated
                skipped += batch.skipped
                warnings.extend(
                    warning for warning in batch.warnings if warning not in warnings
                )
                if batch_observer is not None:
                    batch_observer(batch)

            if pending_note_ids:
                try:
                    batch = await context_service.reindex_embeddings(
                        limit=self._batch_size,
                        force=False,
                        note_ids=pending_note_ids,
                    )
                except BaseException:
                    # Preserve the exact targeted identities across source
                    # failure/cancellation and merge any invalidations recorded
                    # while the await was in flight.
                    retain_pending(pending_note_ids)
                    raise
                actual_batches += 1
                pending_complete = (
                    not batch.warnings
                    and 0 < batch.scanned < self._batch_size
                    and batch.updated + batch.skipped >= batch.scanned
                )
                if not pending_complete:
                    # ContextReindexResult has no per-note receipt. Preserve
                    # every exact identity when the bounded result cannot prove
                    # that the targeted lane drained.
                    retain_pending(pending_note_ids)
                try:
                    record_batch(batch)
                except Exception:
                    # Observation is part of the recovery evidence boundary;
                    # retain exact identities if evidence publication fails.
                    retain_pending(pending_note_ids)
                    raise
                stopped_without_progress = batch.updated == 0
                reached_batch_limit = actual_batches >= self._max_batches

            for _ in range(self._max_batches - actual_batches):
                batch = await context_service.reindex_embeddings(
                    limit=self._batch_size,
                    force=False,
                )
                actual_batches += 1
                record_batch(batch)
                if (
                    batch.warnings
                    or batch.updated == 0
                    or batch.scanned < self._batch_size
                ):
                    stopped_without_progress = batch.updated == 0
                    break
            else:
                reached_batch_limit = actual_batches >= self._max_batches

            if reached_batch_limit and not warnings and not stopped_without_progress:
                warnings.append(
                    "Embedding recovery reached its batch limit; resume is required."
                )
            return ContextReindexResult(
                scanned=scanned,
                updated=updated,
                skipped=skipped,
                warnings=tuple(warnings),
            )
