"""Test helpers for overriding dependency-injector providers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from app.main import app
from dependency_injector import providers

_PROVIDER_CONTAINER_BY_NAME: Final[dict[str, str]] = {
    "context_service": "memory",
    "memory_compact_service": "memory",
    "reconciliation_preview_service": "memory",
    "reconciliation_apply_service": "memory",
    "reconciliation_query_service": "memory",
    "memory_temporal_recall_service": "memory",
    "memory_compact_reconciliation_service": "memory",
    "memory_existing_reconciliation_service": "memory",
    "memory_conflict_service": "memory",
    "obsidian_service": "obsidian",
}


@contextmanager
def override_library_provider(provider_name: str, value: object) -> Iterator[None]:
    """Temporarily override one app provider for route contract tests."""
    container_name = _PROVIDER_CONTAINER_BY_NAME.get(provider_name)
    if container_name is None:
        raise ValueError(f"unsupported provider override: {provider_name}")
    root_container = app.state.container
    if container_name == "memory":
        provider = root_container.memory.providers[provider_name]
    elif container_name == "obsidian":
        provider = root_container.obsidian.providers[provider_name]
    else:
        raise ValueError(f"unsupported provider container: {container_name}")
    with provider.override(providers.Object(value)):
        yield
