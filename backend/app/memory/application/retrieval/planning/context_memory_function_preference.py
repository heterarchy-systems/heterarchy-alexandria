"""Deterministic soft preference for functional memory roles."""

from __future__ import annotations

from collections.abc import Sequence

from app.memory.domain.entities.context_read_models import ContextSearchMatch
from app.memory.domain.event_enum.context_enums import MemoryFunction
from app.shared.types.types_convert_utils import enum_value


def validated_memory_functions(
    preferred: Sequence[MemoryFunction] | None,
) -> list[MemoryFunction] | None:
    """Normalize optional functional-memory preference values at the planning boundary.

    Args:
        preferred: Optional caller-provided functional-memory preference order.

    Returns:
        Validated ordered preferences, or None when no preference is requested.
    """
    if not preferred:
        return None
    return [
        enum_value(memory_function, MemoryFunction, "prefer_memory_functions")
        for memory_function in preferred
    ]


def prefer_memory_function_matches(
    matches: Sequence[ContextSearchMatch],
    preferred: Sequence[MemoryFunction] | None,
) -> list[ContextSearchMatch]:
    """Return all matches with explicitly preferred memory roles stably promoted.

    This policy does not mutate retrieval scores and never removes a match. Each
    preferred role forms one stable bucket in caller-provided priority order;
    unclassified and non-preferred memories retain their original relative order.

    Args:
        matches: Primary retrieval results in deterministic score order.
        preferred: Explicit functional-role preference ordered by priority.

    Returns:
        Reordered matches preserving membership and score values.
    """
    if not matches or not preferred:
        return list(matches)
    priority = {
        memory_function: index for index, memory_function in enumerate(preferred)
    }
    fallback_priority = len(priority)
    return [
        match
        for _, match in sorted(
            enumerate(matches),
            key=lambda item: (
                priority.get(item[1].context.memory_function, fallback_priority),
                item[0],
            ),
        )
    ]
