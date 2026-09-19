"""Typed contracts for Context reindex manifest validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.obsidian.domain.contracts.obsidian_contracts import ObsidianNoteIndex
from app.obsidian.domain.event_enum.obsidian_enums import AlexandriaNoteType
from app.shared.types.extra_types import JSONObject


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReindexCandidate:
    """One parsed managed note awaiting manifest validation and indexing."""

    path: Path
    payload: ObsidianNoteIndex


def supersedes_context_id(payload: ObsidianNoteIndex) -> str | None:
    """Return the forward supersede reference for a Context note.

    Args:
        payload: Parsed managed note index payload.

    Returns:
        Superseded Context ID, or None.
    """
    if payload.alexandria_type is not AlexandriaNoteType.CONTEXT:
        return None
    return _json_text(payload.frontmatter, "supersedes_context_id")


def manifest_frontmatter_text(payload: ObsidianNoteIndex, key: str) -> str | None:
    """Return one string-only manifest field from normalized frontmatter.

    Args:
        payload: Parsed managed note index payload.
        key: Frontmatter field used by the native manifest wire.

    Returns:
        String value when present with the expected type, otherwise None.
    """
    return _json_text(payload.frontmatter, key)


def _json_text(frontmatter: JSONObject, key: str) -> str | None:
    """Return one frontmatter value only when it is a string.

    Args:
        frontmatter: Normalized frontmatter object.
        key: Field to read.

    Returns:
        String field value, otherwise None.
    """
    value = frontmatter.get(key)
    return value if isinstance(value, str) else None
