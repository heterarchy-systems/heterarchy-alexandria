"""Shared conversion helpers for interface payload values."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from app.shared.exceptions.common_exceptions import BoundaryValidationError
from app.shared.types.extra_types import JSONObject, JSONValue


def now_utc() -> datetime:
    """Return the current UTC timestamp.

    Returns:
        datetime: Timezone-aware current timestamp in UTC.
    """
    return datetime.now(UTC)


def aware_utc_datetime(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    Args:
        value: Datetime from an internal or persistence boundary.

    Returns:
        UTC-aware datetime. Naive legacy values are normalized to UTC at the
        compatibility boundary.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def optional_iso_utc_datetime(value: str | None) -> datetime | None:
    """Parse an optional ISO-8601 timestamp into a UTC-aware datetime.

    Args:
        value: Optional ISO-8601 timestamp text. ``Z`` suffixes are accepted and
            naive values are treated as UTC for legacy persistence boundaries.

    Returns:
        UTC-aware datetime when parsing succeeds, otherwise ``None``.
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return aware_utc_datetime(parsed)


def required_datetime_value(value: JSONValue | None, field_name: str) -> datetime:
    """Return a required datetime from an interface payload value.

    Args:
        value: Interface payload value to validate.
        field_name: Field name used in validation errors.

    Returns:
        datetime: Validated datetime value.

    Raises:
        BoundaryValidationError: When the value is not a datetime.
    """
    if isinstance(value, datetime):
        return aware_utc_datetime(value)
    raise BoundaryValidationError(f"{field_name} must be a datetime")


def required_string_value(value: JSONValue | None, field_name: str) -> str:
    """Return a required string from an interface payload value.

    Args:
        value: Interface payload value to validate.
        field_name: Field name used in validation errors.

    Returns:
        str: Validated string value.

    Raises:
        BoundaryValidationError: When the value is not a string.
    """
    if isinstance(value, str):
        return value
    raise BoundaryValidationError(f"{field_name} must be a string")


def optional_string_value(value: JSONValue | None) -> str | None:
    """Return an optional string from an interface payload value.

    Args:
        value: Interface payload value to narrow.

    Returns:
        str | None: String value when present and typed, otherwise ``None``.
    """
    if isinstance(value, str):
        return value
    return None


def string_value(value: JSONValue | None, default: str = "") -> str:
    """Return a string value or a caller-provided default.

    Args:
        value: Interface payload value to narrow.
        default: Fallback string for missing or mistyped values.

    Returns:
        str: String value or fallback default.
    """
    if isinstance(value, str):
        return value
    return default


def bool_value(value: JSONValue | None, default: bool = False) -> bool:
    """Return a boolean value or a caller-provided default.

    Args:
        value: Interface payload value to narrow.
        default: Fallback boolean for missing or mistyped values.

    Returns:
        bool: Boolean value or fallback default.
    """
    if isinstance(value, bool):
        return value
    return default


def json_object_value(value: JSONValue | None) -> JSONObject:
    """Return a JSON object from an interface payload value.

    Args:
        value: Interface payload value to narrow.

    Returns:
        JSONObject: Dictionary payload when typed, otherwise an empty object.
    """
    if isinstance(value, dict):
        return value
    return {}


def string_items(value: JSONValue | None) -> list[str]:
    """Return string items from an interface payload list.

    Args:
        value: Interface payload value expected to hold a list.

    Returns:
        list[str]: String members only, or an empty list for non-list values.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def string_int_items(value: JSONValue | None) -> list[str | int]:
    """Return string and integer items from an interface payload list.

    Args:
        value: Interface payload value expected to hold a list.

    Returns:
        list[str | int]: String and non-boolean integer members only.
    """
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, str)
        or (isinstance(item, int) and not isinstance(item, bool))
    ]


def enum_value[EnumValue: StrEnum](
    value: JSONValue | EnumValue | None,
    enum_type: type[EnumValue],
    field_name: str,
) -> EnumValue:
    """Return a typed string enum from an interface payload value.

    Args:
        value: Interface payload value to validate.
        enum_type: Target ``StrEnum`` subclass.
        field_name: Field name used in validation errors.

    Returns:
        EnumValue: Enum instance matching the input value.

    Raises:
        BoundaryValidationError: When the value is not a valid enum string.
    """
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            raise BoundaryValidationError(
                f"{field_name} must be a valid string"
            ) from exc
    raise BoundaryValidationError(f"{field_name} must be a valid string")
