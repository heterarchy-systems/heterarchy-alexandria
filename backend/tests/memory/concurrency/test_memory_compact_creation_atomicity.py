"""Cross-process atomicity tests for Memory Compact creation."""

from __future__ import annotations

import asyncio
import errno
import multiprocessing
import os
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import BrokenBarrierError, Event, Lock
from typing import Protocol

import anyio
import pytest
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.domain.entities.memory_compact import MemoryCompact
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactCreate,
    MemoryCompactSourceRefCreate,
)
from app.memory.infrastructure.repositories import (
    memory_compact_repository as memory_compact_repository_module,
)
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.memory.infrastructure.repositories.memory_compacts.creation_lock import (
    MemoryCompactCreationLock,
)
from app.memory.infrastructure.repositories.memory_compacts.note_store import (
    MemoryCompactNoteStore,
)


class _ProcessBarrier(Protocol):
    def wait(self, timeout: float | None = None) -> int:
        """Wait for every participating process."""


class _ResultQueue(Protocol):
    def put(self, result: tuple[str, bool]) -> None:
        """Publish one process result."""


class _RaceWideningRepository(ObsidianMemoryCompactRepository):
    """Synchronize concurrent creates after both signature checks complete."""

    def __init__(self, *, vault_path: str, create_gate: _ProcessBarrier) -> None:
        super().__init__(
            vault_path=vault_path,
            relative_dir="Alexandria/Memory Compacts",
        )
        self._create_gate = create_gate

    async def create(self, payload: MemoryCompactCreate) -> MemoryCompact:
        with suppress(BrokenBarrierError):
            await asyncio.to_thread(self._create_gate.wait, 2)
        return await super().create(payload)


class _DelayedDescriptorOpeningLock(MemoryCompactCreationLock):
    """Expose deterministic control over descriptor opening completion."""

    def __init__(self, *, vault_path: Path) -> None:
        super().__init__(
            vault_path=vault_path,
            relative_dir="Alexandria/Memory Compacts",
        )
        self.open_started = Event()
        self.allow_open = Event()
        self.open_finished = Event()
        self.opened_descriptors: list[int] = []

    def _open_descriptor(self) -> int:
        self.open_started.set()
        if not self.allow_open.wait(timeout=5):
            raise TimeoutError("descriptor-opening test gate was not released")
        descriptor = super()._open_descriptor()
        self.opened_descriptors.append(descriptor)
        self.open_finished.set()
        return descriptor


def _payload(*, reverse_sources: bool) -> MemoryCompactCreate:
    source_refs = [
        MemoryCompactSourceRefCreate(
            source_type="CONTEXT",
            source_id=source_id,
            title=f"Context {source_id}",
            detail_path=f"/memory/contexts/{source_id}",
        )
        for source_id in ("ctx-a", "ctx-b")
    ]
    if reverse_sources:
        source_refs.reverse()
    return MemoryCompactCreate(
        project="heterarchy-alexandria",
        covered_from=datetime(2026, 8, 1, tzinfo=UTC),
        covered_to=datetime(2026, 8, 10, tzinfo=UTC),
        markdown_body="Identical normalized Memory Compact body.\n",
        status=MemoryCompactStatus.DRAFT,
        source_refs=tuple(source_refs),
    )


def _create_in_process(
    vault_path: str,
    reverse_sources: bool,
    start_gate: _ProcessBarrier,
    create_gate: _ProcessBarrier,
    result_queue: _ResultQueue,
) -> None:
    async def scenario() -> tuple[str, bool]:
        repository = _RaceWideningRepository(
            vault_path=vault_path,
            create_gate=create_gate,
        )
        service = MemoryCompactService(repository=repository)
        compact = await service.create(_payload(reverse_sources=reverse_sources))
        return compact.id, compact.deduplicated

    start_gate.wait(timeout=10)
    result_queue.put(anyio.run(scenario))


