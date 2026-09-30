"""Incremental Context embedding recovery contracts."""

from __future__ import annotations

import anyio
import pytest

from app.memory.application.contexts.embedding.context_embedding_recovery_service import (
    ContextEmbeddingRecoveryService,
)
from app.memory.domain.entities.context_read_models import ContextReindexResult


class _FakeRecoveryTarget:
    def __init__(self, results: list[ContextReindexResult]) -> None:
        self._results = results
        self.calls: list[tuple[int, bool, tuple[str, ...] | None]] = []

    async def reindex_embeddings(
        self,
        limit: int = 100,
        *,
        force: bool = False,
        note_ids: tuple[str, ...] | None = None,
    ) -> ContextReindexResult:
        self.calls.append((limit, force, note_ids))
        return self._results.pop(0)


class _BlockingFailureTarget(_FakeRecoveryTarget):
    def __init__(self, entered, release) -> None:
        super().__init__(
            [ContextReindexResult(scanned=0, updated=0, skipped=0, warnings=())]
        )
        self._entered = entered
        self._release = release
        self._fail_next = True

    async def reindex_embeddings(
        self,
        limit: int = 100,
        *,
        force: bool = False,
        note_ids: tuple[str, ...] | None = None,
    ) -> ContextReindexResult:
        self.calls.append((limit, force, note_ids))
        if self._fail_next:
            self._fail_next = False
            self._entered.set()
            await self._release.wait()
            raise RuntimeError("source read failed")
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

    assert target.calls == [(2, False, None), (2, False, None)]
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

    assert target.calls == [(2, False, None)]
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


def test_embedding_recovery_observes_pending_and_catchup_batches_with_one_total_bound() -> (
    None
):
    """Pending invalidations share the total batch ceiling with catch-up work."""
    target = _FakeRecoveryTarget(
        [
            ContextReindexResult(scanned=2, updated=2, skipped=0, warnings=()),
            ContextReindexResult(scanned=2, updated=2, skipped=0, warnings=()),
            ContextReindexResult(scanned=2, updated=2, skipped=0, warnings=()),
            ContextReindexResult(scanned=0, updated=0, skipped=0, warnings=()),
        ]
    )
    service = ContextEmbeddingRecoveryService(batch_size=2, max_batches=2)
    service.record_invalidations(("ctx-a", "ctx-b"))
    observed: list[ContextReindexResult] = []

    async def scenario():
        first = await service.recover(target, batch_observer=observed.append)
        second = await service.recover(target, batch_observer=observed.append)
        return first, second

    first, second = anyio.run(scenario)

    assert len(observed) == 4
    assert first.updated == 4
    assert first.warnings == (
        "Embedding recovery reached its batch limit; resume is required.",
    )
    assert second.updated == 2
    assert target.calls == [
        (2, False, ("ctx-a", "ctx-b")),
        (2, False, None),
        (2, False, ("ctx-a", "ctx-b")),
        (2, False, None),
    ]


def test_embedding_recovery_clears_pending_only_after_bounded_target_completion() -> (
    None
):
    """A short fully-accounted targeted batch releases exact pending IDs."""
    target = _FakeRecoveryTarget(
        [
            ContextReindexResult(scanned=1, updated=1, skipped=0, warnings=()),
            ContextReindexResult(scanned=0, updated=0, skipped=0, warnings=()),
            ContextReindexResult(scanned=0, updated=0, skipped=0, warnings=()),
        ]
    )
    service = ContextEmbeddingRecoveryService(batch_size=2, max_batches=2)
    service.record_invalidations(("ctx-only",))

    anyio.run(service.recover, target)
    anyio.run(service.recover, target)

    assert target.calls == [
        (2, False, ("ctx-only",)),
        (2, False, None),
        (2, False, None),
    ]


def test_embedding_recovery_observer_failure_retains_uncertain_pending_ids() -> None:
    """Observer failure cannot discard an incompletely proven targeted lane."""
    target = _FakeRecoveryTarget(
        [
            ContextReindexResult(scanned=2, updated=2, skipped=0, warnings=()),
            ContextReindexResult(scanned=0, updated=0, skipped=0, warnings=()),
        ]
    )
    service = ContextEmbeddingRecoveryService(batch_size=2, max_batches=1)
    service.record_invalidations(("ctx-uncertain",))

    def fail_observer(_batch: ContextReindexResult) -> None:
        raise RuntimeError("observer unavailable")

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="observer unavailable"):
            await service.recover(target, batch_observer=fail_observer)
        await service.recover(target)

    anyio.run(scenario)

    assert target.calls == [
        (2, False, ("ctx-uncertain",)),
        (2, False, ("ctx-uncertain",)),
    ]


def test_embedding_recovery_await_failure_merges_concurrent_invalidations() -> None:
    """Await failure preserves old identities and newer invalidations together."""

    async def scenario() -> list[tuple[int, bool, tuple[str, ...] | None]]:
        entered = anyio.Event()
        release = anyio.Event()
        target = _BlockingFailureTarget(entered, release)
        service = ContextEmbeddingRecoveryService(batch_size=2, max_batches=1)
        service.record_invalidations(("ctx-old",))
        errors: list[RuntimeError] = []

        async def recover() -> None:
            try:
                await service.recover(target)
            except RuntimeError as exc:
                errors.append(exc)

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(recover)
            await entered.wait()
            service.record_invalidations(("ctx-new",))
            release.set()

        assert errors and str(errors[0]) == "source read failed"
        await service.recover(target)
        return target.calls

    calls = anyio.run(scenario)

    assert calls == [
        (2, False, ("ctx-old",)),
        (2, False, ("ctx-old", "ctx-new")),
    ]
