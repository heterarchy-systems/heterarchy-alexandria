"""Service protocols required by operational recovery execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import cast

from app.memory.application.contexts.records.context_service_ports import (
    ContextRecoveryPort,
)
from app.obsidian.application.service.obsidian_service_ports import ObsidianRecoveryPort

type ContextRecoveryPortFactory = Callable[
    [], ContextRecoveryPort | Awaitable[ContextRecoveryPort]
]
type ObsidianRecoveryPortFactory = Callable[
    [], ObsidianRecoveryPort | Awaitable[ObsidianRecoveryPort]
]


async def resolve_recovery_service[RecoveryServiceT](
    factory: Callable[[], RecoveryServiceT | Awaitable[RecoveryServiceT]],
) -> RecoveryServiceT:
    """Resolve a synchronous or asynchronous recovery service provider.

    Args:
        factory: Provider that constructs the service in the active DB session.

    Returns:
        Resolved recovery service instance.
    """
    candidate = factory()
    if isawaitable(candidate):
        return await cast(Awaitable[RecoveryServiceT], candidate)
    return candidate
