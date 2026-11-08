"""Own synchronous effects until their AnyIO worker has actually completed.

There is no completion timeout: caller cancellation can be delayed while the
operation waits for shared capacity and for as long as it takes to return. This
provides graceful cancellation ownership only and cannot guarantee shutdown if
synchronous work never completes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import anyio
import anyio.to_thread


async def run_critical_sync[ResultT](operation: Callable[[], ResultT]) -> ResultT:
    """Run one sync operation through AnyIO's shared worker-thread capacity.

    The private task remains strongly held while queued and while the operation
    runs. If the caller is cancelled, wait for the worker to finish before
    propagating that cancellation. A worker failure during the drain is chained
    from the caller's cancellation so neither outcome is hidden.

    Args:
        operation: Synchronous operation to run on AnyIO's worker thread lane.

    Returns:
        The operation result when the caller is not cancelled.

    Raises:
        asyncio.CancelledError: After the worker completes when caller
            cancellation occurs.
        BaseException: Any failure raised by the worker when cancellation did
            not already win.
    """
    worker_task = asyncio.create_task(
        anyio.to_thread.run_sync(
            operation,
            abandon_on_cancel=False,
            limiter=anyio.to_thread.current_default_thread_limiter(),
        ),
        name="critical-sync-operation",
    )
    try:
        return await asyncio.shield(worker_task)
    except asyncio.CancelledError as cancellation:
        if worker_task.cancelled():
            raise

        with anyio.CancelScope(shield=True):
            while not worker_task.done():
                try:
                    await asyncio.shield(worker_task)
                except asyncio.CancelledError as repeated_cancellation:
                    if worker_task.cancelled():
                        raise cancellation from repeated_cancellation
                    # Direct Task.cancel calls still reach this task through the
                    # shielded scope; keep draining the same owned worker.
                except BaseException as worker_error:
                    raise cancellation from worker_error

            try:
                worker_task.result()
            except BaseException as worker_error:
                raise cancellation from worker_error

        raise cancellation
