"""Boundary-specific scalar decoding for Redis and persisted JSON."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from app.operations.application.maintenance_job_queue import (
    MaintenanceQueueUnavailableError,
)
from app.shared.types.extra_types import JSONValue
from app.shared.types.redis_types import RedisResponse


class RedisValueDecoder:
    """Decode Redis sequences, text and integer scalar replies."""

    @staticmethod
    def sequence(raw: RedisResponse, field: str) -> Sequence[RedisResponse]:
        """Validate that a raw Redis reply is a list or tuple sequence.

        Args:
            raw: Raw Redis command reply value.
            field: Logical Redis field name for error reporting.

        Returns:
            Validated Redis response sequence.

        Raises:
            MaintenanceQueueUnavailableError: If the reply is not a list or tuple.
        """
        if isinstance(raw, list | tuple):
            return raw
        raise MaintenanceQueueUnavailableError(f"Redis {field} must be a sequence")

    @staticmethod
    def text(raw: RedisResponse, field: str) -> str:
        """Decode a raw Redis scalar reply into a UTF-8 text string.

        Args:
            raw: Raw Redis command reply value.
            field: Logical Redis field name for error reporting.

        Returns:
            Decoded UTF-8 string value.

        Raises:
            MaintenanceQueueUnavailableError: If the reply is not valid UTF-8 text.
        """
        if isinstance(raw, bytes):
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MaintenanceQueueUnavailableError(
                    f"Redis {field} is not valid UTF-8"
                ) from exc
        if isinstance(raw, str):
            return raw
        if isinstance(raw, int):
            return str(raw)
        raise MaintenanceQueueUnavailableError(f"Redis {field} must be text")

    @staticmethod
    def text_integer(value: str, field: str) -> int:
        """Parse a base-10 integer from a decoded Redis string field.

        Args:
            value: Decoded string representation of an integer.
            field: Logical Redis field name for error reporting.

        Returns:
            Parsed integer value.

        Raises:
            MaintenanceQueueUnavailableError: If the string is not a valid integer.
        """
        try:
            return int(value)
        except ValueError as exc:
            raise MaintenanceQueueUnavailableError(
                f"Redis maintenance field must be an integer: {field}"
            ) from exc

    @staticmethod
    def integer(raw: RedisResponse, field: str) -> int:
        """Decode a raw Redis scalar reply into a non-boolean integer.

        Args:
            raw: Raw Redis command reply value.
            field: Logical Redis field name for error reporting.

        Returns:
            Decoded integer value.

        Raises:
            MaintenanceQueueUnavailableError: If the reply cannot be decoded as an integer.
        """
        if isinstance(raw, bool):
            raise MaintenanceQueueUnavailableError(f"Redis {field} must be an integer")
        if isinstance(raw, int):
            return raw
        return RedisValueDecoder.text_integer(RedisValueDecoder.text(raw, field), field)


class RedisStatusValueDecoder:
    """Preserve status-field presence, whitespace, enum, and datetime semantics."""

    @staticmethod
    def required(value: str | None, field: str) -> str:
        """Require a non-empty Redis status hash string field.

        Args:
            value: Optional status hash field value.
            field: Logical status field name for error reporting.

        Returns:
            Present non-empty string value.

        Raises:
            MaintenanceQueueUnavailableError: If the value is None or empty.
        """
        if value is None or not value:
            raise MaintenanceQueueUnavailableError(
                f"Redis maintenance status field is missing: {field}"
            )
        return value

    @staticmethod
    def parse_enum[EnumT: StrEnum](
        enum_cls: type[EnumT], value: str, field: str
    ) -> EnumT:
        """Coerce a Redis status hash string into a validated StrEnum member.

        Args:
            enum_cls: Target StrEnum class to instantiate.
            value: Raw string value from the Redis status or stream hash.
            field: Logical status field name for error reporting.

        Returns:
            Validated StrEnum member.

        Raises:
            MaintenanceQueueUnavailableError: If the value is not a valid member
                of ``enum_cls``.
        """
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise MaintenanceQueueUnavailableError(
                f"Redis maintenance enum is invalid: {field}"
            ) from exc

    @staticmethod
    def parse_datetime(value: str, field: str) -> datetime:
        """Parse an ISO-8601 timestamp from a Redis status hash field.

        Args:
            value: ISO-8601 datetime string.
            field: Logical status field name for error reporting.

        Returns:
            Parsed datetime instance.

        Raises:
            MaintenanceQueueUnavailableError: If the string is not valid ISO-8601.
        """
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise MaintenanceQueueUnavailableError(
                f"Redis maintenance datetime is invalid: {field}"
            ) from exc

    @staticmethod
    def optional_datetime(value: str | None, field: str) -> datetime | None:
        """Parse an optional ISO-8601 timestamp, treating blank strings as None.

        Args:
            value: Optional ISO-8601 datetime string.
            field: Logical status field name for error reporting.

        Returns:
            Parsed datetime instance, or None when absent or blank.

        Raises:
            MaintenanceQueueUnavailableError: If present and not valid ISO-8601.
        """
        normalized = RedisStatusValueDecoder.nonblank(value)
        if normalized is None:
            return None
        return RedisStatusValueDecoder.parse_datetime(normalized, field)

    @staticmethod
    def nonblank(value: str | None) -> str | None:
        """Strip surrounding whitespace and normalize empty strings to None.

        Args:
            value: Optional string value to normalize.

        Returns:
            Stripped non-empty string, or None when absent or blank.
        """
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class JsonResultValueDecoder:
    """Validate primitive values in persisted maintenance result JSON."""

    @staticmethod
    def integer(raw: JSONValue, field: str) -> int:
        """Validate that a persisted JSON result field is a non-boolean integer.

        Args:
            raw: Decoded JSON value for the field.
            field: Logical JSON field name for error reporting.

        Returns:
            Validated integer value.

        Raises:
            MaintenanceQueueUnavailableError: If the value is not a non-boolean integer.
        """
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise MaintenanceQueueUnavailableError(
                f"Redis maintenance result field must be an integer: {field}"
            )
        return raw

    @staticmethod
    def text(raw: JSONValue, field: str) -> str:
        """Validate that a persisted JSON result field is a string.

        Args:
            raw: Decoded JSON value for the field.
            field: Logical JSON field name for error reporting.

        Returns:
            Validated string value.

        Raises:
            MaintenanceQueueUnavailableError: If the value is not a string.
        """
        if not isinstance(raw, str):
            raise MaintenanceQueueUnavailableError(
                f"Redis maintenance result field must be text: {field}"
            )
        return raw

    @staticmethod
    def optional_text(raw: JSONValue) -> str | None:
        """Validate that a persisted JSON result field is either None or a string.

        Args:
            raw: Decoded JSON value for the optional field.

        Returns:
            Validated string value, or None.

        Raises:
            MaintenanceQueueUnavailableError: If the value is neither None nor a string.
        """
        if raw is None:
            return None
        return JsonResultValueDecoder.text(raw, "optional text")
