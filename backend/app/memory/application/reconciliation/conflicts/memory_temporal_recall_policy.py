"""Pure temporal filtering policy for reconciliation-aware Context recall."""

from __future__ import annotations

from datetime import datetime

from app.memory.domain.entities.context_read_models import ContextRecord
from app.memory.domain.entities.memory_reconciliation import MemoryTemporalState
from app.memory.domain.event_enum.reconciliation_enums import MemoryTemporalRecallMode


def state_is_valid_at(
    state: MemoryTemporalState | None,
    context: ContextRecord,
    as_of: datetime,
) -> bool:
    """Return whether one Context was valid at the requested instant.

    Args:
        state: State.
        context: Context.
        as_of: As of.

    Returns:
        bool: Operation result.
    """
    if state is None:
        return context.created_at <= as_of
    if state.valid_from is not None and state.valid_from > as_of:
        return False
    return state.valid_to is None or as_of <= state.valid_to


def state_is_current(
    state: MemoryTemporalState | None,
    context: ContextRecord,
    now: datetime,
) -> bool:
    """Return whether one Context is the current valid memory at ``now``.

    Args:
        state: State.
        context: Context.
        now: Now.

    Returns:
        bool: Operation result.
    """
    if context.is_archived:
        return False
    if state is None:
        return context.created_at <= now
    return state.is_current and state_is_valid_at(
        state=state,
        context=context,
        as_of=now,
    )


def include_temporal_match(
    mode: MemoryTemporalRecallMode,
    state: MemoryTemporalState | None,
    context: ContextRecord,
    as_of: datetime,
    now: datetime,
) -> bool:
    """Apply the selected temporal perspective without hiding conflicts.

    Args:
        mode: Mode.
        state: State.
        context: Context.
        as_of: As of.
        now: Now.

    Returns:
        bool: Operation result.
    """
    if mode is MemoryTemporalRecallMode.ALL:
        return True
    if mode is MemoryTemporalRecallMode.HISTORICAL:
        return state_is_valid_at(state=state, context=context, as_of=as_of)
    return state_is_current(state=state, context=context, now=now)
