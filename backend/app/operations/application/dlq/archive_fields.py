"""Lenient field readers for persisted maintenance DLQ archives."""

from collections.abc import Sequence
from datetime import datetime

from app.shared.types.extra_types import JSONValue


def archive_string(value: JSONValue, default: str) -> str:
    """Return a persisted string field or its legacy fallback."""
    return value if isinstance(value, str) else default


def archive_string_or_none(value: JSONValue) -> str | None:
    """Return a persisted string field, preserving a missing or invalid value."""
    return value if isinstance(value, str) else None


def archive_integer(value: JSONValue) -> int:
    """Return an integer field without accepting booleans as integers."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def archive_datetime_or_none(value: JSONValue) -> datetime | None:
    """Read an aware ISO timestamp; malformed and naive values remain absent."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def archive_string_tuple(value: JSONValue) -> tuple[str, ...]:
    """Keep ordered string members of a legacy archive sequence."""
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, str))
