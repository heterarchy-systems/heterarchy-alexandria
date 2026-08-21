"""Shared datetime schema contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from app.shared.types.extra_types import JSONValue
from pydantic import (
    AwareDatetime,
    TypeAdapter,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    WrapValidator,
)

_AWARE_DATETIME_ADAPTER = TypeAdapter(AwareDatetime)


def _validate_aware_datetime(
    value: datetime | JSONValue,
    handler: ValidatorFunctionWrapHandler,
    info: ValidationInfo,
) -> datetime:
    """Preserve strict Python datetime inputs while accepting ISO JSON strings.

    Args:
        value: Raw value received by Pydantic before datetime parsing.
        handler: Pydantic's strict downstream datetime validator.
        info: Validation context used to distinguish JSON and Python modes.

    Returns:
        Validated timezone-aware datetime.

    Raises:
        ValueError: When the value is numeric.
        TypeError: When the downstream validator returns a non-datetime value.
    """
    if isinstance(value, int | float):
        raise ValueError("datetime value must be an ISO-8601 string")
    if info.mode == "json" and isinstance(value, str):
        return _AWARE_DATETIME_ADAPTER.validate_python(value)
    validated = handler(value)
    if not isinstance(validated, datetime):
        raise TypeError("aware datetime validator returned a non-datetime value")
    return validated


type AwareTimestamp = Annotated[
    AwareDatetime,
    WrapValidator(_validate_aware_datetime),
]
