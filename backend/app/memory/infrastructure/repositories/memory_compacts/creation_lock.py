"""Cross-process creation lock for canonical Memory Compact notes."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path

from app.memory.infrastructure.repositories.memory_compacts.critical_task import (
    wait_for_critical_task,
)
from app.memory.infrastructure.repositories.memory_compacts.obsidian_markdown_path_policy import (
    resolve_base_dir,
)

_CREATION_LOCK_NAME = ".memory-compact-creation.lock"
_LOCK_RETRY_DELAY_SECONDS = 0.01


class MemoryCompactCreationLock:
    """Serialize Memory Compact check-and-create sections across processes."""

    def __init__(self, *, vault_path: str | Path, relative_dir: str | Path) -> None:
        """Resolve the concept-owned lock beside canonical compact notes.

        Args:
            vault_path: Obsidian vault root path.
            relative_dir: Relative folder for Memory Compact notes.
        """
        base_dir = resolve_base_dir(vault_path, relative_dir)
        self._path = base_dir / _CREATION_LOCK_NAME

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        """Acquire the filesystem lock without blocking the event loop.

        Yields:
            Control while this process owns the creation critical section.
        """
        descriptor = await self._acquire_without_cancellation_leak()
        try:
            yield
        finally:
            release_task = asyncio.create_task(asyncio.to_thread(_release, descriptor))
            await wait_for_critical_task(release_task)

    async def _acquire_without_cancellation_leak(self) -> int:
        open_task = asyncio.create_task(asyncio.to_thread(self._open_descriptor))
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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        return os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)


def _release(descriptor: int) -> None:
    try:
        flock(descriptor, LOCK_UN)
    finally:
        os.close(descriptor)
