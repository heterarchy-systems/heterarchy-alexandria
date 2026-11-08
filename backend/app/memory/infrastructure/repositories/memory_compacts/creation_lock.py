"""Cross-process creation lock for canonical Memory Compact notes."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path

from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_path_policy import (
    resolve_base_dir,
)
from app.shared.infrastructure.critical_task import run_critical_sync

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
    async def hold(self) -> AsyncGenerator[None]:
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
        """Release one acquisition, keeping the lock held while nested.

        Raises:
            RuntimeError: When lock release is attempted without a held descriptor.
        """
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
        await run_critical_sync(lambda: _release(descriptor))

    async def _acquire_without_cancellation_leak(self) -> int:
        """Open and lock the creation lock file without leaking descriptors on cancellation.

        Returns:
            Locked OS file descriptor for the creation lock file.

        Raises:
            asyncio.CancelledError: If the task is cancelled while opening or waiting for the lock.
            BaseException: If locking fails after opening the file descriptor.
        """
        descriptor: int | None = None

        def open_descriptor() -> int:
            """Open the lock file descriptor and capture it for cancellation cleanup.

            Returns:
                Opened OS file descriptor.
            """
            nonlocal descriptor
            descriptor = self._open_descriptor()
            return descriptor

        try:
            descriptor = await run_critical_sync(open_descriptor)
        except asyncio.CancelledError:
            if descriptor is not None:
                os.close(descriptor)
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
        """Create parent directories and open the lock file descriptor.

        Returns:
            Opened read-write OS file descriptor.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        return os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)


def _release(descriptor: int) -> None:
    """Unlock and close a held creation lock file descriptor.

    Args:
        descriptor: OS file descriptor to unlock and close.
    """
    try:
        flock(descriptor, LOCK_UN)
    finally:
        os.close(descriptor)
