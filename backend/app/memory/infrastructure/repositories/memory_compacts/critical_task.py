"""Cancellation-safe task completion for Memory Compact filesystem work."""

from __future__ import annotations

import asyncio


async def wait_for_critical_task[ResultT](
    task: asyncio.Task[ResultT],
) -> ResultT:
    """Wait for a critical task to finish before propagating cancellation.

    Args:
        task: Started task owning Memory Compact filesystem work.

    Returns:
        Result produced when no cancellation was requested.

    Raises:
        asyncio.CancelledError: After the task finishes when cancellation occurred.
    """
    cancellation_requested = False
    while True:
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancellation_requested = True
            continue
        except BaseException:
            if cancellation_requested:
                raise asyncio.CancelledError from None
            raise
        if cancellation_requested:
            raise asyncio.CancelledError
        return result
