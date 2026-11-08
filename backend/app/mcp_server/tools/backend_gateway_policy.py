"""Shared bounds and payload normalization for MCP backend gateways."""

from __future__ import annotations

from urllib.parse import quote

from app.memory.domain.event_enum.context_enums import RagStrategy
from app.shared.types.extra_types import JSONObject

DEFAULT_CONTEXT_SEARCH_LIMIT = 5
DEFAULT_CONTEXT_SEARCH_STRATEGY = RagStrategy.HYBRID
DEFAULT_SOURCE_AGENT = "Hermes"


def bounded_search_limit(limit: int) -> int:
    """Clamp a search result limit to the supported MCP gateway range.

    Args:
        limit: Requested maximum number of search results.

    Returns:
        Search result limit clamped between 1 and 50.
    """
    bounded_limit = min(max(limit, 1), 50)
    return bounded_limit


def path_segment(value: str) -> str:
    """Return one URL-safe path segment.

    Args:
        value: Untrusted path parameter.

    Returns:
        Percent-encoded path segment safe for backend URL construction.
    """
    return quote(value, safe="")


def required_recovery_run_idempotency_key(value: str | None) -> str:
    """Validate and normalize a required recovery apply idempotency key.

    Args:
        value: Candidate idempotency key supplied by the caller.

    Returns:
        Stripped non-empty idempotency key.

    Raises:
        ValueError: If the key is missing or blank.
    """
    if value is None or not value.strip():
        raise ValueError("idempotency_key is required when recovery dry_run is false")
    return value.strip()


def items_or_empty(items: list[str] | None) -> list[str]:
    """Normalize optional bullet lists for compact handoff payloads.

    Args:
        items: Caller-provided list or omitted value.

    Returns:
        Original list or an empty list when omitted.
    """
    if items is None:
        return []
    return items


def move_payloads(moves: list[dict[str, str]]) -> list[JSONObject]:
    """Normalize vault move descriptors into backend JSON payloads.

    Args:
        moves: Source, destination, and reason dictionaries for each move.

    Returns:
        Normalized JSON payload dictionaries for backend move endpoints.
    """
    return [
        {
            "source_path": move["source_path"],
            "destination_path": move["destination_path"],
            "reason": move["reason"],
        }
        for move in moves
    ]
