"""Typed checkpoint I/O and checkpoint values for memory cycles."""

from __future__ import annotations

from functools import partial
from typing import Final, Protocol

from pydantic import TypeAdapter

from app.memory.domain.entities.memory_cycle import (
    MemoryCycleCheckpoint,
    MemoryCycleResult,
)
from app.memory.domain.event_enum.memory_cycle_enums import MemoryCycleCheckpointState
from app.shared.infrastructure.critical_task import run_critical_sync


class MemoryCycleCheckpointStore(Protocol):
    """Typed blocking checkpoint surface owned by the report-bundle run store."""

    def load_typed(
        self,
        idempotency_key: str,
        adapter: TypeAdapter[MemoryCycleCheckpoint],
    ) -> MemoryCycleCheckpoint | None:
        """Load one typed cycle checkpoint.

        Args:
            idempotency_key: Namespaced checkpoint key.
            adapter: Pydantic TypeAdapter for checkpoint deserialization.

        Returns:
            Loaded checkpoint record, or None if not found.
        """

    def save_typed(
        self,
        idempotency_key: str,
        record: MemoryCycleCheckpoint,
        adapter: TypeAdapter[MemoryCycleCheckpoint],
    ) -> None:
        """Atomically save one typed cycle checkpoint.

        Args:
            idempotency_key: Namespaced checkpoint key.
            record: Checkpoint record to persist.
            adapter: Pydantic TypeAdapter for checkpoint serialization.
        """


_CHECKPOINT_ADAPTER: Final[TypeAdapter[MemoryCycleCheckpoint]] = TypeAdapter(
    MemoryCycleCheckpoint
)
_CHECKPOINT_PREFIX: Final[str] = "memory-cycle:"


class MemoryCycleCheckpointAdapter:
    """Bridge typed cycle checkpoints to the existing report-bundle run store."""

    def __init__(self, checkpoint_store: MemoryCycleCheckpointStore) -> None:
        """Retain the existing durable checkpoint authority.

        Args:
            checkpoint_store: Underlying blocking checkpoint store.
        """
        self._checkpoint_store = checkpoint_store

    async def load(self, idempotency_key: str) -> MemoryCycleCheckpoint | None:
        """Read typed run-store state through the bounded blocking bridge.

        Args:
            idempotency_key: Caller idempotency key for the cycle.

        Returns:
            Persisted cycle checkpoint if present, otherwise None.
        """
        return await run_critical_sync(
            partial(
                self._checkpoint_store.load_typed,
                _checkpoint_key(idempotency_key),
                _CHECKPOINT_ADAPTER,
            )
        )

    async def save(self, checkpoint: MemoryCycleCheckpoint) -> None:
        """Persist one typed checkpoint atomically outside the canonical note root.

        Args:
            checkpoint: Cycle checkpoint state to persist.
        """
        await run_critical_sync(
            partial(
                self._checkpoint_store.save_typed,
                _checkpoint_key(checkpoint.idempotency_key),
                checkpoint,
                _CHECKPOINT_ADAPTER,
            )
        )


def _checkpoint_key(idempotency_key: str) -> str:
    """Namespace cycle checkpoints in the existing run-store authority.

    Args:
        idempotency_key: Raw cycle idempotency key.

    Returns:
        Namespaced checkpoint storage key.
    """
    return _CHECKPOINT_PREFIX + idempotency_key.strip()


def checkpoint_for(
    result: MemoryCycleResult,
    state: MemoryCycleCheckpointState,
    child_plan_ids: tuple[str, ...],
    child_result_ids: tuple[str | None, ...],
    compact_id: str | None,
) -> MemoryCycleCheckpoint:
    """Build an admitted checkpoint with explicit durable child identity.

    Args:
        result: Current aggregate cycle result snapshot.
        state: Lifecycle state of the checkpoint.
        child_plan_ids: Persisted child reconciliation plan identifiers.
        child_result_ids: Persisted child reconciliation result identifiers.
        compact_id: Persisted compact identifier when created.

    Returns:
        Constructed MemoryCycleCheckpoint record.
    """
    return MemoryCycleCheckpoint(
        idempotency_key=result.idempotency_key,
        plan_hash=result.plan_hash,
        state=state,
        result=result,
        source_snapshot=result.source_snapshot,
        compact_id=compact_id,
        child_plan_ids=child_plan_ids,
        child_result_ids=child_result_ids,
    )


def checkpoint_for_result(
    result: MemoryCycleResult,
    state: MemoryCycleCheckpointState,
) -> MemoryCycleCheckpoint:
    """Build a completed/partial checkpoint from aggregate output evidence.

    Args:
        result: Aggregate cycle result containing child outcomes and compact change.
        state: Lifecycle state of the checkpoint.

    Returns:
        Constructed MemoryCycleCheckpoint record.
    """
    child_plan_ids = tuple(
        item.plan_id for item in result.child_outcomes if item.plan_id is not None
    )
    child_result_ids = tuple(
        item.result_id for item in result.child_outcomes if item.plan_id is not None
    )
    compact_id = (
        None if result.compact_change is None else result.compact_change.compact_id
    )
    return checkpoint_for(
        result=result,
        state=state,
        child_plan_ids=child_plan_ids,
        child_result_ids=child_result_ids,
        compact_id=compact_id,
    )
