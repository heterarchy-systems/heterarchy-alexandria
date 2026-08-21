"""Type alias normalization for Obsidian librarian request schemas."""

from __future__ import annotations

from app.obsidian.domain.obsidian_note_type_aliases import alexandria_note_type_input
from app.shared.types.extra_types import JSONValue


def preferred_note_type_input(value: JSONValue) -> JSONValue:
    """Normalize agent-facing note type aliases before enum validation.

    Args:
        value: Raw note type filter item supplied by an MCP or HTTP caller.

    Returns:
        Normalized note type value for downstream enum validation.
    """
    return alexandria_note_type_input(value)
