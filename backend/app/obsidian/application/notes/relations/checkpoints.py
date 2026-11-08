"""Durable relation checkpoint serialization and blocking I/O."""

from __future__ import annotations

from functools import partial

import anyio
import anyio.to_thread
from pydantic import TypeAdapter

from app.obsidian.domain.entities.obsidian_relation import ObsidianRelateCheckpoint
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.infrastructure.critical_task import run_critical_sync

_CHECKPOINT_ADAPTER: TypeAdapter[ObsidianRelateCheckpoint] = TypeAdapter(
    ObsidianRelateCheckpoint
)


def open_store(
    vault_config_store: ObsidianVaultConfigStore,
) -> ObsidianReportBundleRunStore:
    """Construct the existing run store from the current managed vault.

    Args:
        vault_config_store: Existing owner of current vault configuration.

    Returns:
        Store shared with all checkpoint operations for this invocation.
    """
    return ObsidianReportBundleRunStore(vault_config_store.current().vault_path)


async def load_checkpoint(
    store: ObsidianReportBundleRunStore,
    key: str,
) -> ObsidianRelateCheckpoint | None:
    """Load a relation checkpoint through AnyIO's bounded worker lane.

    Args:
        store: Store constructed once for the caller invocation.
        key: Durable idempotency checkpoint key.

    Returns:
        Typed persisted checkpoint, or None when absent.
    """
    return await anyio.to_thread.run_sync(
        partial(store.load_typed, key, _CHECKPOINT_ADAPTER),
        limiter=anyio.to_thread.current_default_thread_limiter(),
    )


async def save_checkpoint(
    store: ObsidianReportBundleRunStore,
    key: str,
    record: ObsidianRelateCheckpoint,
) -> None:
    """Save one relation checkpoint and own the worker through completion.

    Args:
        store: Same store instance used to read this invocation's checkpoint.
        key: Durable idempotency checkpoint key.
        record: Typed checkpoint persisted in the established format.
    """
    await run_critical_sync(
        partial(
            store.save_typed,
            key,
            record,
            _CHECKPOINT_ADAPTER,
        ),
    )
