"""Typed narrowing primitives for decoded native compute wire payloads.

Each native compute adapter validates the JSON emitted by the Rust extension
before mapping it into domain contracts. The primitives here own the shared
narrowing semantics so adapters do not re-implement them per provider.
"""

from __future__ import annotations

from app.shared.types.extra_types import JSONValue


def wire_object(
    value: JSONValue | None, field: str, error_code: str
) -> dict[str, JSONValue]:
    """Narrow one decoded wire value to a JSON object.

    Args:
        value: Decoded JSON value for the field.
        field: Field name used in diagnostics.
        error_code: Stable machine-readable error code prefix.

    Returns:
        String-keyed JSON object.

    Raises:
        ValueError: If the value is not an object.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{error_code}: {field} must be an object")
    return value


def wire_array(value: JSONValue | None, field: str, error_code: str) -> list[JSONValue]:
    """Narrow one decoded wire value to a JSON array.

    Args:
        value: Decoded JSON value for the field.
        field: Field name used in diagnostics.
        error_code: Stable machine-readable error code prefix.

    Returns:
        Decoded JSON array.

    Raises:
        ValueError: If the value is not an array.
    """
    if not isinstance(value, list):
        raise ValueError(f"{error_code}: {field} must be an array")
    return value


def wire_required_text(value: dict[str, JSONValue], key: str, error_code: str) -> str:
    """Read one required non-empty text field from a decoded wire object.

    Args:
        value: Decoded JSON object.
        key: Required field name.
        error_code: Stable machine-readable error code prefix.

    Returns:
        Non-empty string field value.

    Raises:
        ValueError: If the field is missing, empty, or not text.
    """
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{error_code}: invalid {key}")
    return raw


def wire_integer(value: dict[str, JSONValue], key: str, error_code: str) -> int:
    """Read one required non-negative integer field from a decoded wire object.

    Args:
        value: Decoded JSON object.
        key: Required field name.
        error_code: Stable machine-readable error code prefix.

    Returns:
        Non-negative integer field value.

    Raises:
        ValueError: If the field is missing, not an integer, or negative.
    """
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ValueError(f"{error_code}: invalid {key}")
    return raw