def test_identical_compact_creation_is_atomic_across_processes(
    tmp_path: Path,
) -> None:
    """Concurrent services should create one note and replay one stable id."""
    vault_path = tmp_path / "vault"
    process_context = multiprocessing.get_context("spawn")
    start_gate = process_context.Barrier(2)
    create_gate = process_context.Barrier(2)
    result_queue = process_context.Queue()
    processes = [
        process_context.Process(
            target=_create_in_process,
            args=(
                str(vault_path),
                reverse_sources,
                start_gate,
                create_gate,
                result_queue,
            ),
        )
        for reverse_sources in (False, True)
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
        assert [process.exitcode for process in processes] == [0, 0]
        results = [result_queue.get(timeout=5) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()

    compact_ids = {compact_id for compact_id, _deduplicated in results}
    deduplicated_results = sorted(deduplicated for _compact_id, deduplicated in results)
    note_paths = list((vault_path / "Alexandria" / "Memory Compacts").rglob("*.md"))

    assert len(compact_ids) == 1
    assert deduplicated_results == [False, True]
    assert len(note_paths) == 1
    assert next(iter(compact_ids)) in note_paths[0].read_text(encoding="utf-8")


def test_identical_compact_creation_completes_at_high_same_loop_concurrency(
    tmp_path: Path,
) -> None:
    """Contended creation should not starve canonical repository I/O."""
    vault_path = tmp_path / "vault"

    async def scenario() -> list[MemoryCompact]:
        services = [
            MemoryCompactService(
                repository=ObsidianMemoryCompactRepository(
                    vault_path=vault_path,
                    relative_dir="Alexandria/Memory Compacts",
                )
            )
            for _ in range(64)
        ]
        async with asyncio.timeout(20):
            return await asyncio.gather(
                *(
                    service.create(_payload(reverse_sources=False))
                    for service in services
                )
            )

    results = anyio.run(scenario)
    compact_ids = {compact.id for compact in results}
    note_paths = list((vault_path / "Alexandria" / "Memory Compacts").rglob("*.md"))

    assert len(compact_ids) == 1
    assert sum(not compact.deduplicated for compact in results) == 1
    assert len(note_paths) == 1
    assert next(iter(compact_ids)) in note_paths[0].read_text(encoding="utf-8")


def test_creation_lock_closes_descriptor_after_repeated_acquisition_cancellation(
    tmp_path: Path,
) -> None:
    """Repeated cancellation must not orphan a descriptor opened in a worker."""

    async def scenario() -> tuple[int, bool, bool, bool]:
        lock = _DelayedDescriptorOpeningLock(vault_path=tmp_path / "vault")

        async def acquire() -> None:
            async with lock.hold():
                pytest.fail("cancelled acquisition unexpectedly entered the guard")

        acquiring_task = asyncio.create_task(acquire())
        assert await asyncio.to_thread(lock.open_started.wait, 2)
        assert acquiring_task.cancel()
        await asyncio.sleep(0)
        assert acquiring_task.cancel()
        lock.allow_open.set()
        assert await asyncio.to_thread(lock.open_finished.wait, 2)

        try:
            await acquiring_task
        except asyncio.CancelledError:
            cancellation_propagated = True
        else:
            cancellation_propagated = False

        descriptor = lock.opened_descriptors[0]
        try:
            os.fstat(descriptor)
        except OSError as error:
            assert error.errno == errno.EBADF
            descriptor_still_open = False
        else:
            descriptor_still_open = True

        lock_reacquired = False
        try:
            async with asyncio.timeout(2):
                async with MemoryCompactCreationLock(
                    vault_path=tmp_path / "vault",
                    relative_dir="Alexandria/Memory Compacts",
                ).hold():
                    lock_reacquired = True
        finally:
            if descriptor_still_open:
                os.close(descriptor)

        return (
            len(lock.opened_descriptors),
            descriptor_still_open,
            lock_reacquired,
            cancellation_propagated,
        )

    opened, still_open, reacquired, cancellation_propagated = anyio.run(scenario)

    assert opened == 1
    assert not still_open
    assert reacquired
    assert cancellation_propagated


def test_creation_guard_waits_for_cancelled_persistence_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation must not release creation_guard before persistence finishes."""
    worker_started = Event()
    allow_worker_finish = Event()
    worker_done = Event()
    competing_worker_started = Event()
    call_count_lock = Lock()
    call_count = 0
    persist_created_compact = memory_compact_repository_module._persist_created_compact

    def delayed_persist_created_compact(
        store: MemoryCompactNoteStore,
        compact: MemoryCompact,
    ) -> None:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            worker_started.set()
        else:
            competing_worker_started.set()
        if not allow_worker_finish.wait(timeout=5):
            raise TimeoutError("canonical-persistence test gate was not released")
        persist_created_compact(store, compact)
        if current_call == 1:
            worker_done.set()

    monkeypatch.setattr(
        memory_compact_repository_module,
        "_persist_created_compact",
        delayed_persist_created_compact,
    )

    async def scenario() -> tuple[bool, bool, bool, int, int, bool]:
        vault_path = tmp_path / "vault"
        owner_service = MemoryCompactService(
            repository=ObsidianMemoryCompactRepository(
                vault_path=vault_path,
                relative_dir="Alexandria/Memory Compacts",
            )
        )
        competing_service = MemoryCompactService(
            repository=ObsidianMemoryCompactRepository(
                vault_path=vault_path,
                relative_dir="Alexandria/Memory Compacts",
            )
        )
        owner_task = asyncio.create_task(
            owner_service.create(_payload(reverse_sources=False))
        )
        assert await asyncio.to_thread(worker_started.wait, 2)
        assert owner_task.cancel()
        await asyncio.sleep(0)
        assert owner_task.cancel()
        competing_task = asyncio.create_task(
            competing_service.create(_payload(reverse_sources=True))
        )

        try:
            competing_entered_early = await asyncio.to_thread(
                competing_worker_started.wait,
                0.5,
            )
            worker_was_done = worker_done.is_set()
            competing_was_done = competing_task.done()
        finally:
            allow_worker_finish.set()
            owner_result, competing_result = await asyncio.gather(
                owner_task,
                competing_task,
                return_exceptions=True,
            )
        note_count = len(
            list((vault_path / "Alexandria" / "Memory Compacts").rglob("*.md"))
        )

        return (
            competing_entered_early,
            worker_was_done,
            competing_was_done,
            call_count,
            note_count,
            isinstance(owner_result, asyncio.CancelledError)
            and isinstance(competing_result, MemoryCompact)
            and competing_result.deduplicated,
        )

    (
        competing_entered_early,
        worker_was_done,
        competing_was_done,
        persistence_calls,
        note_count,
        cancellation_propagated_and_competitor_deduplicated,
    ) = anyio.run(scenario)

    assert not worker_was_done
    assert not competing_entered_early
    assert not competing_was_done
    assert persistence_calls == 1
    assert note_count == 1
    assert cancellation_propagated_and_competitor_deduplicated
