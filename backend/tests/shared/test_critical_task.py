"""Cancellation ownership for synchronous work on AnyIO's thread lane."""

from __future__ import annotations

import asyncio
from threading import Event

import anyio
import pytest

from app.shared.application.index_maintenance_coordinator import (
    IndexMaintenanceCoordinator,
)
from app.shared.infrastructure.critical_task import run_critical_sync


def test_repeated_raw_cancellation_waits_for_running_sync_completion() -> None:
    """Repeated direct task cancellation must not detach a running effect."""

    async def scenario() -> None:
        started = Event()
        release = Event()
        finished = Event()

        def operation() -> str:
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("running worker gate was not released")
            finished.set()
            return "complete"

        caller = asyncio.create_task(run_critical_sync(operation))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            assert caller.cancel()
            await anyio.lowlevel.checkpoint()
            assert not caller.done()
            assert caller.cancel()
            await anyio.lowlevel.checkpoint()
            assert not caller.done()

            release.set()
            with pytest.raises(asyncio.CancelledError):
                async with asyncio.timeout(3):
                    await caller
            assert finished.is_set()
        finally:
            release.set()
            if not caller.done():
                caller.cancel()
                try:
                    async with asyncio.timeout(3):
                        await caller
                except asyncio.CancelledError, TimeoutError:
                    pass

    anyio.run(scenario)


def test_raw_cancellation_waits_while_queued_on_default_thread_limiter() -> None:
    """A cancelled caller remains owned while its operation awaits capacity."""

    async def scenario() -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_capacity = limiter.total_tokens
        limiter.total_tokens = 1
        await limiter.acquire()
        started = Event()
        release = Event()
        caller: asyncio.Task[str] | None = None
        try:

            def operation() -> str:
                started.set()
                if not release.wait(timeout=2):
                    raise TimeoutError("queued worker gate was not released")
                return "complete"

            caller = asyncio.create_task(run_critical_sync(operation))
            for _ in range(3):
                if limiter.statistics().tasks_waiting:
                    break
                await anyio.lowlevel.checkpoint()
            assert limiter.statistics().tasks_waiting == 1
            assert caller.cancel()
            await anyio.lowlevel.checkpoint()
            assert not caller.done()
            assert not started.is_set()

            limiter.release()
            assert await asyncio.to_thread(started.wait, 2)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                async with asyncio.timeout(3):
                    await caller
        finally:
            release.set()
            if limiter.statistics().borrowed_tokens:
                limiter.release()
            if caller is not None and not caller.done():
                caller.cancel()
                try:
                    async with asyncio.timeout(3):
                        await caller
                except asyncio.CancelledError, TimeoutError:
                    pass
            limiter.total_tokens = original_capacity

    anyio.run(scenario)


def test_anyio_cancel_scope_drains_worker_before_scope_catches_cancellation() -> None:
    """AnyIO level cancellation is shielded only while the worker is drained."""

    async def scenario() -> None:
        started = Event()
        release = Event()
        worker_finished = Event()
        competitor_started = anyio.Event()
        competitor_acquired = anyio.Event()
        scope_exited = anyio.Event()
        scope = anyio.CancelScope()
        coordinator = IndexMaintenanceCoordinator()

        def operation() -> None:
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("cancel-scope worker gate was not released")
            worker_finished.set()

        async def competitor() -> None:
            competitor_started.set()
            async with coordinator.operation("bridge-competitor", wait=True):
                competitor_acquired.set()

        async def cancel_and_release() -> None:
            try:
                if not await asyncio.to_thread(started.wait, 2):
                    raise TimeoutError("worker did not start before cancellation")
                scope.cancel()
                await anyio.lowlevel.checkpoint()
                assert not scope_exited.is_set()
                assert not worker_finished.is_set()
                assert not competitor_acquired.is_set()
                assert coordinator.active_operation == "bridge-owner"
            finally:
                release.set()

        competitor_task: asyncio.Task[None] | None = None
        canceller: asyncio.Task[None] | None = None
        try:
            async with coordinator.operation("bridge-owner", wait=True):
                competitor_task = asyncio.create_task(competitor())
                await competitor_started.wait()
                await anyio.lowlevel.checkpoint()
                assert not competitor_acquired.is_set()

                canceller = asyncio.create_task(cancel_and_release())
                with scope:
                    await run_critical_sync(operation)
                    pytest.fail(
                        "the cancelled scope returned before propagating cancellation"
                    )

                assert worker_finished.is_set()
                scope_exited.set()
                assert not competitor_acquired.is_set()

            assert competitor_task is not None
            assert canceller is not None
            async with asyncio.timeout(3):
                await competitor_task
                await canceller
            assert scope.cancelled_caught
            assert worker_finished.is_set()
            assert scope_exited.is_set()
            assert competitor_acquired.is_set()
        finally:
            release.set()
            for task in (competitor_task, canceller):
                if task is None:
                    continue
                if not task.done():
                    task.cancel()
                try:
                    async with asyncio.timeout(3):
                        await task
                except asyncio.CancelledError, TimeoutError:
                    pass

    anyio.run(scenario)


def test_worker_failure_during_cancel_drain_is_chained() -> None:
    """A child failure remains observable when caller cancellation won first."""

    async def scenario() -> None:
        started = Event()
        release = Event()

        def operation() -> None:
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("failing worker gate was not released")
            raise ValueError("worker failed during cancellation drain")

        caller = asyncio.create_task(run_critical_sync(operation))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            assert caller.cancel()
            await anyio.lowlevel.checkpoint()
            release.set()
            with pytest.raises(asyncio.CancelledError) as raised:
                async with asyncio.timeout(3):
                    await caller
            assert isinstance(raised.value.__cause__, ValueError)
            assert str(raised.value.__cause__) == (
                "worker failed during cancellation drain"
            )
        finally:
            release.set()
            if not caller.done():
                caller.cancel()
                try:
                    async with asyncio.timeout(3):
                        await caller
                except asyncio.CancelledError, TimeoutError:
                    pass

    anyio.run(scenario)
