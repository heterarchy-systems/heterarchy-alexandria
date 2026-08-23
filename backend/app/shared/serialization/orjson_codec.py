"""Shared JSON serialization helper module."""

from __future__ import annotations

from typing import cast

import orjson

from app.shared.types.extra_types import JSONValue


# Broad type justified: orjson default callback can receive unsupported arbitrary objects.
def _json_default(value: object) -> str:
    """Safely convert unsupported JSON values to strings.

    Args:
        value: Unsupported value received from orjson.

    Returns:
        String representation for fallback serialization.
    """
    return str(value)


def dumps_json(value: JSONValue) -> bytes:
    """Serialize a JSON-compatible value with orjson.

    Args:
        value: JSON-compatible value.

    Returns:
        Serialized UTF-8 JSON bytes.
    """
    return orjson.dumps(
        value,
        default=_json_default,
        option=orjson.OPT_UTC_Z,
    )


def dumps_pretty_json(value: JSONValue) -> bytes:
    """Serialize a JSON-compatible value with stable indentation.

    Args:
        value: JSON-compatible value.

    Returns:
        Indented serialized UTF-8 JSON bytes.
    """
    return orjson.dumps(
        value,
        default=_json_default,
        option=orjson.OPT_INDENT_2 | orjson.OPT_UTC_Z,
    )


def dumps_canonical_json(value: JSONValue) -> bytes:
    """Serialize compact JSON with deterministic key ordering.

    Args:
        value: JSON-compatible value.

    Returns:
        Canonical UTF-8 JSON bytes suitable for hashing.
    """
    return orjson.dumps(
        value,
        default=_json_default,
        option=orjson.OPT_SORT_KEYS | orjson.OPT_UTC_Z,
    )


def dumps_sorted_pretty_json(value: JSONValue) -> bytes:
    """Serialize indented JSON with deterministic key ordering.

    Args:
        value: JSON-compatible value.

    Returns:
        Stable, indented UTF-8 JSON bytes.
    """
    return orjson.dumps(
        value,
        default=_json_default,
        option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS | orjson.OPT_UTC_Z,
    )


def loads_json(value: bytes | str) -> JSONValue:
    """Deserialize JSON bytes or text through the shared codec.

    Args:
        value: Serialized JSON bytes or text.

    Returns:
        JSON-compatible decoded value.
    """
    decoded = orjson.loads(value)
    json_value = cast(JSONValue, decoded)
    return json_value
