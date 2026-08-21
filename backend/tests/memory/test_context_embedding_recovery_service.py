"""Incremental Context embedding recovery contracts."""

from __future__ import annotations

import anyio
from app.memory.application.contexts.embedding.context_embedding_recovery_service import (
    ContextEmbeddingRecoveryService,
)
from app.memory.domain.entities.context_read_models import ContextReindexResult


class _FakeRecoveryTarget:
    def __init__(self, results: list[ContextReindexResult]) -> None:
        self._results = results
        self.calls: list[tuple[int, bool]] = []

    async def reindex_embeddings(
        self,
        limit: int = 100,
        *,
        force: bool = False,
    ) -> ContextReindexResult:
        self.calls.append((limit, force))
        return self._results.pop(0)


def test_embedding_recovery_drains_missing_chunks_without_forcing_current_rows() -> (
    None
):
    """Recovery should continue bounded batches and never force healthy vectors."""
    target = _FakeRecoveryTarget(
        [
            ContextReindexResult(scanned=2, updated=2, skipped=0, warnings=()),
            ContextReindexResult(scanned=1, updated=1, skipped=0, warnings=()),
        ]
    )
    service = ContextEmbeddingRecoveryService(batch_size=2, max_batches=5)

    result = anyio.run(service.recover, target)

    assert target.calls == [(2, False), (2, False)]
    assert result.scanned == 3
    assert result.updated == 3
    assert result.warnings == ()


def test_embedding_recovery_stops_when_no_progress_is_possible() -> None:
    """A source that scans but cannot update must not create an infinite loop."""
    target = _FakeRecoveryTarget(
        [ContextReindexResult(scanned=2, updated=0, skipped=2, warnings=())]
    )
    service = ContextEmbeddingRecoveryService(batch_size=2, max_batches=5)

    result = anyio.run(service.recover, target)

    assert target.calls == [(2, False)]
    assert result.scanned == 2
    assert result.updated == 0


def test_embedding_recovery_reports_when_bounded_work_must_resume() -> None:
    """Exhausting the safety bound should keep readiness visibly degraded."""
    target = _FakeRecoveryTarget(
        [
            ContextReindexResult(scanned=1, updated=1, skipped=0, warnings=()),
            ContextReindexResult(scanned=1, updated=1, skipped=0, warnings=()),
        ]
    )
    service = ContextEmbeddingRecoveryService(batch_size=1, max_batches=2)

    result = anyio.run(service.recover, target)

    assert result.updated == 2
    assert result.warnings == (
        "Embedding recovery reached its batch limit; resume is required.",
    )
