"""PostgreSQL advisory lock adapter contracts."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import anyio
import pytest
from app.shared.infrastructure.postgres_advisory_lock import (
    PostgresAdvisoryLock,
    postgres_advisory_lock_key,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql import Executable


class _RecordingConnection:
    def __init__(self, scalar_results: list[bool]) -> None:
        self.scalar_results = deque(scalar_results)
        self.execution_options_calls: list[dict[str, str]] = []
        self.execute_statements: list[str] = []
        self.scalar_statements: list[str] = []
        self.invalidate_calls = 0

    async def execution_options(self, **options: str) -> _RecordingConnection:
        self.execution_options_calls.append(options)
        return self

    async def execute(self, statement: Executable) -> None:
        self.execute_statements.append(str(statement))

    async def scalar(self, statement: Executable) -> bool:
        self.scalar_statements.append(str(statement))
        return self.scalar_results.popleft()

    async def invalidate(self) -> None:
        self.invalidate_calls += 1


class _BlockingUnlockConnection(_RecordingConnection):
    def __init__(self) -> None:
        super().__init__([True])
        self.unlock_started = anyio.Event()
        self.allow_unlock = anyio.Event()

    async def scalar(self, statement: Executable) -> bool:
        statement_text = str(statement)
        self.scalar_statements.append(statement_text)
        if "pg_try_advisory_lock" in statement_text:
            return True
        if "pg_advisory_unlock" in statement_text:
            self.unlock_started.set()
            await self.allow_unlock.wait()
            return True
        raise AssertionError(f"unexpected scalar statement: {statement_text}")


class _RecordingEngine:
    def __init__(self, connection: _RecordingConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[_RecordingConnection]:
        yield self.connection


def test_advisory_lock_key_is_stable_and_namespaced() -> None:
    """Stable namespaces should map to stable but distinct signed lock keys."""
    first = postgres_advisory_lock_key("heterarchy-alexandria:index-maintenance")
    repeated = postgres_advisory_lock_key("heterarchy-alexandria:index-maintenance")
    other = postgres_advisory_lock_key("heterarchy-alexandria:scheduler")

    assert first == repeated
    assert first != other
    assert -(2**63) <= first < 2**63


def test_waiting_shared_lock_uses_blocking_autocommit_session_lock() -> None:
    """Queued writers should use short AUTOCOMMIT probes, not a long SQL wait."""

    async def scenario() -> _RecordingConnection:
        connection = _RecordingConnection([False, True, True])
        engine = cast(AsyncEngine, _RecordingEngine(connection))
        lock = PostgresAdvisoryLock(
            engine,
            namespace="shared-lock",
            poll_interval_seconds=0,
        )

        async with lock.operation(wait=True, shared=True):
            pass
        return connection

    connection = anyio.run(scenario)

    assert connection.execution_options_calls == [{"isolation_level": "AUTOCOMMIT"}]
    assert connection.execute_statements == []
    assert len(connection.scalar_statements) == 3
    assert all(
        "pg_try_advisory_lock_shared" in statement
        for statement in connection.scalar_statements[:2]
    )
    assert "pg_advisory_unlock_shared" in connection.scalar_statements[2]


def test_fail_fast_exclusive_lock_does_not_unlock_when_not_acquired() -> None:
    """A failed nonblocking attempt should report contention without false release."""

    async def scenario() -> _RecordingConnection:
        connection = _RecordingConnection([False])
        engine = cast(AsyncEngine, _RecordingEngine(connection))
        lock = PostgresAdvisoryLock(engine, namespace="exclusive-lock")

        with pytest.raises(BlockingIOError):
            async with lock.operation(wait=False, shared=False):
                raise AssertionError("contended advisory lock unexpectedly entered")
        return connection

    connection = anyio.run(scenario)

    assert len(connection.scalar_statements) == 1
    assert "pg_try_advisory_lock" in connection.scalar_statements[0]
    assert "pg_advisory_unlock" not in connection.scalar_statements[0]


def test_cancelled_owner_waits_for_shielded_advisory_unlock() -> None:
    """Cancellation must not return a still-locked session to the pool."""

    async def scenario() -> _BlockingUnlockConnection:
        connection = _BlockingUnlockConnection()
        engine = cast(AsyncEngine, _RecordingEngine(connection))
        lock = PostgresAdvisoryLock(engine, namespace="cancelled-owner")

        async def owner() -> None:
            async with lock.operation(wait=False, shared=False):
                pass

        owner_task = asyncio.create_task(owner())
        await connection.unlock_started.wait()
        owner_task.cancel()
        await anyio.sleep(0)
        assert not owner_task.done()
        connection.allow_unlock.set()
        with pytest.raises(asyncio.CancelledError):
            await owner_task
        return connection

    connection = anyio.run(scenario)

    assert connection.invalidate_calls == 0
    assert any(
        "pg_advisory_unlock" in statement for statement in connection.scalar_statements
    )


def test_failed_advisory_unlock_invalidates_the_physical_connection() -> None:
    """An unmatched release must discard the session instead of leaking its lock."""

    async def scenario() -> _RecordingConnection:
        connection = _RecordingConnection([True, False])
        engine = cast(AsyncEngine, _RecordingEngine(connection))
        lock = PostgresAdvisoryLock(engine, namespace="failed-release")

        with pytest.raises(RuntimeError, match="release failed"):
            async with lock.operation(wait=False, shared=False):
                pass
        return connection

    connection = anyio.run(scenario)

    assert connection.invalidate_calls == 1
