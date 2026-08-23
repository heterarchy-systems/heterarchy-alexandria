"""PostgreSQL advisory lock for cross-process index coordination."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.shared.application.index_maintenance_coordinator import IndexWriteProcessLock


def postgres_advisory_lock_key(namespace: str) -> int:
    """Derive one stable signed 64-bit PostgreSQL advisory lock key.

    Args:
        namespace: Stable application-level lock namespace.

    Returns:
        Signed 64-bit integer accepted by PostgreSQL advisory lock functions.
    """
    digest = sha256(namespace.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class PostgresAdvisoryLock(IndexWriteProcessLock):
    """Hold shared or exclusive session-level advisory locks on one connection."""

    def __init__(
        self,
        engine: AsyncEngine,
        namespace: str,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        """Initialize a PostgreSQL advisory lock namespace.

        Args:
            engine: Async engine that owns the PostgreSQL connection pool.
            namespace: Stable lock namespace shared by all application processes.
            poll_interval_seconds: Delay between nonblocking attempts while queued.
        """
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        self._engine = engine
        self._key = postgres_advisory_lock_key(namespace)
        self._poll_interval_seconds = poll_interval_seconds

    @asynccontextmanager
    async def operation(
        self,
        wait: bool,
        shared: bool,
    ) -> AsyncIterator[None]:
        """Acquire and release one session-level advisory lock.

        Args:
            wait: Whether to queue until an incompatible holder releases.
            shared: Whether compatible short writers may enter concurrently.

        Yields:
            Control while the dedicated connection owns the advisory lock.
        """
        try_function = (
            func.pg_try_advisory_lock_shared if shared else func.pg_try_advisory_lock
        )
        async with self._engine.connect() as raw_connection:
            connection = await raw_connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            acquired = False
            if wait:
                acquired = await self._wait_until_acquired(
                    connection=connection,
                    shared=shared,
                )
            else:
                acquired = await connection.scalar(select(try_function(self._key)))
                if acquired is not True:
                    raise BlockingIOError("PostgreSQL advisory lock is already held")
            try:
                yield
            finally:
                if acquired:
                    cleanup_task = asyncio.create_task(
                        self._release_or_invalidate(
                            raw_connection=raw_connection,
                            connection=connection,
                            shared=shared,
                        ),
                        name="postgres-advisory-lock-release",
                    )
                    try:
                        await asyncio.shield(cleanup_task)
                    except asyncio.CancelledError:
                        await cleanup_task
                        raise

    async def _wait_until_acquired(
        self,
        connection: AsyncConnection,
        shared: bool,
    ) -> bool:
        """Poll for a session lock without opening a transaction or long statement.

        ``pg_advisory_lock`` would inherit statement, command, and lock timeouts.
        Short ``pg_try_advisory_lock`` calls preserve those protections while the
        application controls the bounded polling interval on an AUTOCOMMIT session.

        Args:
            connection: Connection used by this operation.
            shared: Shared used by this operation.

        Returns:
            ``True`` after the current session acquires the requested lock.
        """
        try_function = (
            func.pg_try_advisory_lock_shared if shared else func.pg_try_advisory_lock
        )
        while True:
            acquired = await connection.scalar(select(try_function(self._key)))
            if acquired is True:
                return True
            await asyncio.sleep(self._poll_interval_seconds)

    async def _release_or_invalidate(
        self,
        raw_connection: AsyncConnection,
        connection: AsyncConnection,
        shared: bool,
    ) -> None:
        """Release the session lock or discard the physical connection.

        Session-level advisory locks survive transaction rollback. If cleanup is
        interrupted or PostgreSQL reports an unmatched release, the underlying
        connection must not return to the pool with a live lock.

        Args:
            raw_connection: Raw connection used by this operation.
            connection: Connection used by this operation.
            shared: Shared used by this operation.
        """
        unlock_function = (
            func.pg_advisory_unlock_shared if shared else func.pg_advisory_unlock
        )
        try:
            released = await connection.scalar(select(unlock_function(self._key)))
            if released is not True:
                raise RuntimeError("PostgreSQL advisory lock release failed")
        except (Exception, asyncio.CancelledError):
            await raw_connection.invalidate()
            raise
