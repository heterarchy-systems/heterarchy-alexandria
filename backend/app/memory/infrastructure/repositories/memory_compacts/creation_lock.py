"""Cross-process creation lock for canonical Memory Compact notes."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path

from asyncer import asyncify

from app.memory.infrastructure.repositories.memory_compacts.critical_task import (
    wait_for_critical_task,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_path_policy import (
    resolve_base_dir,
)

_CREATION_LOCK_NAME = ".memory-compact-creation.lock"
_LOCK_RETRY_DELAY_SECONDS = 0.01


class MemoryCompactCreationLock:
    """Serialize Memory Compact check-and-create sections across processes.

    The lock is re-entrant for the owning asyncio task: a nested ``hold()``
    inside the same task (for example an application-level critical section
    that itself calls the compact creation path) reuses the held descriptor
    instead of deadlocking on a second conflicting flock. Different tasks in
    the same process, and other processes, still contend on the filesystem
    lock exactly as before.
    """

    def __init__(self, vault_path: str | Path, relative_dir: str | Path) -> None:
        """Resolve the concept-owned lock beside canonical compact notes.

        Args:
            vault_path: Obsidian vault root path.
            relative_dir: Relative folder for Memory Compact notes.
        """
        base_dir = resolve_base_dir(vault_path, relative_dir)
        self._path = base_dir / _CREATION_LOCK_NAME
        self._owner_task: asyncio.Task[None] | None = None
        self._descriptor: int | None = None
        self._depth = 0

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        """Acquire the filesystem lock without blocking the event loop.

        Yields:
            Control while this process owns the creation critical section.
        """
        await self._acquire()
        try:
            yield
        finally:
            await self._release_one()

    async def _acquire(self) -> None:
        """Acquire or re-enter the critical section for the current task.

        Raises:
            RuntimeError: When a foreign task attempts to re-enter while the
                lock is held without an owning descriptor.
        """
        current = asyncio.current_task()
        if current is None:
            raise RuntimeError(
                "the creation lock must be held inside a running asyncio task"
            )
        if current is self._owner_task:
            self._depth += 1
            return
        descriptor = await self._acquire_without_cancellation_leak()
        self._descriptor = descriptor
        self._owner_task = current
        self._depth = 1

    async def _release_one(self) -> None:
        """Release one acquisition, keeping the lock held while nested."""
        self._depth -= 1
        if self._depth > 0:
            return
        descriptor = self._descriptor
        self._descriptor = None
        self._owner_task = None
        self._depth = 0
        if descriptor is None:
            raise RuntimeError(
                "creation lock release attempted without a held descriptor"
            )
        release_task = asyncio.ensure_future(asyncify(_release)(descriptor))
        await wait_for_critical_task(release_task)

    async def _acquire_without_cancellation_leak(self) -> int:
        """Acquire without cancellation leak.

        Returns:
            int result produced by acquire without cancellation leak.
        """
        open_task = asyncio.ensure_future(asyncify(self._open_descriptor)())
        try:
            descriptor = await wait_for_critical_task(open_task)
        except asyncio.CancelledError:
            if (
                open_task.done()
                and not open_task.cancelled()
                and open_task.exception() is None
            ):
                os.close(open_task.result())
            raise
        try:
            while True:
                try:
                    flock(descriptor, LOCK_EX | LOCK_NB)
                    return descriptor
                except BlockingIOError:
                    await asyncio.sleep(_LOCK_RETRY_DELAY_SECONDS)
        except BaseException:
            os.close(descriptor)
            raise

    def _open_descriptor(self) -> int:
        """Open descriptor.

        Returns:
            int result produced by open descriptor.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        return os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)


def _release(descriptor: int) -> None:
    """Execute release.

    Args:
        descriptor: Descriptor used by this operation.
    """
    try:
        flock(descriptor, LOCK_UN)
    finally:
        os.close(descriptor)
