"""Shared JSON serialization helper module."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import orjson

from app.shared.types.extra_types import JSONValue

type SerializableJSONValue = JSONValue | Mapping[str, object] | Sequence[object]


_STRICT_ORJSON_OPTIONS = (
    orjson.OPT_PASSTHROUGH_DATETIME
    | orjson.OPT_PASSTHROUGH_DATACLASS
    | orjson.OPT_PASSTHROUGH_SUBCLASS
)


def dumps_strict_json(value: object) -> bytes:
    """Serialize a strictly JSON-compatible value with orjson, rejecting NaN/Inf.

    Args:
        value: Strictly JSON-compatible value.

    Returns:
        Serialized UTF-8 JSON bytes.

    Raises:
        TypeError: When the value contains non-JSON types.
        ValueError: When the value contains NaN or infinite floats.
    """

    def reject_non_finite_floats(candidate: object) -> None:
        """Recursively validate that no float in candidate is NaN or infinite.

        Args:
            candidate: Value or nested container element to inspect.

        Raises:
            ValueError: If candidate or any nested element is a non-finite float.
        """
        if isinstance(candidate, float):
            if not math.isfinite(candidate):
                raise ValueError("Out of range float values are not JSON compliant")
            return
        if isinstance(candidate, Mapping):
            for key, item in candidate.items():
                reject_non_finite_floats(key)
                reject_non_finite_floats(item)
            return
        if isinstance(candidate, Sequence) and not isinstance(
            candidate, (str, bytes, bytearray)
        ):
            for item in candidate:
                reject_non_finite_floats(item)

    reject_non_finite_floats(value)
    return orjson.dumps(value, option=_STRICT_ORJSON_OPTIONS)


def dumps_json(value: SerializableJSONValue) -> bytes:
    """Serialize a JSON-compatible value with orjson.

    Args:
        value: JSON-compatible value.

    Returns:
        Serialized UTF-8 JSON bytes.
    """
    return orjson.dumps(
        value,
        default=str,
        option=orjson.OPT_UTC_Z,
    )


def dumps_pretty_json(value: SerializableJSONValue) -> bytes:
    """Serialize a JSON-compatible value with stable indentation.

    Args:
        value: JSON-compatible value.

    Returns:
        Indented serialized UTF-8 JSON bytes.
    """
    return orjson.dumps(
        value,
        default=str,
        option=orjson.OPT_INDENT_2 | orjson.OPT_UTC_Z,
    )


def dumps_canonical_json(value: SerializableJSONValue) -> bytes:
    """Serialize compact JSON with deterministic key ordering.

    Args:
        value: JSON-compatible value.

    Returns:
        Canonical UTF-8 JSON bytes suitable for hashing.
    """
    return orjson.dumps(
        value,
        default=str,
        option=orjson.OPT_SORT_KEYS | orjson.OPT_UTC_Z,
    )


def loads_json(value: bytes | str) -> JSONValue:
    """Deserialize JSON bytes or text through the shared codec.

    Args:
        value: Serialized JSON bytes or text.

    Returns:
        JSON-compatible decoded value.
    """
    decoded: JSONValue = orjson.loads(value)
    return decoded
