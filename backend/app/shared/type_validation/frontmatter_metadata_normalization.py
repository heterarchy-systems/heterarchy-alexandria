"""Shared normalization for type-sensitive frontmatter metadata."""

from __future__ import annotations

from app.shared.type_validation.frontmatter_metadata_enums import (
    BooleanField,
    StringCollectionField,
)
from app.shared.types.extra_types import JSONValue

__all__ = (
    "BooleanField",
    "StringCollectionField",
    "normalize_boolean_metadata",
    "normalize_known_frontmatter_metadata",
    "normalize_string_collection",
)


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
    """Coerce a raw frontmatter value into a flat sequence for string validation.

    Args:
        value: Raw JSON-compatible metadata value.

    Returns:
        Sequence of candidate items to normalize.

    Raises:
        ValueError: If `value` is not a string/sequence/null or uses a legacy collection literal.
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
    """Return whether a string looks like a serialized Python collection literal.

    Args:
        value: Trimmed string candidate to inspect.

    Returns:
        True when the string is bracketed like a tuple, list, set, or dict repr.
    """
    if value.startswith("(") and value.endswith(")"):
        return True
    if value.startswith("[") and value.endswith("]"):
        return True
    if value.startswith("{") and value.endswith("}"):
        return True
    return value.startswith(("set(", "frozenset(")) and value.endswith(")")
