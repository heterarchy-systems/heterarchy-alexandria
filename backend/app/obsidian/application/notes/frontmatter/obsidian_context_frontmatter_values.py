"""Scalar normalization and error translation for Context frontmatter."""

from __future__ import annotations

from pydantic import ValidationError

from app.memory.domain.event_enum.context_enums import ContextKind
from app.obsidian.domain.event_enum.obsidian_enums import (
    ObsidianContextLifecycleStatus,
)
from app.shared.type_validation.frontmatter_metadata_normalization import (
    normalize_string_collection,
)
from app.shared.types.extra_types import JSONObject, JSONValue


def string_or_none(value: JSONValue) -> str | None:
    """Return trimmed frontmatter text or ``None`` for null-like values.

    Args:
        value: Raw JSON-compatible frontmatter value.

    Returns:
        Trimmed text when present.

    Raises:
        ValueError: If the value is not a string or null.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("frontmatter scalar must be a string")
    text = value.strip()
    if not text:
        return None
    return text


def normalized_context_version(value: JSONValue) -> int | None:
    """Normalize an optional decimal Context version from frontmatter.

    Args:
        value: Raw JSON-compatible version scalar.

    Returns:
        Integer version, or None when the field is absent.

    Raises:
        ValueError: If the value is not an integer or decimal integer text.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("version must be an integer")
    if isinstance(value, int):
        if value >= 1:
            return value
        raise ValueError("version must be a positive integer")
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdecimal():
            parsed = int(normalized)
            if parsed >= 1:
                return parsed
        raise ValueError("version must be a positive integer")
    raise ValueError("version must be an integer")


def normalized_scope_text(value: JSONValue) -> str | None:
    """Normalize scope-like text to uppercase underscore spelling.

    Args:
        value: Raw JSON-compatible frontmatter value.

    Returns:
        Canonical scope text when present.
    """
    return normalized_uppercase_text(value)


def normalized_status_text(value: JSONValue) -> str | None:
    """Normalize lifecycle text to lowercase underscore spelling.

    Args:
        value: Raw JSON-compatible frontmatter value.

    Returns:
        Canonical lifecycle text when present.
    """
    text = string_or_none(value)
    if text is None:
        return None
    return text.lower().replace("-", "_").replace(" ", "_")


def normalized_content_hash(value: JSONValue) -> str | None:
    """Normalize and validate an optional SHA-256 content digest.

    Args:
        value: Raw content hash value.

    Returns:
        Lowercase SHA-256 digest when present.

    Raises:
        ValueError: If the value is not a SHA-256 hexadecimal digest.
    """
    text = string_or_none(value)
    if text is None:
        return None
    normalized = text.lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("content_hash must be a SHA-256 hex digest")
    return normalized


def normalized_legacy_timestamp(value: JSONValue) -> JSONValue:
    """Expand a legacy date-only value to an aware UTC timestamp string.

    Args:
        value: Raw timestamp value.

    Returns:
        Expanded timestamp text for date-only strings, otherwise the input value.
    """
    if isinstance(value, str) and len(value.strip()) == 10:
        return f"{value.strip()}T00:00:00Z"
    return value


def normalized_uppercase_text(value: JSONValue) -> str | None:
    """Normalize enum-like text to the repository uppercase convention.

    Args:
        value: Raw JSON-compatible frontmatter value.

    Returns:
        Canonical uppercase text when present.
    """
    text = string_or_none(value)
    if text is None:
        return None
    return text.upper().replace("-", "_").replace(" ", "_")


def reference_tuple(value: JSONValue) -> tuple[str, ...]:
    """Normalize a provenance reference sequence.

    Args:
        value: Raw provenance reference collection.

    Returns:
        Immutable normalized reference values.

    Raises:
        ValueError: If the collection or an item has an invalid type.
    """
    try:
        return tuple(normalize_string_collection(value))
    except ValueError as exc:
        raise ValueError(
            "provenance references must be a flat string collection"
        ) from exc


def lifecycle_status_value(
    frontmatter_status: ObsidianContextLifecycleStatus | None,
    note_status: str,
) -> ObsidianContextLifecycleStatus:
    """Resolve frontmatter and note-level lifecycle status values.

    Args:
        frontmatter_status: Validated explicit frontmatter status.
        note_status: Legacy note status text.

    Returns:
        Canonical Context lifecycle status.

    Raises:
        ValueError: If the legacy note status is invalid.
    """
    if frontmatter_status is not None:
        return frontmatter_status
    try:
        return ObsidianContextLifecycleStatus.from_frontmatter_text(note_status)
    except ValueError as exc:
        raise ValueError(f"INVALID_STATUS: {note_status}") from exc


def legacy_context_kind(value: str | None) -> ContextKind:
    """Resolve a Context kind from the legacy generic kind field.

    Args:
        value: Normalized legacy kind text.

    Returns:
        Matching Context kind, defaulting to memory.
    """
    if value is None:
        return ContextKind.MEMORY
    try:
        return ContextKind(value)
    except ValueError:
        return ContextKind.MEMORY


def frontmatter_context_id(frontmatter: JSONObject) -> str | None:
    """Read the optional stable Context identifier from raw frontmatter.

    Args:
        frontmatter: Parsed frontmatter payload.

    Returns:
        Trimmed identifier when the field is a non-empty string.
    """
    value = frontmatter.get("id")
    if not isinstance(value, str):
        return None
    return value.strip() or None


def frontmatter_validation_message(error: ValidationError) -> str:
    """Translate Pydantic failures into stable Context validation messages.

    Args:
        error: Pydantic validation failure from the boundary model.

    Returns:
        Stable domain-facing validation message.
    """
    invalid_fields = {
        str(item["loc"][0]) for item in error.errors(include_url=False) if item["loc"]
    }
    if "status" in invalid_fields:
        return "INVALID_STATUS: Context frontmatter status is invalid"
    if "scope" in invalid_fields:
        return "INVALID_SCOPE: Context frontmatter scope is invalid"
    if "content_hash" in invalid_fields or "version" in invalid_fields:
        return "INVALID_CONTENT_INTEGRITY: Context hash or version is invalid"
    if "memory_function" in invalid_fields:
        return "INVALID_MEMORY_FUNCTION: Context memory function is invalid"
    provenance_fields = {
        "provenance",
        "source_actor_id",
        "source_actor_type",
        "source_run_id",
        "external_run_id",
        "artifact_refs",
        "evidence_refs",
        "confidence",
    }
    if invalid_fields & provenance_fields:
        return "INVALID_PROVENANCE: Context frontmatter provenance is invalid"
    return "INVALID_SCOPE_IDENTITY: Context frontmatter identity is invalid"
