"""Shared bounds and payload normalization for MCP backend gateways."""

from __future__ import annotations

from urllib.parse import quote

from app.memory.domain.event_enum.context_enums import RagStrategy
from app.shared.types.extra_types import JSONObject

DEFAULT_CONTEXT_SEARCH_LIMIT = 5
DEFAULT_CONTEXT_SEARCH_STRATEGY = RagStrategy.HYBRID
DEFAULT_SOURCE_AGENT = "Hermes"
DEFAULT_CANDIDATE_AUTHOR = "Hermes"


def _bounded_packet_budget(limit: int) -> int:
    """Execute bounded packet budget.

    Args:
        limit: Maximum number of items to process or return.

    Returns:
        int result produced by bounded packet budget.
    """
    return min(max(int(limit), 1_000), 120_000)


def _bounded_source_ref_limit(limit: int) -> int:
    """Execute bounded source ref limit.

    Args:
        limit: Maximum number of items to process or return.

    Returns:
        int result produced by bounded source ref limit.
    """
    return min(max(int(limit), 1), 100)


def _bounded_search_limit(limit: int) -> int:
    """Execute bounded search limit.

    Args:
        limit: Maximum number of items to process or return.

    Returns:
        int result produced by bounded search limit.
    """
    bounded_limit = min(max(int(limit), 1), 50)
    return bounded_limit


def _path_segment(value: str) -> str:
    """Return one URL-safe path segment.

    Args:
        value: Untrusted path parameter.

    Returns:
        Percent-encoded path segment safe for backend URL construction.
    """
    return quote(value, safe="")


def _required_recovery_run_idempotency_key(value: str | None) -> str:
    """Execute required recovery run idempotency key.

    Args:
        value: Value being processed.

    Returns:
        str result produced by required recovery run idempotency key.
    """
    if value is None or not value.strip():
        raise ValueError("idempotency_key is required when recovery dry_run is false")
    return value.strip()


def _items_or_empty(items: list[str] | None) -> list[str]:
    """Normalize optional bullet lists for compact handoff payloads.

    Args:
        items: Caller-provided list or omitted value.

    Returns:
        Original list or an empty list when omitted.
    """
    if items is None:
        return []
    return items


def _evidence_items_or_empty(
    items: list[JSONObject] | None,
) -> list[JSONObject]:
    """Copy optional evidence payloads without importing an HTTP interface schema.

    Args:
        items: Caller-provided evidence item dictionaries or omitted value.

    Returns:
        Independent JSON payload copies for backend boundary validation.
    """
    if items is None:
        return []
    return [dict(item) for item in items]


def _move_payloads(moves: list[dict[str, str]]) -> list[JSONObject]:
    """Execute move payloads.

    Args:
        moves: Moves used by this operation.

    Returns:
        list[JSONObject] result produced by move payloads.
    """
    return [
        {
            "source_path": move["source_path"],
            "destination_path": move["destination_path"],
            "reason": move["reason"],
        }
        for move in moves
    ]
