"""Shared normalization for type-sensitive frontmatter metadata."""

from __future__ import annotations

from enum import StrEnum

from app.shared.types.extra_types import JSONValue


class StringCollectionField(StrEnum):
    """Known frontmatter fields whose values normalize to string lists."""

    TAGS = "tags"
    ARTIFACT_REFS = "artifact_refs"
    EVIDENCE_REFS = "evidence_refs"
    CONFLICT_SET_IDS = "conflict_set_ids"
    EVIDENCE_URLS = "evidence_urls"
    LINKED_NOTE_IDS = "linked_note_ids"
    REDACTION_WARNINGS = "redaction_warnings"
    REQUIRED_TOOLS = "required_tools"
    SUPERSEDES = "supersedes"
    WHEN_NOT_TO_USE = "when_not_to_use"
    WHEN_TO_USE = "when_to_use"


class BooleanField(StrEnum):
    """Known frontmatter fields whose values normalize to booleans."""

    ACTIVATE_REQUESTED = "activate_requested"
    IS_CURRENT = "is_current"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    SAFE_TO_PUBLISH = "safe_to_publish"
    SOURCE_OF_TRUTH = "source_of_truth"


def normalize_string_collection(value: JSONValue) -> list[str]:
    """Return a canonical ordered collection of unique non-empty strings.

    Args:
        value: Raw JSON-compatible metadata value.

    Returns:
        Trimmed, de-duplicated strings in their original order.

    Raises:
        ValueError: If the input is not a supported flat string collection.
    """
    collection = _string_collection_input(value)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in collection:
        if not isinstance(item, str):
            raise ValueError("string collection items must be strings")
        text = item.strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def normalize_boolean_metadata(value: JSONValue) -> bool:
    """Normalize only explicit boolean values and true/false strings.

    Args:
        value: Raw JSON-compatible metadata value.

    Returns:
        Canonical boolean value.

    Raises:
        ValueError: If the value is not true or false.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError("boolean metadata must be true or false")


def normalize_known_frontmatter_metadata(frontmatter: dict[str, JSONValue]) -> None:
    """Normalize known collection and boolean fields in place.

    Args:
        frontmatter: Mutable save-boundary metadata.
    """
    for field in StringCollectionField:
        field_name = field.value
        if field_name in frontmatter:
            frontmatter[field_name] = normalize_string_collection(
                frontmatter[field_name]
            )
    for field in BooleanField:
        field_name = field.value
        if field_name in frontmatter:
            frontmatter[field_name] = normalize_boolean_metadata(
                frontmatter[field_name]
            )


def _string_collection_input(
    value: JSONValue,
) -> list[JSONValue] | tuple[JSONValue, ...]:
    """Execute string collection input.

    Args:
        value: Value being processed.

    Returns:
        list[JSONValue] | tuple[JSONValue, ...] result produced by string collection input.
    """
    if value is None:
        return []
    if isinstance(value, list | tuple):
        if any(
            isinstance(item, str)
            and _looks_like_collection_representation(item.strip())
            for item in value
        ):
            raise ValueError("string collection legacy representation is not accepted")
        return value
    if not isinstance(value, str):
        raise ValueError("string collection must be a string, list, tuple, or null")
    stripped = value.strip()
    if not stripped:
        return []
    if _looks_like_collection_representation(stripped):
        raise ValueError("string collection legacy representation is not accepted")
    return [stripped]


def _looks_like_collection_representation(value: str) -> bool:
    """Execute looks like collection representation.

    Args:
        value: Value being processed.

    Returns:
        Whether looks like collection representation.
    """
    if value.startswith("(") and value.endswith(")"):
        return True
    if value.startswith("[") and value.endswith("]"):
        return True
    if value.startswith("{") and value.endswith("}"):
        return True
    return value.startswith(("set(", "frozenset(")) and value.endswith(")")
