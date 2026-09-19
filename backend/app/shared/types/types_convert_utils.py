"""Shared conversion helpers for interface payload values."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from app.shared.exceptions.common_exceptions import BoundaryValidationError
from app.shared.types.extra_types import JSONValue


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
