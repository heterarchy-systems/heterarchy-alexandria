"""Provider-mode regression contracts for Context service construction."""

from __future__ import annotations

from inspect import isawaitable
from typing import cast

import anyio
from app.container import create_graph_signal_provider
from app.main import app
from app.obsidian.domain.repositories.obsidian_graph_projection_repository import (
    IObsidianGraphProjectionRepository,
)
from app.platform.config.app_config import AppConfig
from dependency_injector import providers


async def _exercise_synchronous_context_service_override() -> None:
    provider = app.state.container.memory.context_service
    replacement = object()

    assert provider.is_async_mode_enabled()
    with provider.override(providers.Object(replacement)):
        candidate = provider()
        assert isawaitable(candidate)
        assert await candidate is replacement

    assert provider.is_async_mode_enabled()


def test_context_service_provider_retains_async_mode_after_sync_override() -> None:
    """A synchronous test override must not disable async dependency resolution."""
    anyio.run(_exercise_synchronous_context_service_override)


def test_embedding_provider_is_process_scoped_singleton() -> None:
    """The expensive local embedding model must be reused across Context services."""
    assert isinstance(
        app.state.container.memory.embedding_provider, providers.Singleton
    )


def test_disabled_graph_mode_discards_even_a_supplied_projection_repository() -> None:
    """Disabled mode must never construct a Context graph evidence provider."""
    repository = cast(IObsidianGraphProjectionRepository, object())

    provider = create_graph_signal_provider(
        config=AppConfig(_env_file=None, graph_read_model="disabled"),
        repository=repository,
    )

    assert provider is None
