"""Concurrency coordination for rebuildable index write operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol

from app.shared.exceptions.common_exceptions import IndexMaintenanceConflictError

type IndexLeaseMode = Literal["exclusive", "shared"]


class IndexWriteProcessLock(Protocol):
    """Cross-process shared/exclusive lease for one rebuildable index database."""

    def operation(
        self,
        wait: bool,
        shared: bool,
    ) -> AbstractAsyncContextManager[None]:
        """Return one cross-process lease context.

        Args:
            wait: Whether the caller should wait for another process to release.
            shared: Whether compatible short writers may enter concurrently.

        Returns:
            Async context manager that owns the cross-process lease.
        """


@dataclass(slots=True)
class _TaskLease:
    mode: IndexLeaseMode
    name: str
    depth: int = 1


class IndexMaintenanceCoordinator:
    """Coordinate short writers with exclusive maintenance operations.

    The coordinator may enable concurrent PostgreSQL
    short writers while rebuild, reindex, and graph-maintenance operations acquire
    an exclusive lane. Exclusive waiters are preferred so a steady write stream
    cannot starve maintenance. One asyncio task may re-enter its current lease, but
    a shared lease may not be upgraded to exclusive inside the same task.
    """

    def __init__(
        self,
        process_lock: IndexWriteProcessLock | None = None,
        allow_concurrent_writes: bool = False,
    ) -> None:
        """Initialize the local and cross-process coordination lanes.

        Args:
            process_lock: Optional database-specific cross-process lock.
            allow_concurrent_writes: Whether short writers use compatible shared locks.
        """
        self._condition = asyncio.Condition()
        self._process_lock = process_lock
        self._allow_concurrent_writes = allow_concurrent_writes
        self._task_leases: dict[int, _TaskLease] = {}
        self._exclusive_owner_task_id: int | None = None
        self._active_shared_count = 0
        self._waiting_exclusive_count = 0
        self._active_operation: str | None = None

    @property
    def active_operation(self) -> str | None:
        """Return the exclusive or oldest active operation name.

        Returns:
            Active operation name, or ``None`` when the lanes are idle.
        """
        if self._active_operation is not None:
            return self._active_operation
        return next(
            (lease.name for lease in self._task_leases.values()),
            None,
        )

    @asynccontextmanager
    async def operation(
        self,
        name: str,
        wait: bool = False,
    ) -> AsyncIterator[None]:
        """Enter one exclusive maintenance operation.

        Args:
            name: Stable name for the requested maintenance operation.
            wait: Queue behind active work instead of failing fast.

        Yields:
            Control while the current task owns the exclusive lane.
        """
        async with self._lease(name=name, wait=wait, requested_mode="exclusive"):
            yield

    @asynccontextmanager
    async def write_operation(self, name: str) -> AsyncIterator[None]:
        """Enter one short write operation.

        Args:
            name: Stable name for the canonical or index write.

        Yields:
            Control while the write owns a compatible shared or serialized lane.
        """
        requested_mode: IndexLeaseMode = (
            "shared" if self._allow_concurrent_writes else "exclusive"
        )
        async with self._lease(name=name, wait=True, requested_mode=requested_mode):
            yield

    @asynccontextmanager
    async def _lease(
        self,
        name: str,
        wait: bool,
        requested_mode: IndexLeaseMode,
    ) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("index maintenance requires an active asyncio task")
        task_id = id(task)
        outermost, effective_mode = await self._acquire_local(
            task_id=task_id,
            name=name,
            wait=wait,
            requested_mode=requested_mode,
        )
        try:
            if not outermost or self._process_lock is None:
                yield
                return
            try:
                async with self._process_lock.operation(
                    wait=wait,
                    shared=effective_mode == "shared",
                ):
                    yield
            except BlockingIOError as exc:
                raise IndexMaintenanceConflictError(
                    f"index maintenance '{name}' cannot start because another "
                    "process owns an incompatible index lease"
                ) from exc
        finally:
            await self._release_local(task_id)

    async def _acquire_local(
        self,
        task_id: int,
        name: str,
        wait: bool,
        requested_mode: IndexLeaseMode,
    ) -> tuple[bool, IndexLeaseMode]:
        async with self._condition:
            existing = self._task_leases.get(task_id)
            if existing is not None:
                if existing.mode == "shared" and requested_mode == "exclusive":
                    raise RuntimeError(
                        "index lease cannot upgrade from shared to exclusive; "
                        "enter the outer operation as exclusive"
                    )
                existing.depth += 1
                return False, existing.mode

            if requested_mode == "shared":
                await self._acquire_shared(task_id=task_id, name=name)
                return True, "shared"

            await self._acquire_exclusive(task_id=task_id, name=name, wait=wait)
            return True, "exclusive"

    async def _acquire_shared(self, task_id: int, name: str) -> None:
        while (
            self._exclusive_owner_task_id is not None
            or self._waiting_exclusive_count > 0
        ):
            await self._condition.wait()
        self._task_leases[task_id] = _TaskLease(mode="shared", name=name)
        self._active_shared_count += 1

    async def _acquire_exclusive(
        self,
        task_id: int,
        name: str,
        wait: bool,
    ) -> None:
        if not self._exclusive_available():
            if not wait:
                active = self.active_operation or "concurrent index writes"
                raise IndexMaintenanceConflictError(
                    f"index maintenance '{name}' cannot start while '{active}' is active"
                )
            self._waiting_exclusive_count += 1
            try:
                while not self._exclusive_available():
                    await self._condition.wait()
            finally:
                self._waiting_exclusive_count -= 1
        self._task_leases[task_id] = _TaskLease(mode="exclusive", name=name)
        self._exclusive_owner_task_id = task_id
        self._active_operation = name

    def _exclusive_available(self) -> bool:
        return self._exclusive_owner_task_id is None and self._active_shared_count == 0

    async def _release_local(self, task_id: int) -> None:
        async with self._condition:
            lease = self._task_leases.get(task_id)
            if lease is None:
                raise RuntimeError("index lease release without matching acquisition")
            lease.depth -= 1
            if lease.depth > 0:
                return
            del self._task_leases[task_id]
            if lease.mode == "exclusive":
                self._exclusive_owner_task_id = None
                self._active_operation = None
            else:
                self._active_shared_count -= 1
            self._condition.notify_all()
